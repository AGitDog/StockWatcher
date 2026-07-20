from __future__ import annotations

import csv
import json
from functools import lru_cache
from io import StringIO
from datetime import datetime
from pathlib import Path
import re
from typing import Any

import pandas as pd
import requests
import yfinance as yf

try:
    from google import genai
    _GEMINI_AVAILABLE = True
except ImportError:
    _GEMINI_AVAILABLE = False


DEFAULT_ANALYST_LOOKBACK_DAYS = 120
DEFAULT_NEWS_ITEMS = 5
DEFAULT_MAPPING_FILE = "stock_mappings.txt"
DEFAULT_WATCHLIST_DIR = "watchlists"
DEFAULT_ALERT_LOOKAHEAD_DAYS = 30
DEFAULT_SIGNAL_NEWS_WINDOW_DAYS = 7
DEFAULT_SIGNAL_HISTORY_DIR = "signal_history"
INDEX_DEFINITIONS = {
    "DAX": {
        "aliases": {"DAX", "INDEX:DAX", "^GDAXI"},
        "url": "https://en.wikipedia.org/wiki/DAX",
        "table_index": 4,
        "ticker_column": "Ticker",
    },
    "S&P 500": {
        "aliases": {"S&P500", "S&P 500", "SP500", "INDEX:S&P500", "INDEX:S&P 500", "^GSPC"},
        "url": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "table_index": 0,
        "ticker_column": "Symbol",
    },
    "Dow Jones": {
        "aliases": {"DOW", "DOW JONES", "DOW JONES INDUSTRIAL AVERAGE", "DJIA", "INDEX:DOW", "^DJI"},
        "url": "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average",
        "table_index": 1,
        "ticker_column": "Symbol",
    },
    "Nasdaq-100": {
        "aliases": {"NASDAQ", "NASDAQ-100", "NASDAQ 100", "NASDAQ100", "NDX", "^NDX", "INDEX:NASDAQ100", "INDEX:NASDAQ-100"},
        "url": "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies",
        "table_index": 0,
        "ticker_column": "Ticker",
    },
    "MDAX": {
        "aliases": {"MDAX", "INDEX:MDAX", "^MDAXI"},
        "url": "https://en.wikipedia.org/wiki/MDAX",
        "table_index": 2,
        "ticker_column": "Symbol",
        "suffix": ".DE",
    },
    "CAC 40": {
        "aliases": {"CAC 40", "CAC40", "CAC", "INDEX:CAC40", "INDEX:CAC 40", "^FCHI"},
        "url": "https://en.wikipedia.org/wiki/CAC_40",
        "table_index": 4,
        "ticker_column": "Ticker",
    },
    "EURO STOXX 50": {
        "aliases": {"EURO STOXX 50", "EURO STOXX", "STOXX 50", "STOXX50E", "INDEX:STOXX50E", "^STOXX50E"},
        "url": "https://en.wikipedia.org/wiki/EURO_STOXX_50",
        "table_index": 3,
        "ticker_column": "Ticker",
    },
    "FTSE 100": {
        "aliases": {"FTSE 100", "FTSE", "FTSE100", "UK100", "INDEX:FTSE", "^FTSE"},
        "url": "https://en.wikipedia.org/wiki/FTSE_100_Index",
        "table_index": 6,
        "ticker_column": "Ticker",
        "suffix": ".L",
    },
    "SMI": {
        "aliases": {"SMI", "SWISS MARKET INDEX", "INDEX:SMI", "^SSMI"},
        "url": "https://en.wikipedia.org/wiki/Swiss_Market_Index",
        "table_index": 2,
        "ticker_column": "Ticker",
        "suffix": ".SW",
    },
    "Nifty 50": {
        "aliases": {"NIFTY", "NIFTY 50", "NIFTY50", "INDEX:NIFTY50", "^NSEI"},
        "url": "https://en.wikipedia.org/wiki/NIFTY_50",
        "table_index": 1,
        "ticker_column": "Symbol",
        "suffix": ".NS",
    },
    "S&P/TSX 60": {
        "aliases": {"TSX 60", "TSX", "S&P/TSX 60", "INDEX:TSX60", "^GSPTSE"},
        "url": "https://en.wikipedia.org/wiki/S%26P/TSX_60",
        "table_index": 1,
        "ticker_column": "Symbol",
        "suffix": ".TO",
    },
    "TecDAX": {
        "aliases": {"TECDAX", "INDEX:TECDAX", "^TECDAXI"},
        "url": "https://de.wikipedia.org/wiki/TecDAX",
        "table_index": 5,
        "ticker_column": "Symbol[9]",
        "suffix": ".DE",
    },
    "Nikkei 225": {
        "aliases": {"NIKKEI", "NIKKEI 225", "NIKKEI225", "^N225", "INDEX:NIKKEI"},
        "url": "https://de.wikipedia.org/wiki/Nikkei_225",
        "table_index": 8,
        "ticker_column": "Code",
        "suffix": ".T",
    },
}


def parse_watchlist_text(file_text: str) -> list[str]:
    """Parse a plain text watchlist into a de-duplicated list of entries."""
    symbols: list[str] = []
    seen: set[str] = set()

    for raw_line in file_text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        for chunk in line.replace(";", ",").split(","):
            symbol = chunk.strip()
            if not symbol:
                continue

            expanded_entries = expand_watchlist_entry(symbol)
            for expanded_symbol in expanded_entries:
                dedupe_key = expanded_symbol.upper()
                if not expanded_symbol or dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                symbols.append(expanded_symbol)

    return symbols


def summarize_index_entries(file_text: str) -> dict[str, list[dict[str, Any]]]:
    supported: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []

    seen_supported: set[str] = set()
    seen_unsupported: set[str] = set()

    for raw_line in file_text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        for chunk in line.replace(";", ",").split(","):
            entry = chunk.strip()
            if not entry:
                continue

            matched_index = _match_index_alias(entry)
            if matched_index:
                dedupe_key = matched_index.upper()
                if dedupe_key in seen_supported:
                    continue
                seen_supported.add(dedupe_key)
                supported.append(
                    {
                        "entry": entry,
                        "index_name": matched_index,
                        "count": len(load_index_constituents(matched_index)),
                    }
                )
                continue

            if _looks_like_index_candidate(entry):
                dedupe_key = entry.upper()
                if dedupe_key in seen_unsupported:
                    continue
                seen_unsupported.add(dedupe_key)
                unsupported.append(
                    {
                        "entry": entry,
                        "reason": "Indexaehnlicher Eintrag, aber aktuell ohne Komponenten-Mapping.",
                    }
                )

    return {"supported": supported, "unsupported": unsupported}


def expand_watchlist_entry(entry: str) -> list[str]:
    normalized = entry.strip()
    if not normalized:
        return []

    index_name = _match_index_alias(normalized)
    if not index_name:
        return [normalized]

    index_symbols = load_index_constituents(index_name)
    return index_symbols or [normalized]


def build_watchlist_summary(file_text: str, mapping_text: str | None = None) -> list[dict[str, Any]]:
    """Build a per-symbol market briefing from a watchlist text file."""
    entries = parse_watchlist_text(file_text)
    symbol_mappings = parse_symbol_mappings(mapping_text or "")
    return [build_symbol_summary(entry, symbol_mappings) for entry in entries]


def build_watchlist_alerts(
    file_text: str,
    mapping_text: str | None = None,
    lookahead_days: int = DEFAULT_ALERT_LOOKAHEAD_DAYS,
) -> list[dict[str, Any]]:
    summaries = build_watchlist_summary(file_text, mapping_text)
    alerts: list[dict[str, Any]] = []

    for item in summaries:
        alert_items: list[str] = []

        if item["analyst_actions"]["items"]:
            alert_items.append(f"Analysten: {item['analyst_actions']['items'][0]}")

        if item["insider_activity"]["items"]:
            alert_items.append(f"Insider: {item['insider_activity']['items'][0]}")

        for next_date in item["next_dates"]:
            date_value = _extract_first_date(next_date)
            if date_value is None:
                continue
            if 0 <= (date_value.date() - datetime.utcnow().date()).days <= lookahead_days:
                alert_items.append(f"Termin: {next_date}")

        if alert_items:
            alerts.append(
                {
                    "symbol": item["symbol"],
                    "name": item["name"],
                    "input_name": item["input_name"],
                    "resolution_note": item["resolution_note"],
                    "items": _dedupe_preserve_order(alert_items),
                }
            )

    return alerts


def build_watchlist_signal_monitor(file_text: str, mapping_text: str | None = None) -> list[dict[str, Any]]:
    entries = parse_watchlist_text(file_text)
    symbol_mappings = parse_symbol_mappings(mapping_text or "")
    results = [build_symbol_signal_monitor(entry, symbol_mappings) for entry in entries]
    enriched_results = add_watchlist_peer_context(results)
    return sorted(enriched_results, key=lambda item: item.get("brodel_score", 0), reverse=True)


def ensure_signal_history_dir(directory: str = DEFAULT_SIGNAL_HISTORY_DIR) -> Path:
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_signal_snapshot(
    watchlist_name: str,
    signal_items: list[dict[str, Any]],
    directory: str = DEFAULT_SIGNAL_HISTORY_DIR,
) -> Path:
    history_dir = ensure_signal_history_dir(directory)
    snapshot_path = history_dir / f"{_sanitize_watchlist_name(watchlist_name).removesuffix('.txt')}.json"
    existing = load_signal_snapshot_history(watchlist_name, directory)
    snapshot = {
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "items": signal_items,
    }
    existing.append(snapshot)
    snapshot_path.write_text(json.dumps(existing, ensure_ascii=True, indent=2), encoding="utf-8")
    return snapshot_path


def load_signal_snapshot_history(
    watchlist_name: str,
    directory: str = DEFAULT_SIGNAL_HISTORY_DIR,
) -> list[dict[str, Any]]:
    history_dir = ensure_signal_history_dir(directory)
    snapshot_path = history_dir / f"{_sanitize_watchlist_name(watchlist_name).removesuffix('.txt')}.json"
    if not snapshot_path.exists():
        return []
    try:
        loaded = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return loaded if isinstance(loaded, list) else []


def build_signal_delta_report(
    current_items: list[dict[str, Any]],
    previous_snapshot: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not previous_snapshot:
        return []

    previous_items = previous_snapshot.get("items", []) if isinstance(previous_snapshot, dict) else []
    previous_by_symbol = {
        str(item.get("symbol")): item
        for item in previous_items
        if isinstance(item, dict) and item.get("symbol")
    }

    deltas: list[dict[str, Any]] = []
    for item in current_items:
        symbol = item.get("symbol")
        previous_item = previous_by_symbol.get(symbol)
        previous_score = int(previous_item.get("brodel_score", 0)) if previous_item else 0
        current_score = int(item.get("brodel_score", 0))
        score_delta = current_score - previous_score

        current_signals = set(item.get("signal_items", []))
        previous_signals = set(previous_item.get("signal_items", [])) if previous_item else set()
        new_signals = sorted(current_signals - previous_signals)

        if previous_item is None:
            change_type = "Neu"
        elif score_delta > 0:
            change_type = "Gestiegen"
        elif score_delta < 0:
            change_type = "Gefallen"
        elif new_signals:
            change_type = "Neue Signale"
        else:
            continue

        deltas.append(
            {
                "symbol": symbol,
                "name": item.get("name"),
                "current_score": current_score,
                "previous_score": previous_score,
                "score_delta": score_delta,
                "change_type": change_type,
                "new_signals": new_signals,
            }
        )

    return sorted(deltas, key=lambda entry: (entry["score_delta"], entry["current_score"]), reverse=True)


def ensure_watchlist_dir(directory: str = DEFAULT_WATCHLIST_DIR) -> Path:
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_watchlist_files(directory: str = DEFAULT_WATCHLIST_DIR) -> list[str]:
    watchlist_dir = ensure_watchlist_dir(directory)
    return sorted(path.name for path in watchlist_dir.glob("*.txt"))


def load_watchlist_file(file_name: str, directory: str = DEFAULT_WATCHLIST_DIR) -> str:
    file_path = ensure_watchlist_dir(directory) / _sanitize_watchlist_name(file_name)
    if not file_path.exists():
        return ""
    return file_path.read_text(encoding="utf-8")


def save_watchlist_file(file_name: str, file_text: str, directory: str = DEFAULT_WATCHLIST_DIR) -> Path:
    watchlist_dir = ensure_watchlist_dir(directory)
    safe_name = _sanitize_watchlist_name(file_name)
    if not safe_name.lower().endswith(".txt"):
        safe_name = f"{safe_name}.txt"

    file_path = watchlist_dir / safe_name
    normalized_lines = [line.rstrip() for line in file_text.splitlines()]
    file_path.write_text("\n".join(normalized_lines).strip() + "\n", encoding="utf-8")
    return file_path


def get_supported_indices() -> list[str]:
    return sorted(INDEX_DEFINITIONS.keys())


@lru_cache(maxsize=16)
def load_index_constituents(index_name: str) -> list[str]:
    config = INDEX_DEFINITIONS.get(index_name)
    if not config:
        return []

    try:
        response = requests.get(config["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        response.raise_for_status()
        tables = pd.read_html(StringIO(response.text))
        constituents = tables[config["table_index"]]
        if config["ticker_column"] not in constituents.columns:
            return []

        symbols = []
        suffix = config.get("suffix", "")
        for raw_symbol in constituents[config["ticker_column"]].dropna().astype(str).tolist():
            symbol = raw_symbol.strip().replace("\n", " ")
            if not symbol:
                continue
            if symbol.endswith(".0"):
                symbol = symbol[:-2]
            if suffix and not symbol.endswith(suffix):
                symbol += suffix
            symbols.append(symbol)
        return symbols
    except Exception:
        return []


def build_symbol_summary(symbol_or_name: str, symbol_mappings: dict[str, str] | None = None) -> dict[str, Any]:
    resolution = resolve_symbol(symbol_or_name, symbol_mappings)
    symbol = resolution["symbol"]

    if not symbol:
        return {
            "symbol": symbol_or_name,
            "name": symbol_or_name,
            "quote_type": "unknown",
            "is_etf": False,
            "input_name": symbol_or_name,
            "resolved": False,
            "resolution_note": "Kein passendes Boersensymbol gefunden.",
            "summary": "Der Eintrag konnte nicht in ein gueltiges Handelssymbol aufgeloest werden.",
            "insider_activity": {"headline": "Keine aktuellen Insiderdaten gefunden.", "items": []},
            "analyst_actions": {"headline": "Keine aktuellen Upgrade/Downgrade-Daten gefunden.", "items": []},
            "next_dates": [],
            "news": [],
        }

    ticker = yf.Ticker(symbol)
    info = _safe_get(lambda: ticker.get_info(), {})
    quote_type = str(info.get("quoteType") or "").lower()
    is_etf = quote_type == "etf"

    long_name = info.get("longName") or info.get("shortName") or symbol

    return {
        "symbol": symbol,
        "name": long_name,
        "quote_type": quote_type or "unknown",
        "is_etf": is_etf,
        "input_name": symbol_or_name,
        "resolved": resolution["resolved"],
        "resolution_note": resolution["note"],
        "summary": _build_business_summary(info, is_etf),
        "insider_activity": _summarize_insider_activity(ticker, is_etf),
        "analyst_actions": _summarize_analyst_actions(ticker),
        "next_dates": _extract_next_dates(ticker, info, is_etf),
        "news": _summarize_news(ticker),
    }



def _summarize_technical_indicators(history: pd.DataFrame | None) -> dict[str, Any]:
    if history is None or history.empty or len(history) < 26:
        return {"name": "Technische Indikatoren", "score": 0, "summary": "Nicht genug Kursdaten fuer Technische Indikatoren."}

    close = pd.to_numeric(history.get("Close"), errors="coerce")
    if close is None or close.isna().all():
        return {"name": "Technische Indikatoren", "score": 0, "summary": "Kursdaten nicht lesbar."}

    # RSI
    delta = close.diff()
    up, down = delta.copy(), delta.copy()
    up[up < 0] = 0
    down[down > 0] = 0
    roll_up = up.ewm(span=14).mean()
    roll_down = down.abs().ewm(span=14).mean()
    rs = roll_up / roll_down
    rsi = 100.0 - (100.0 / (1.0 + rs))
    current_rsi = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0

    # MACD
    exp1 = close.ewm(span=12, adjust=False).mean()
    exp2 = close.ewm(span=26, adjust=False).mean()
    macd = exp1 - exp2
    signal = macd.ewm(span=9, adjust=False).mean()
    current_macd = float(macd.iloc[-1]) if not pd.isna(macd.iloc[-1]) else 0.0
    current_signal = float(signal.iloc[-1]) if not pd.isna(signal.iloc[-1]) else 0.0

    # Bollinger Bands
    ma20 = close.rolling(window=20).mean()
    std20 = close.rolling(window=20).std()
    upper_band = ma20 + (std20 * 2)
    lower_band = ma20 - (std20 * 2)
    current_close = float(close.iloc[-1])
    current_upper = float(upper_band.iloc[-1]) if not pd.isna(upper_band.iloc[-1]) else float('inf')
    current_lower = float(lower_band.iloc[-1]) if not pd.isna(lower_band.iloc[-1]) else 0.0

    score = 0
    parts = []

    # Evaluate RSI
    if current_rsi < 30:
        score += 4
        parts.append(f"RSI: {current_rsi:.1f} (Ueberverkauft)")
    elif current_rsi > 70:
        score -= 4
        parts.append(f"RSI: {current_rsi:.1f} (Ueberkauft)")
    else:
        parts.append(f"RSI: {current_rsi:.1f}")

    # Evaluate MACD
    if current_macd > current_signal:
        score += 3
        parts.append("MACD: Bullisch")
    else:
        score -= 1
        parts.append("MACD: Baerisch")

    # Evaluate Bollinger
    if current_close < current_lower:
        score += 3
        parts.append("Bollinger: Unteres Band")
    elif current_close > current_upper:
        score -= 3
        parts.append("Bollinger: Oberes Band")

    score = max(-8, min(10, score))
    summary = " | ".join(parts)
    return {"name": "Technische Indikatoren", "score": score, "summary": summary}


def _apply_macro_overlay(score: int) -> int:
    try:
        import fred_cache
        spy = _safe_dataframe(lambda: yf.Ticker("SPY").history(period="1y"))
        vix = _safe_dataframe(lambda: yf.Ticker("^VIX").history(period="1mo"))
        
        multiplier = 1.0
        
        if spy is not None and not spy.empty and len(spy) >= 200:
            spy_close = float(spy["Close"].iloc[-1])
            spy_ma200 = float(spy["Close"].tail(200).mean())
            if spy_close > spy_ma200:
                multiplier *= 1.1
            else:
                multiplier *= 0.8
                
        if vix is not None and not vix.empty:
            vix_close = float(vix["Close"].iloc[-1])
            if vix_close > 25:
                multiplier *= 0.9

        # Yield Curve Overlay
        yield_spread = fred_cache.get_yield_curve_spread()
        if yield_spread is not None and yield_spread < 0:
            # Yield curve is inverted (recession signal) -> reduce score
            multiplier *= 0.95
                
        return int(round(score * multiplier))
    except Exception:
        return score


def build_symbol_signal_monitor(symbol_or_name: str, symbol_mappings: dict[str, str] | None = None) -> dict[str, Any]:
    resolution = resolve_symbol(symbol_or_name, symbol_mappings)
    symbol = resolution["symbol"]

    if not symbol:
        return {
            "symbol": symbol_or_name,
            "name": symbol_or_name,
            "input_name": symbol_or_name,
            "resolved": False,
            "resolution_note": "Kein passendes Boersensymbol gefunden.",
            "brodel_score": 0,
            "signal_items": ["Kein gueltiges Symbol verfuegbar."],
            "signal_breakdown": {},
        }

    ticker = yf.Ticker(symbol)
    info = _safe_get(lambda: ticker.get_info(), {})
    quote_type = str(info.get("quoteType") or "").lower()
    name = info.get("longName") or info.get("shortName") or symbol
    history = _safe_dataframe(lambda: ticker.history(period="6mo", auto_adjust=False))

    eps_revision_signal = _summarize_eps_revisions(ticker)
    price_target_signal = _summarize_price_targets(ticker, info, history)
    price_volume_signal = _summarize_price_volume(history)
    news_signal = _summarize_news_intensity(ticker)
    event_signal = _summarize_event_pressure(ticker, info)
    insider_signal = _summarize_insider_signal(ticker, quote_type == "etf")
    short_interest_signal = _summarize_short_interest(info, history)
    relative_strength_signal = _summarize_relative_strength(history, symbol)
    fundamental_signal = _summarize_fundamentals(ticker, info)
    technical_signal = _summarize_technical_indicators(history)

    signal_components = [
        eps_revision_signal,
        price_target_signal,
        price_volume_signal,
        news_signal,
        event_signal,
        insider_signal,
        short_interest_signal,
        relative_strength_signal,
        fundamental_signal,
        technical_signal,
    ]

    raw_score = sum(component["score"] for component in signal_components)
    macro_adjusted_score = _apply_macro_overlay(raw_score)
    brodel_score = max(-30, min(macro_adjusted_score, 100))
    signal_items = [component["summary"] for component in signal_components if component["summary"]]

    return {
        "symbol": symbol,
        "name": name,
        "input_name": symbol_or_name,
        "resolved": resolution["resolved"],
        "resolution_note": resolution["note"],
        "sector": str(info.get("sector") or info.get("category") or "Unbekannt"),
        "industry": str(info.get("industry") or info.get("fundFamily") or "Unbekannt"),
        "brodel_score": brodel_score,
        "signal_items": signal_items,
        "signal_breakdown": {component["name"]: component for component in signal_components},
    }


def load_symbol_mappings(file_path: str = DEFAULT_MAPPING_FILE) -> dict[str, str]:
    path = Path(file_path)
    if not path.exists():
        return {}
    return parse_symbol_mappings(path.read_text(encoding="utf-8"))


def parse_symbol_mappings(mapping_text: str) -> dict[str, str]:
    mappings: dict[str, str] = {}
    for raw_line in mapping_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        raw_name, raw_symbol = line.split("=", 1)
        name = raw_name.strip()
        symbol = raw_symbol.strip().upper()
        if not name or not symbol:
            continue
        mappings[_normalize_text(name)] = symbol
    return mappings


def _sanitize_watchlist_name(file_name: str) -> str:
    base_name = Path(file_name.strip() or "watchlist").name
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", base_name)
    return sanitized.strip("._") or "watchlist.txt"


def _match_index_alias(value: str) -> str | None:
    normalized = value.strip().upper()
    for index_name, config in INDEX_DEFINITIONS.items():
        aliases = {alias.upper() for alias in config.get("aliases", set())}
        if normalized in aliases:
            return index_name
    return None


def _looks_like_index_candidate(value: str) -> bool:
    normalized = value.strip().upper()
    if normalized.startswith("^"):
        return True

    keywords = ("INDEX", "DAX", "DOW", "NASDAQ", "S&P", "FTSE", "MDAX", "TECDAX", "CAC", "NIKKEI")
    return any(keyword in normalized for keyword in keywords)


def resolve_symbol(symbol_or_name: str, symbol_mappings: dict[str, str] | None = None) -> dict[str, Any]:
    candidate = symbol_or_name.strip()
    if not candidate:
        return {"symbol": None, "resolved": False, "note": "Leerer Eintrag."}

    if symbol_mappings:
        mapped_symbol = symbol_mappings.get(_normalize_text(candidate))
        if mapped_symbol:
            return {
                "symbol": mapped_symbol,
                "resolved": True,
                "note": f"Manuelles Mapping auf '{mapped_symbol}'.",
            }

    if _looks_like_symbol(candidate):
        return {
            "symbol": candidate.upper(),
            "resolved": candidate.upper() != candidate,
            "note": "Direkt als Symbol interpretiert.",
        }

    search = _safe_get(lambda: yf.Search(candidate, max_results=10), None)
    quotes = getattr(search, "quotes", []) if search is not None else []
    best_match = _pick_best_quote_match(candidate, quotes)
    if best_match is None:
        return {"symbol": None, "resolved": False, "note": "Yahoo-Finance-Suche lieferte keinen Treffer."}

    name = best_match.get("shortname") or best_match.get("longname") or best_match.get("symbol")
    return {
        "symbol": str(best_match.get("symbol") or "").upper() or None,
        "resolved": True,
        "note": f"Als '{name}' aufgeloest.",
    }


def _looks_like_symbol(candidate: str) -> bool:
    candidate = candidate.strip()
    if not re.fullmatch(r"[A-Za-z0-9.\-^=]{1,15}", candidate):
        return False

    has_letter = any(character.isalpha() for character in candidate)
    if not has_letter:
        return True

    # Treat mixed-case words like company names as search terms, not as ticker symbols.
    return candidate.upper() == candidate or any(character in candidate for character in ".-^=")


def _pick_best_quote_match(candidate: str, quotes: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not quotes:
        return None

    normalized_candidate = _normalize_text(candidate)
    allowed_types = {"equity", "etf"}
    best_item: dict[str, Any] | None = None
    best_score = -1

    for item in quotes:
        quote_type = str(item.get("quoteType") or "").lower()
        if quote_type not in allowed_types:
            continue

        symbol = str(item.get("symbol") or "")
        short_name = str(item.get("shortname") or item.get("longname") or "")
        score = 0

        normalized_name = _normalize_text(short_name)
        normalized_symbol = _normalize_text(symbol)

        if normalized_name == normalized_candidate:
            score += 100
        elif normalized_candidate and normalized_candidate in normalized_name:
            score += 60

        if normalized_symbol == normalized_candidate:
            score += 120

        if quote_type == "equity":
            score += 10
        if quote_type == "etf":
            score += 8

        exchange = str(item.get("exchange") or "")
        if exchange in {"NMS", "NYQ", "ASE", "LSE", "GER", "FRA", "AMS", "MIL", "ASX", "KOE"}:
            score += 5

        base_symbol = symbol.split(".", 1)[0]
        if base_symbol.isalpha():
            score += 8
        if symbol and symbol[0].isdigit():
            score -= 20
        if symbol.endswith(".AX"):
            score += 4

        if score > best_score:
            best_item = item
            best_score = score

    return best_item


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _extract_first_date(value: str) -> datetime | None:
    match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", value)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d")
    except ValueError:
        return None


def _build_business_summary(info: dict[str, Any], is_etf: bool) -> str:
    parts: list[str] = []

    if is_etf:
        category = info.get("category") or info.get("fundFamily")
        if category:
            parts.append(f"ETF-Schwerpunkt: {category}")
    else:
        sector = info.get("sector")
        industry = info.get("industry")
        if sector and industry:
            parts.append(f"Sektor: {sector}, Branche: {industry}")
        elif sector:
            parts.append(f"Sektor: {sector}")

    country = info.get("country")
    currency = info.get("currency")
    if country and currency:
        parts.append(f"Markt: {country} ({currency})")
    elif country:
        parts.append(f"Markt: {country}")

    business_summary = info.get("longBusinessSummary")
    if business_summary:
        snippet = business_summary.strip().replace("\n", " ")
        parts.append(snippet[:240] + ("..." if len(snippet) > 240 else ""))

    return " | ".join(parts) if parts else "Keine Stammdaten verfugbar."


def _summarize_insider_activity(ticker: yf.Ticker, is_etf: bool) -> dict[str, Any]:
    if is_etf:
        return {
            "headline": "Insiderkaeufe sind fuer ETFs in der Regel nicht relevant.",
            "items": [],
        }

    purchases = _safe_dataframe(lambda: ticker.get_insider_purchases())
    transactions = _safe_dataframe(lambda: ticker.get_insider_transactions())

    items: list[str] = []

    if purchases is not None and not purchases.empty:
        recent = purchases.head(5)
        for _, row in recent.iterrows():
            title = _clean_scalar(row.get("Insider")) or _clean_scalar(row.get("insider")) or "Insider"
            shares = _clean_scalar(row.get("Shares")) or _clean_scalar(row.get("shares")) or "n/a"
            value = _clean_scalar(row.get("Value")) or _clean_scalar(row.get("value")) or "n/a"
            items.append(f"{title}: Shares {shares}, Value {value}")

    if not items and transactions is not None and not transactions.empty:
        normalized = transactions.copy()
        columns = {str(column).lower(): column for column in normalized.columns}
        text_columns = [
            columns.get("text"),
            columns.get("insider"),
            columns.get("owner"),
        ]
        transaction_column = columns.get("transaction") or columns.get("startdate")

        for _, row in normalized.head(5).iterrows():
            fragments = []
            for column in text_columns:
                if not column:
                    continue
                cleaned = _clean_scalar(row.get(column))
                if cleaned:
                    fragments.append(cleaned)
            if transaction_column:
                cleaned = _clean_scalar(row.get(transaction_column))
                if cleaned:
                    fragments.append(cleaned)
            if fragments:
                items.append(" | ".join(fragments))

    headline = "Keine aktuellen Insiderdaten gefunden."
    if items:
        headline = f"{len(items)} relevante Insider-Hinweise gefunden."

    return {
        "headline": headline,
        "items": items,
    }


def _summarize_analyst_actions(ticker: yf.Ticker) -> dict[str, Any]:
    upgrades = _safe_dataframe(lambda: ticker.get_upgrades_downgrades())
    if upgrades is None or upgrades.empty:
        return {
            "headline": "Keine aktuellen Upgrade/Downgrade-Daten gefunden.",
            "items": [],
        }

    cutoff = pd.Timestamp.now(tz="UTC").tz_localize(None) - pd.Timedelta(days=DEFAULT_ANALYST_LOOKBACK_DAYS)
    frame = upgrades.copy()
    frame.index = pd.to_datetime(frame.index, errors="coerce")
    frame = frame[frame.index.notna()]
    recent = frame[frame.index >= cutoff].sort_index(ascending=False).head(5)

    if recent.empty:
        return {
            "headline": f"Keine Upgrade/Downgrade-Aenderungen in den letzten {DEFAULT_ANALYST_LOOKBACK_DAYS} Tagen.",
            "items": [],
        }

    items = []
    for date_value, row in recent.iterrows():
        recommendation_type = _format_analyst_action(_get_row_value(row, "action"))
        items.append(
            " | ".join(
                [
                    date_value.strftime("%Y-%m-%d"),
                    recommendation_type,
                    str(_get_row_value(row, "firm") or "Unbekannte Firma"),
                    f"{_get_row_value(row, 'fromGrade') or 'n/a'} -> {_get_row_value(row, 'toGrade') or 'n/a'}",
                ]
            )
        )

    return {
        "headline": f"{len(items)} aktuelle Analysten-Aenderungen gefunden.",
        "items": items,
    }


def _extract_next_dates(ticker: yf.Ticker, info: dict[str, Any], is_etf: bool) -> list[str]:
    dates: list[str] = []
    today = datetime.utcnow().date()

    earnings_dates = _safe_dataframe(lambda: ticker.get_earnings_dates(limit=3))
    if earnings_dates is not None and not earnings_dates.empty:
        earnings_dates.index = pd.to_datetime(earnings_dates.index, errors="coerce")
        for dt_value in earnings_dates.index[:3]:
            if pd.notna(dt_value) and dt_value.date() >= today:
                dates.append(f"Earnings: {dt_value.strftime('%Y-%m-%d')}")

    calendar = _safe_get(lambda: ticker.get_calendar(), {})
    if isinstance(calendar, dict):
        for label, raw_value in calendar.items():
            if not _is_relevant_calendar_label(str(label)):
                continue
            formatted = _format_date_value(raw_value)
            parsed_date = _extract_first_date(formatted or "") if formatted else None
            if formatted and parsed_date is not None and parsed_date.date() >= today:
                dates.append(f"{label}: {formatted}")

    for label, field_name in (("Ex-Dividende", "exDividendDate"), ("Dividende", "dividendDate")):
        formatted = _format_date_value(info.get(field_name))
        parsed_date = _extract_first_date(formatted or "") if formatted else None
        if formatted and parsed_date is not None and parsed_date.date() >= today:
            dates.append(f"{label}: {formatted}")

    if is_etf and not dates:
        dates.append("Keine naechsten ETF-Termine verfugbar.")

    return _dedupe_preserve_order(dates)[:6]


def _summarize_news(ticker: yf.Ticker) -> list[dict[str, str]]:
    news_items = _safe_get(lambda: ticker.get_news(count=DEFAULT_NEWS_ITEMS), [])
    summaries: list[dict[str, str]] = []

    if not isinstance(news_items, list):
        return summaries

    for item in news_items[:DEFAULT_NEWS_ITEMS]:
        if not isinstance(item, dict):
            continue

        title = item.get("title") or item.get("content", {}).get("title")
        publisher = item.get("publisher") or item.get("content", {}).get("provider", {}).get("displayName")
        published_at = item.get("providerPublishTime") or item.get("content", {}).get("pubDate")
        date_text = _format_date_value(published_at)
        url = (
            item.get("canonicalUrl", {}).get("url")
            or item.get("clickThroughUrl", {}).get("url")
            or item.get("content", {}).get("canonicalUrl", {}).get("url")
            or item.get("content", {}).get("clickThroughUrl", {}).get("url")
        )

        if title and url:
            summaries.append(
                {
                    "title": str(title),
                    "publisher": str(publisher or ""),
                    "date": str(date_text or ""),
                    "url": str(url),
                }
            )

    return summaries


def _summarize_eps_revisions(ticker: yf.Ticker) -> dict[str, Any]:
    revisions = _safe_dataframe(lambda: ticker.get_eps_revisions())
    if revisions is None or revisions.empty:
        return {"name": "EPS-Revisionen", "score": 0, "summary": "Keine EPS-Revisionen verfuegbar."}

    total_up = 0
    total_down = 0
    for column in revisions.columns:
        normalized = str(column).lower()
        numeric = pd.to_numeric(revisions[column], errors="coerce").fillna(0)
        if "up" in normalized:
            total_up += int(numeric.sum())
        elif "down" in normalized:
            total_down += int(numeric.sum())

    net_revisions = total_up - total_down
    score = 0
    if net_revisions > 0:
        score = min(15, 6 + net_revisions * 3)
    elif net_revisions < 0:
        score = max(-5, net_revisions)

    summary = f"EPS-Revisionen: {total_up} hoch, {total_down} runter"
    if net_revisions > 0:
        summary += " - positive Revisionstendenz"
    elif net_revisions < 0:
        summary += " - gemischte bis negative Tendenz"

    return {"name": "EPS-Revisionen", "score": score, "summary": summary}


def _summarize_price_targets(ticker: yf.Ticker, info: dict[str, Any], history: pd.DataFrame | None) -> dict[str, Any]:
    import finnhub_cache
    symbol = ticker.ticker
    fh_targets, fh_recoms = finnhub_cache.get_analyst_data(symbol)

    current_price = _get_current_price(info, history)
    target_mean = None
    target_high = None
    target_low = None

    # Try Finnhub first for targets
    if fh_targets and "targetMean" in fh_targets and fh_targets["targetMean"]:
        target_mean = _safe_float(fh_targets.get("targetMean"))
        target_high = _safe_float(fh_targets.get("targetHigh"))
        target_low = _safe_float(fh_targets.get("targetLow"))
        
    # Fallback to yfinance for targets
    if target_mean is None:
        targets = _safe_get(lambda: ticker.get_analyst_price_targets(), {})
        if isinstance(targets, dict):
            target_mean = _safe_float(targets.get("mean"))
            target_high = _safe_float(targets.get("high"))
            target_low = _safe_float(targets.get("low"))

    if current_price is None or target_mean is None or current_price <= 0:
        return {"name": "Kursziele & Konsens", "score": 0, "summary": "Kursziel-Daten vorhanden, aber nicht sauber vergleichbar."}

    target_gap_percent = ((target_mean - current_price) / current_price) * 100
    score = 0
    if target_gap_percent >= 20:
        score += 10
    elif target_gap_percent >= 10:
        score += 5
    elif target_gap_percent > 0:
        score += 2

    analyst_count = 0
    buy_ratio = 0.0

    # Try Finnhub first for recommendations
    if fh_recoms and isinstance(fh_recoms, list) and len(fh_recoms) > 0:
        latest = fh_recoms[0]
        strong_buy = _safe_float(latest.get("strongBuy", 0)) or 0
        buy = _safe_float(latest.get("buy", 0)) or 0
        hold = _safe_float(latest.get("hold", 0)) or 0
        sell = _safe_float(latest.get("sell", 0)) or 0
        strong_sell = _safe_float(latest.get("strongSell", 0)) or 0

        analyst_count = strong_buy + buy + hold + sell + strong_sell
        if analyst_count > 0:
            buy_ratio = (strong_buy + buy) / analyst_count
    else:
        # Fallback to yfinance for recommendations
        recom_summary = _safe_dataframe(lambda: ticker.get_recommendations_summary())
        if recom_summary is not None and not recom_summary.empty:
            latest = recom_summary.iloc[0]
            strong_buy = _safe_float(latest.get("strongBuy", 0)) or 0
            buy = _safe_float(latest.get("buy", 0)) or 0
            hold = _safe_float(latest.get("hold", 0)) or 0
            sell = _safe_float(latest.get("sell", 0)) or 0
            strong_sell = _safe_float(latest.get("strongSell", 0)) or 0

            analyst_count = strong_buy + buy + hold + sell + strong_sell
            if analyst_count > 0:
                buy_ratio = (strong_buy + buy) / analyst_count

    if analyst_count >= 5:
        if buy_ratio >= 0.8:
            score += 5
        elif buy_ratio >= 0.6:
            score += 3

    range_text = ""
    if target_low is not None and target_high is not None:
        range_text = f" (Spanne {target_low:.2f} bis {target_high:.2f})"

    provider = "Finnhub" if (fh_targets and "targetMean" in fh_targets) else "YFinance"
    summary = f"[{provider}] Mittel {target_mean:.2f} vs. Kurs {current_price:.2f} = {target_gap_percent:.1f}% Potenzial{range_text}"
    if analyst_count > 0:
        summary += f" | Konsens: {buy_ratio*100:.0f}% Buys ({int(analyst_count)} Analysten)"

    return {"name": "Kursziele & Konsens", "score": score, "summary": summary}


def _summarize_price_volume(history: pd.DataFrame | None) -> dict[str, Any]:
    if history is None or history.empty or len(history) < 25:
        return {"name": "Preis/Volumen", "score": 0, "summary": "Nicht genug Kursdaten fuer Preis/Volumen-Signal."}

    frame = history.copy().sort_index()
    close_series = pd.to_numeric(frame.get("Close"), errors="coerce")
    volume_series = pd.to_numeric(frame.get("Volume"), errors="coerce")
    if close_series is None or volume_series is None:
        return {"name": "Preis/Volumen", "score": 0, "summary": "Preis/Volumen-Daten nicht lesbar."}

    latest_close = float(close_series.iloc[-1])
    latest_volume = float(volume_series.iloc[-1])
    ma20 = float(close_series.tail(20).mean())
    ma50 = float(close_series.tail(50).mean()) if len(close_series) >= 50 else ma20
    avg_volume_20 = float(volume_series.tail(20).mean())
    volume_ratio = latest_volume / avg_volume_20 if avg_volume_20 > 0 else 0
    return_5d = ((latest_close / float(close_series.iloc[-6])) - 1) * 100 if len(close_series) >= 6 else 0
    
    # Check if the latest day is an up day
    prev_close = float(close_series.iloc[-2]) if len(close_series) >= 2 else latest_close
    is_up_day = latest_close >= prev_close

    base_score = 0
    if latest_close > ma20:
        base_score += 5
    if latest_close > ma50:
        base_score += 6
    if return_5d >= 7:
        base_score += 4
    elif return_5d <= -7:
        base_score -= 3

    vol_score = 0
    if is_up_day and latest_volume > (avg_volume_20 * 1.5):
        vol_score = 3

    total_score = max(-10, min(10, base_score + vol_score))

    summary = (
        f"Kurs {latest_close:.2f}, 5T {return_5d:.1f}%, Volumen {volume_ratio:.1f}x vs. 20T, "
        f"ueber MA20/MA50: {'ja' if latest_close > ma20 else 'nein'}/{'ja' if latest_close > ma50 else 'nein'}"
    )
    return {"name": "Preis/Volumen", "score": total_score, "summary": summary}


def _summarize_news_intensity(ticker: yf.Ticker) -> dict[str, Any]:
    news_items = _safe_get(lambda: ticker.get_news(count=10), [])
    if not isinstance(news_items, list) or not news_items:
        return {"name": "News-Sentiment", "score": 0, "summary": "Keine aktuelle News-Dichte erkennbar."}

    cutoff = datetime.utcnow().date() - pd.Timedelta(days=DEFAULT_SIGNAL_NEWS_WINDOW_DAYS)
    recent_headlines: list[str] = []
    for item in news_items:
        published_at = item.get("providerPublishTime") or item.get("content", {}).get("pubDate")
        date_text = _format_date_value(published_at)
        if not date_text:
            continue
        parsed = _extract_first_date(date_text)
        if parsed and parsed.date() >= cutoff:
            title = item.get("title") or item.get("content", {}).get("title", "")
            if title:
                recent_headlines.append(title)

    recent_count = len(recent_headlines)

    # Density sub-score (0–7)
    density_score = 0
    if recent_count >= 6:
        density_score = 7
    elif recent_count >= 4:
        density_score = 5
    elif recent_count >= 2:
        density_score = 3

    # Sentiment sub-score via Gemini (-8 to +8)
    sentiment_result = _analyze_news_sentiment(recent_headlines)
    sentiment_score = sentiment_result["score"]
    sentiment_label = sentiment_result["label"]

    total_score = max(-10, min(15, density_score + sentiment_score))

    summary = f"{recent_count} News in {DEFAULT_SIGNAL_NEWS_WINDOW_DAYS}T"
    if sentiment_label:
        summary += f" | Sentiment: {sentiment_label} ({sentiment_score:+d})"

    return {"name": "News-Sentiment", "score": total_score, "summary": summary}


def _analyze_news_sentiment(headlines: list[str]) -> dict[str, Any]:
    """Use Gemini to classify a batch of headlines as bullish/neutral/bearish.
    Returns a score between -8 and +8 and a human-readable label.
    Falls back to keyword-based analysis if Gemini is unavailable."""
    if not headlines:
        return {"score": 0, "label": ""}

    # Try Gemini first
    if _GEMINI_AVAILABLE:
        try:
            return _analyze_sentiment_gemini(headlines)
        except Exception:
            pass

    # Fallback: keyword-based
    return _analyze_sentiment_keywords(headlines)


def _analyze_sentiment_gemini(headlines: list[str]) -> dict[str, Any]:
    """Call Gemini Flash to analyze sentiment of news headlines."""
    import os
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        raise RuntimeError("No Gemini API key configured")

    client = genai.Client(api_key=api_key)

    numbered = "\n".join(f"{i+1}. {h}" for i, h in enumerate(headlines[:10]))
    prompt = (
        "Analyze the sentiment of these stock news headlines. "
        "For each headline, respond with exactly one word: BULLISH, NEUTRAL, or BEARISH.\n"
        "Respond ONLY with the numbered results, one per line, like:\n"
        "1. BULLISH\n2. NEUTRAL\n"
        f"\nHeadlines:\n{numbered}"
    )

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
    )

    text = response.text.upper()
    bullish = text.count("BULLISH")
    bearish = text.count("BEARISH")
    total = bullish + bearish + text.count("NEUTRAL")

    if total == 0:
        return {"score": 0, "label": "unklar"}

    net = bullish - bearish
    # Scale: each net bullish headline = +2, capped at ±8
    score = max(-8, min(8, net * 2))

    if net >= 2:
        label = f"positiv ({bullish}↑ {bearish}↓)"
    elif net <= -2:
        label = f"negativ ({bullish}↑ {bearish}↓)"
    else:
        label = f"neutral ({bullish}↑ {bearish}↓)"

    return {"score": score, "label": label}


def _analyze_sentiment_keywords(headlines: list[str]) -> dict[str, Any]:
    """Fallback keyword-based sentiment analysis when Gemini is not available."""
    BULLISH_KEYWORDS = (
        "beat", "beats", "upgrade", "upgraded", "raises", "raised", "outperform",
        "growth", "surge", "surges", "soars", "jumps", "rally", "record",
        "positive", "profit", "buy", "bullish", "strong", "higher",
    )
    BEARISH_KEYWORDS = (
        "miss", "misses", "downgrade", "downgraded", "cuts", "cut", "sell",
        "lawsuit", "investigation", "fraud", "crash", "plunge", "plunges",
        "decline", "loss", "losses", "warns", "warning", "bearish", "lower",
        "recall", "layoff", "layoffs", "bankruptcy",
    )

    bullish = 0
    bearish = 0
    for headline in headlines:
        lower = headline.lower()
        words = set(re.findall(r'\b\w+\b', lower))
        if words & set(BULLISH_KEYWORDS):
            bullish += 1
        if words & set(BEARISH_KEYWORDS):
            bearish += 1

    net = bullish - bearish
    score = max(-8, min(8, net * 2))

    if net >= 2:
        label = f"positiv ({bullish}↑ {bearish}↓)"
    elif net <= -2:
        label = f"negativ ({bullish}↑ {bearish}↓)"
    else:
        label = f"neutral ({bullish}↑ {bearish}↓)"

    return {"score": score, "label": label}


def _summarize_event_pressure(ticker: yf.Ticker, info: dict[str, Any]) -> dict[str, Any]:
    next_dates = _extract_next_dates(ticker, info, False)
    if not next_dates:
        return {"name": "Event-Druck", "score": 0, "summary": "Keine nahen Termine erkannt."}

    upcoming_days: list[int] = []
    for entry in next_dates:
        parsed = _extract_first_date(entry)
        if parsed is None:
            continue
        delta_days = (parsed.date() - datetime.utcnow().date()).days
        if delta_days >= 0:
            upcoming_days.append(delta_days)

    if not upcoming_days:
        return {"name": "Event-Druck", "score": 0, "summary": "Keine nahen Termine erkannt."}

    nearest = min(upcoming_days)
    score = 0
    if nearest <= 7:
        score = 5
    elif nearest <= 14:
        score = 3
    elif nearest <= 30:
        score = 1

    summary = f"Naechster Termin in {nearest} Tagen"
    return {"name": "Event-Druck", "score": score, "summary": summary}


def _summarize_insider_signal(ticker: yf.Ticker, is_etf: bool) -> dict[str, Any]:
    """Score insider buying activity. Nutzt Finnhub Insider Sentiment als primäre Quelle, 
    Fallback auf yfinance falls nicht verfügbar."""
    if is_etf:
        return {"name": "Insider-Aktivitaet", "score": 0, "summary": "Nicht relevant fuer ETFs."}

    import finnhub_cache
    symbol = ticker.ticker
    fh_insider = finnhub_cache.get_insider_sentiment(symbol)
    
    purchase_count = 0
    sell_count = 0
    provider = "YF"

    # Try Finnhub First
    if fh_insider and isinstance(fh_insider, list) and len(fh_insider) > 0:
        provider = "Finnhub"
        # Sum up changes (positive = buying, negative = selling) from the recent sentiment data
        for item in fh_insider[-3:]: # Look at up to last 3 months
            change = _safe_float(item.get("change")) or 0
            if change > 0:
                purchase_count += change
            elif change < 0:
                sell_count += abs(change)
        
        # Scale down large counts for our scoring model
        if purchase_count > 100:
            purchase_count = 4
        elif purchase_count > 0:
            purchase_count = 2
            
        if sell_count > 100:
            sell_count = 4
        elif sell_count > 0:
            sell_count = 1
    else:
        # Fallback to yfinance
        transactions = _safe_dataframe(lambda: ticker.get_insider_transactions())
        if transactions is not None and not transactions.empty:
            columns = {str(col).lower(): col for col in transactions.columns}
            text_col = columns.get("text") or columns.get("transaction")
            if text_col:
                for _, row in transactions.head(20).iterrows():
                    text_val = str(row.get(text_col, "")).lower()
                    if any(kw in text_val for kw in ("purchase", "buy", "kauf")):
                        purchase_count += 1
                    elif any(kw in text_val for kw in ("sale", "sell", "verkauf", "disposition")):
                        sell_count += 1

    score = 0
    if purchase_count >= 4:
        score = 10
    elif purchase_count >= 2:
        score = 6
    elif purchase_count >= 1:
        score = 4

    if sell_count > purchase_count * 2:
        score = max(0, score - 3)

    if purchase_count == 0 and sell_count == 0:
        summary = f"[{provider}] Keine Insider-Transaktionen erkannt."
    else:
        summary = f"[{provider}] {int(purchase_count)} Kaeufe, {int(sell_count)} Verkaeufe"
        if purchase_count >= 4:
            summary += " - starkes Insider-Kaufsignal"
        elif purchase_count >= 2:
            summary += " - mehrfache Insiderkaeufe"

    return {"name": "Insider-Aktivitaet", "score": score, "summary": summary}


def _summarize_short_interest(info: dict[str, Any], history: pd.DataFrame | None = None) -> dict[str, Any]:
    """Score based on short interest with dual interpretation.
    High short + price above MA50 = squeeze potential (bullish).
    High short + price below MA50 = confirmed bearish pressure."""
    short_pct = _safe_float(info.get("shortPercentOfFloat"))
    short_ratio = _safe_float(info.get("shortRatio"))

    # Determine price vs MA50 for dual interpretation
    above_ma50 = True  # default: assume bullish if no history
    if history is not None and not history.empty and len(history) >= 50:
        close_series = pd.to_numeric(history.get("Close"), errors="coerce")
        if close_series is not None and not close_series.isna().all():
            latest_close = float(close_series.iloc[-1])
            ma50 = float(close_series.tail(50).mean())
            above_ma50 = latest_close > ma50



    if short_pct is None and short_ratio is None:
        return {"name": "Short Interest", "score": 0, "summary": "Keine Short-Interest-Daten verfuegbar."}

    score = 0
    parts = []

    if short_pct is not None:
        short_pct_display = short_pct * 100 if short_pct < 1 else short_pct
        parts.append(f"Short-Float: {short_pct_display:.1f}%")
        if above_ma50:
            if short_pct_display >= 20:
                score = 5
            elif short_pct_display >= 10:
                score = 3
            elif short_pct_display >= 5:
                score = 1
        else:
            # Bearish: confirmed selling pressure
            score = 0

    if short_ratio is not None:
        parts.append(f"Short-Ratio: {short_ratio:.1f} Tage")
        if above_ma50:
            if short_ratio >= 5 and score < 5:
                score = max(score, 4)
            elif short_ratio >= 3 and score < 3:
                score = max(score, 2)

    summary = ", ".join(parts) if parts else "Keine Short-Interest-Daten verfuegbar."
    if not above_ma50 and short_pct is not None:
        short_pct_display = short_pct * 100 if short_pct < 1 else short_pct
        if short_pct_display >= 10:
            summary += " - Kurs unter MA50, baerischer Druck"
        else:
            summary += " - moderate Leerverkaufsaktivitaet"
    elif score >= 4:
        summary += " - erhoehtes Squeeze-Potenzial (bullisch)."
    elif score > 0:
        summary += " - erhoehtes Squeeze-Potenzial (bullisch)."
    elif not above_ma50:
        score = 0
        summary += " - unter MA50 (baerisch)."

    return {"name": "Short Interest", "score": score, "summary": summary}


def _summarize_fundamentals(ticker: yf.Ticker, info: dict[str, Any]) -> dict[str, Any]:
    """Berechnet einen Score basierend auf P/E, PEG, Debt/Equity, FCF Yield und Gewinnmarge."""
    import alpha_vantage_cache
    score = 0
    components = []
    
    symbol = ticker.ticker
    av_data = alpha_vantage_cache.get_fundamentals(symbol)
    
    # Try Alpha Vantage first, fallback to yfinance info
    if av_data and av_data.get("PERatio") and av_data.get("PERatio") != "None":
        forward_pe = _safe_float(av_data.get("PERatio"))
        peg_ratio = _safe_float(av_data.get("PEGRatio"))
        profit_margin = _safe_float(av_data.get("ProfitMargin"))
        
        # AV doesn't provide debtToEquity and freeCashflow directly in OVERVIEW in a simple usable way
        # so we merge from yfinance if available
        debt_equity = _safe_float(info.get("debtToEquity"))
        fcf = _safe_float(info.get("freeCashflow"))
        mcap = _safe_float(av_data.get("MarketCapitalization")) or _safe_float(info.get("marketCap"))
        provider = "AV"
    else:
        forward_pe = _safe_float(info.get("forwardPE"))
        peg_ratio = _safe_float(info.get("pegRatio"))
        debt_equity = _safe_float(info.get("debtToEquity"))
        fcf = _safe_float(info.get("freeCashflow"))
        mcap = _safe_float(info.get("marketCap"))
        profit_margin = _safe_float(info.get("profitMargins"))
        provider = "YF"

    if forward_pe is not None and forward_pe > 0:
        if forward_pe < 15:
            score += 2
            components.append(f"P/E {forward_pe:.1f}")
        elif forward_pe < 25:
            score += 1
            components.append(f"P/E {forward_pe:.1f}")
        elif forward_pe > 50:
            score -= 2
            components.append(f"P/E {forward_pe:.1f} (hoch)")

    if peg_ratio is not None and peg_ratio > 0:
        if peg_ratio < 1.0:
            score += 2
            components.append(f"PEG {peg_ratio:.2f}")
        elif peg_ratio < 1.5:
            score += 1
            components.append(f"PEG {peg_ratio:.2f}")

    if debt_equity is not None:
        if debt_equity < 50:
            score += 2
            components.append(f"D/E {debt_equity:.1f}")
        elif debt_equity < 100:
            score += 1

    if fcf is not None and mcap is not None and mcap > 0:
        fcf_yield = (fcf / mcap) * 100
        if fcf_yield > 5:
            score += 2
            components.append(f"FCF-Rendite {fcf_yield:.1f}%")
        elif fcf_yield > 2:
            score += 1

    if profit_margin is not None:
        if profit_margin > 0.20:
            score += 2
            components.append(f"Marge {profit_margin*100:.1f}%")
        elif profit_margin > 0.10:
            score += 1
            components.append(f"Marge {profit_margin*100:.1f}%")

    score = max(-2, min(10, score))
    summary = f"[{provider}] Stark: " + ", ".join(components) if components else f"[{provider}] Fundamentaldaten unauffaellig."

    return {"name": "Fundamentale Bewertung", "score": score, "summary": summary}


# Regional benchmark mapping for relative strength comparison
REGIONAL_BENCHMARKS: dict[str, str] = {
    ".DE": "^GDAXI",    # DAX (Germany)
    ".F": "^GDAXI",     # Frankfurt
    ".MU": "^GDAXI",    # Munich
    ".DU": "^GDAXI",    # Duesseldorf
    ".VI": "^GDAXI",    # Vienna (close to DAX)
    ".SW": "^SSMI",     # Swiss SMI
    ".T": "^N225",      # Tokyo / Nikkei
    ".SA": "^BVSP",     # Bovespa (Brazil)
    ".TO": "^GSPTSE",   # TSX (Canada)
    ".NS": "^NSEI",     # Nifty 50 (India)
    ".BO": "^NSEI",     # Bombay
    ".L": "^FTSE",      # FTSE 100 (UK)
    ".PA": "^FCHI",     # CAC 40 (France)
    ".AS": "^AEX",      # AEX (Netherlands)
    ".MI": "^FTSEMIB.MI",  # FTSE MIB (Italy)
}


def _get_benchmark_symbol(stock_symbol: str) -> str:
    """Return the appropriate regional benchmark for a given stock symbol."""
    for suffix, benchmark in REGIONAL_BENCHMARKS.items():
        if stock_symbol.upper().endswith(suffix.upper()):
            return benchmark
    return "SPY"  # Default: S&P 500 for US and unknown


def _summarize_relative_strength(history: pd.DataFrame | None, symbol: str = "") -> dict[str, Any]:
    """Compare stock performance vs. regional benchmark over last month."""
    if history is None or history.empty or len(history) < 20:
        return {"name": "Relative Staerke", "score": 0, "summary": "Nicht genug Kursdaten fuer Relative-Staerke-Berechnung."}

    close_series = pd.to_numeric(history.get("Close"), errors="coerce")
    if close_series is None or close_series.isna().all():
        return {"name": "Relative Staerke", "score": 0, "summary": "Kursdaten nicht lesbar."}

    stock_return_1m = ((float(close_series.iloc[-1]) / float(close_series.iloc[-20])) - 1) * 100

    benchmark_symbol = _get_benchmark_symbol(symbol)
    bench_history = _safe_dataframe(lambda: yf.Ticker(benchmark_symbol).history(period="1mo", auto_adjust=False))
    if bench_history is not None and not bench_history.empty and len(bench_history) >= 10:
        bench_close = pd.to_numeric(bench_history.get("Close"), errors="coerce")
        if bench_close is not None and not bench_close.isna().all():
            benchmark_return = ((float(bench_close.iloc[-1]) / float(bench_close.iloc[0])) - 1) * 100
        else:
            benchmark_return = 0.0
    else:
        benchmark_return = 0.0

    relative_perf = stock_return_1m - benchmark_return

    score = 0
    if relative_perf >= 10:
        score = 5
    elif relative_perf >= 5:
        score = 3
    elif relative_perf >= 2:
        score = 1

    summary = f"1M-Perf: {stock_return_1m:.1f}% vs. {benchmark_symbol} {benchmark_return:.1f}% = {relative_perf:+.1f}% relativ"
    if relative_perf >= 10:
        summary += " - starke Outperformance"
    elif relative_perf >= 5:
        summary += " - solide Outperformance"

    return {"name": "Relative Staerke", "score": score, "summary": summary}


def add_watchlist_peer_context(signal_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sector_groups: dict[str, list[dict[str, Any]]] = {}
    for item in signal_items:
        sector = str(item.get("sector") or "Unbekannt")
        sector_groups.setdefault(sector, []).append(item)

    enriched: list[dict[str, Any]] = []
    for item in signal_items:
        sector = str(item.get("sector") or "Unbekannt")
        peers = sector_groups.get(sector, [])
        peer_scores = [int(peer.get("brodel_score", 0)) for peer in peers if peer.get("symbol") != item.get("symbol")]
        sector_average = round(sum(int(peer.get("brodel_score", 0)) for peer in peers) / len(peers), 1) if peers else 0
        rank = 1 + sum(1 for peer in peers if int(peer.get("brodel_score", 0)) > int(item.get("brodel_score", 0)))

        top_peer = None
        if peer_scores:
            sorted_peers = sorted(
                (peer for peer in peers if peer.get("symbol") != item.get("symbol")),
                key=lambda peer: int(peer.get("brodel_score", 0)),
                reverse=True,
            )
            if sorted_peers:
                top_peer = {
                    "symbol": sorted_peers[0].get("symbol"),
                    "name": sorted_peers[0].get("name"),
                    "score": int(sorted_peers[0].get("brodel_score", 0)),
                }

        peer_context = {
            "sector": sector,
            "industry": item.get("industry") or "Unbekannt",
            "sector_average": sector_average,
            "score_vs_sector": round(int(item.get("brodel_score", 0)) - sector_average, 1),
            "sector_rank": rank,
            "sector_count": len(peers),
            "top_peer": top_peer,
        }

        enriched_item = dict(item)
        enriched_item["peer_context"] = peer_context
        enriched.append(enriched_item)

    return enriched


def _format_analyst_action(action: Any) -> str:
    normalized = str(action or "").strip().lower()
    action_map = {
        "up": "Hochstufung",
        "down": "Herabstufung",
        "main": "Bestaetigung",
        "init": "Neueinstufung",
        "reit": "Neueinstufung",
    }
    return action_map.get(normalized, "Aenderung")


def _get_row_value(row: Any, key: str) -> Any:
    for candidate in (key, key.lower(), key.upper(), key.capitalize()):
        if candidate in row:
            return row.get(candidate)
    return None


def _get_current_price(info: dict[str, Any], history: pd.DataFrame | None) -> float | None:
    for key in ("currentPrice", "regularMarketPrice", "previousClose"):
        value = _safe_float(info.get(key))
        if value is not None and value > 0:
            return value

    if history is not None and not history.empty and "Close" in history.columns:
        close_value = _safe_float(history["Close"].iloc[-1])
        if close_value is not None and close_value > 0:
            return close_value

    return None


def _safe_float(value: Any) -> float | None:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(converted):
        return None
    return converted


def _is_relevant_calendar_label(label: str) -> bool:
    normalized = label.strip().lower()
    relevant_terms = ("earnings", "dividend", "ex-dividend", "split", "event")
    return any(term in normalized for term in relevant_terms)


def _safe_get(loader: Any, fallback: Any) -> Any:
    try:
        value = loader()
        return fallback if value is None else value
    except Exception:
        return fallback


def _safe_dataframe(loader: Any) -> pd.DataFrame | None:
    value = _safe_get(loader, None)
    if isinstance(value, pd.DataFrame):
        return value
    return None


def _format_date_value(value: Any) -> str | None:
    if value is None or value == "":
        return None

    if hasattr(value, "iloc") and not isinstance(value, str):
        if len(value) > 0:
            return _format_date_value(value.iloc[0])
        return None

    if hasattr(value, "tolist") and not isinstance(value, str):
        try:
            value = value.tolist()
        except Exception:
            pass

    if isinstance(value, (list, tuple)) and value:
        return _format_date_value(value[0])

    if isinstance(value, pd.Timestamp):
        return value.tz_localize(None).strftime("%Y-%m-%d") if value.tzinfo else value.strftime("%Y-%m-%d")

    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")

    if isinstance(value, (int, float)):
        try:
            return datetime.utcfromtimestamp(value).strftime("%Y-%m-%d")
        except (OSError, OverflowError, ValueError):
            return str(value)

    parsed = pd.to_datetime(value, errors="coerce")
    
    # NEW: Ensure parsed is a scalar before calling pd.notna
    if hasattr(parsed, "__iter__") and not isinstance(parsed, str):
        if len(parsed) > 0:
            parsed = parsed[0]
        else:
            parsed = pd.NaT

    if pd.notna(parsed):
        parsed_ts = pd.Timestamp(parsed)
        return parsed_ts.strftime("%Y-%m-%d")

    text = str(value).strip()
    return text or None


def _clean_scalar(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result