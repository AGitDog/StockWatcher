"""Weekly system check (Sundays): every external connection, last week's runs and the app.

    python system_check.py                  # all checks, markdown report on stdout
    python system_check.py --report out.md  # also write the report to a file (issue body)

Live probes call each source once and read the answer with the same code as the nightly run.
They check the format, not the values. Every probe gets a second try after a short pause, so a
single network hiccup does not raise an alarm. A failed hard check makes the run fail (exit 1),
GitHub then sends a mail and the workflow opens an issue with this report. Soft checks only warn.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import requests

import insider_check
import insider_sources as sources

APP_URL = "https://stockwatcher-nvggpetjbfuyd6wkgniquu.streamlit.app/"
SNAPSHOT_DIR = Path("signal_history") / "meine_watchlist"
STATE_FILE = Path("bot_depot") / "state.json"
RETRY_PAUSE_SECONDS = 20
MIN_FRESH_SHARE = 0.90
MIN_GOOD_DAYS = 4  # of 5 weekdays: one holiday or skipped GitHub run is tolerated
REGION_SYMBOLS = ["AAPL", "SAP.DE", "HSBA.L", "7203.T", "RELIANCE.NS", "RY.TO", "NESN.SW"]
PIPELINE_SYMBOLS = ["AAPL", "SAP.DE", "7203.T"]
V3_BLOCKS = {
    "Qualität": ("operating_margin", "return_on_assets", "fcf_to_debt"),
    "Bewertung": ("forward_pe", "fcf_yield"),
    "Momentum": ("momentum_12_1",),
    "EPS-Revisionen": ("eps_up_ratio",),
    "Rückkauf": ("share_change",),
}
# Nominal index sizes; fewer than 80 % means the table moved or the parser broke.
INDEX_SIZES = {
    "DAX": 40, "S&P 500": 500, "Dow Jones": 30, "Nasdaq-100": 100, "MDAX": 50, "CAC 40": 40,
    "EURO STOXX 50": 50, "FTSE 100": 100, "SMI": 20, "Nifty 50": 50, "S&P/TSX 60": 60, "TecDAX": 30,
    "Nikkei 225": 225, "PHLX Semiconductor Sector": 30, "NASDAQ Biotechnology Index": 200,
}
# one text per page of app.PAGES (Start, Marktbeobachtung, Trades, Forschung, Hilfe)
PAGE_MARKERS = ["Willkommen bei StockWatcher", "Marktbeobachtung", "Spieldepots", "Wahrheitsmaschine", "Hilfe & Methodik"]
SIZE_LIMITS_MB = {"signal_history": 300, "insider_data": 20, "bot_depot": 5}


@dataclass
class Check:
    area: str
    name: str
    ok: bool
    detail: str
    hard: bool = True


def run_probe(area: str, name: str, probe: Callable[[], tuple[bool, str]], hard: bool = True,
              retries: int = 1, pause: float = RETRY_PAUSE_SECONDS, sleep: Callable[[float], None] = time.sleep) -> Check:
    """Run a probe; a crash counts as a failure, a failure gets ``retries`` more tries."""
    ok, detail = False, ""
    for attempt in range(retries + 1):
        try:
            ok, detail = probe()
        except Exception as exc:  # a changed format often shows up as an exception
            ok, detail = False, f"{type(exc).__name__}: {str(exc)[:200]}"
        if ok:
            break
        if attempt < retries:
            sleep(pause)
    return Check(area, name, bool(ok), detail, hard)


# ── Yahoo Finance ───────────────────────────────────────────────────────────

def probe_yahoo_prices() -> tuple[bool, str]:
    from factor_lab.data import download_close_prices

    start = (date.today() - timedelta(days=21)).isoformat()
    with tempfile.TemporaryDirectory() as tmp:
        close = download_close_prices(REGION_SYMBOLS, start=start, cache_dir=Path(tmp), use_cache=False)
    counts = {symbol: int(close[symbol].notna().sum()) if symbol in close else 0 for symbol in REGION_SYMBOLS}
    missing = [symbol for symbol, count in counts.items() if count < 5]
    detail = ", ".join(f"{symbol} {count}" for symbol, count in counts.items())
    return not missing, f"Schlusskurse in 3 Wochen: {detail}" + (f" · zu wenig: {', '.join(missing)}" if missing else "")


def probe_yahoo_bars() -> tuple[bool, str]:
    import paper_bot

    bars = paper_bot.download_bars(["AAPL", "SAP.DE"], date.today() - timedelta(days=14))
    needed = {"Open", "Low", "Close"}
    bad = [symbol for symbol in ("AAPL", "SAP.DE")
           if symbol not in bars or bars[symbol] is None or bars[symbol].empty or not needed <= set(bars[symbol].columns)]
    return not bad, "Tageskerzen für den Paper-Bot" + (f" fehlen: {', '.join(bad)}" if bad else " vollständig")


def probe_yahoo_info() -> tuple[bool, str]:
    import yfinance as yf

    needed = ["currency", "longName", "sector", "country", "marketCap", "forwardPE", "grossMargins", "returnOnEquity"]
    problems = []
    for symbol in ("AAPL", "SAP.DE"):
        info = yf.Ticker(symbol).get_info() or {}
        lacking = [key for key in needed if info.get(key) in (None, "")]
        if lacking:
            problems.append(f"{symbol} ohne {', '.join(lacking)}")
    return not problems, "; ".join(problems) or f"{len(needed)} Felder bei AAPL und SAP.DE"


def probe_yahoo_analysts() -> tuple[bool, str]:
    import yfinance as yf

    ticker = yf.Ticker("AAPL")
    revisions = ticker.get_eps_revisions()
    targets = ticker.get_analyst_price_targets() or {}
    summary = ticker.get_recommendations_summary()
    upgrades = ticker.get_upgrades_downgrades()
    problems = []
    if revisions is None or revisions.empty or not any("up" in str(column).lower() for column in revisions.columns):
        problems.append("EPS-Revisionen ohne up/down-Spalten")
    if not targets.get("mean"):
        problems.append("Kursziel ohne Mittelwert")
    if summary is None or summary.empty or "strongBuy" not in summary.columns:
        problems.append("Empfehlungen ohne strongBuy")
    if upgrades is None or upgrades.empty:
        problems.append("keine Hoch-/Herabstufungen")
    return not problems, "; ".join(problems) or "Revisionen, Kursziele, Empfehlungen, Hoch-/Herabstufungen"


def probe_yahoo_company_data() -> tuple[bool, str]:
    import yfinance as yf

    ticker = yf.Ticker("AAPL")
    news = ticker.get_news(count=5) or []
    titles = [item.get("title") or (item.get("content") or {}).get("title") for item in news if isinstance(item, dict)]
    calendar = ticker.get_calendar() or {}
    earnings = ticker.get_earnings_dates(limit=3)
    shares = ticker.get_shares_full(start=(date.today() - timedelta(days=400)).isoformat())
    income = ticker.income_stmt
    dividends = ticker.dividends
    problems = []
    if not any(titles):
        problems.append("News ohne Titel")
    if not calendar and (earnings is None or earnings.empty):
        problems.append("kein Termin der Quartalszahlen")
    if shares is None or len(shares) < 2:
        problems.append("keine Aktienanzahl-Historie")
    if income is None or income.empty or "Total Revenue" not in income.index:
        problems.append("GuV ohne Total Revenue")
    if dividends is None or dividends.empty:
        problems.append("keine Dividenden")
    return not problems, "; ".join(problems) or "News, Termine, Aktienanzahl, GuV, Dividenden"


def probe_yahoo_insider() -> tuple[bool, str]:
    return insider_check.probe_yahoo()


def probe_yahoo_search() -> tuple[bool, str]:
    import yfinance as yf

    quotes = getattr(yf.Search("SAP SE", max_results=5), "quotes", []) or []
    symbols = [quote.get("symbol") for quote in quotes if isinstance(quote, dict)]
    return any(str(symbol).startswith("SAP") for symbol in symbols), f"Treffer: {', '.join(map(str, symbols[:5])) or 'keine'}"


def probe_fx() -> tuple[bool, str]:
    sources.usd_per_unit.cache_clear()
    ranges = {"EUR": (0.5, 2), "GBP": (0.5, 2.5), "CHF": (0.5, 2), "CAD": (0.4, 1.5), "JPY": (0.002, 0.02), "INR": (0.005, 0.03)}
    rates = {code: sources.usd_per_unit(code) for code in ranges}
    ok = all(rate and low < rate < high for (code, rate), (low, high) in zip(rates.items(), ranges.values()))
    return ok, ", ".join(f"{code} {rate:.4f}" if rate else f"{code} fehlt" for code, rate in rates.items())


# ── Finnhub, Gemini  ──────────────────────────────────────────

def _finnhub(endpoint: str, **params) -> requests.Response:
    import finnhub_cache

    return finnhub_cache._get(f"https://finnhub.io/api/v1/stock/{endpoint}",
                              params={"symbol": "AAPL", "token": finnhub_cache.get_finnhub_key(), **params}, timeout=15)


def probe_finnhub() -> tuple[bool, str]:
    """The three endpoints the nightly run uses."""
    import finnhub_cache

    if not finnhub_cache.get_finnhub_key():
        return False, "FINNHUB_API_KEY fehlt"
    results = {
        "Empfehlungen": _finnhub("recommendation"),
        "Insider-Geschäfte": _finnhub("insider-transactions", **{"from": (date.today() - timedelta(days=90)).isoformat()}),
        "Insider-Stimmung": _finnhub("insider-sentiment", **{"from": "2024-01-01", "to": "2030-01-01"}),
    }
    problems = [f"{name} HTTP {response.status_code}" for name, response in results.items() if response.status_code != 200]
    if not problems:
        recommendation = results["Empfehlungen"].json()
        if not (isinstance(recommendation, list) and recommendation and "strongBuy" in recommendation[0]):
            problems.append("Empfehlungen ohne strongBuy")
        if "data" not in results["Insider-Geschäfte"].json():
            problems.append("Insider-Geschäfte ohne data")
    return not problems, "; ".join(problems) or "Empfehlungen, Insider-Geschäfte, Insider-Stimmung"


def probe_gemini() -> tuple[bool, str]:
    import stock_agent

    if not stock_agent._GEMINI_AVAILABLE:
        return False, "Bibliothek google-genai fehlt"
    result = stock_agent._analyze_sentiment_gemini(["Apple beats earnings expectations and raises its outlook"])
    return result.get("label") != "unklar", f"Antwort: {result.get('label')}"


# ── index lists ─────────────────────────────────────────────────────────────

def probe_indices() -> tuple[bool, str]:
    import stock_agent

    stock_agent.load_index_constituents.cache_clear()
    sizes = {name: len(stock_agent.load_index_constituents(name)) for name in stock_agent.INDEX_DEFINITIONS}
    short = [f"{name} {count}/{INDEX_SIZES.get(name, 10)}" for name, count in sizes.items()
             if count < 0.8 * INDEX_SIZES.get(name, 10)]
    return not short, (f"zu wenige Mitglieder: {', '.join(short)}" if short else f"{len(sizes)} Indizes vollständig")


# ── the whole nightly pipeline for three stocks ─────────────────────────────

def pipeline_problems(item: dict) -> list[str]:
    """Why a freshly computed item would be useless for the scores (empty list = fine)."""
    import snapshot_store

    problems = []
    if not snapshot_store.is_fresh_measurement(item):
        problems.append("keine frischen Kursdaten")
    factors = item.get("factors_v3") or {}
    blocks = [name for name, keys in V3_BLOCKS.items() if any(factors.get(key) is not None for key in keys)]
    if len(blocks) < 4:
        problems.append(f"nur {len(blocks)} Rang-Score-Bausteine ({', '.join(blocks) or 'keine'})")
    if not item.get("signal_breakdown_v2"):
        problems.append("kein Punkte-Score")
    return problems


def probe_pipeline() -> tuple[bool, str]:
    import stock_agent

    problems = []
    for symbol in PIPELINE_SYMBOLS:
        item = stock_agent.build_symbol_signal_monitor(symbol)
        problems += [f"{symbol}: {problem}" for problem in pipeline_problems(item)]
    return not problems, "; ".join(problems) or f"{', '.join(PIPELINE_SYMBOLS)} komplett berechnet"


# ── the app ─────────────────────────────────────────────────────────────────

def probe_app_url(url: str = APP_URL, get: Callable[..., requests.Response] = requests.get) -> tuple[bool, str]:
    """The app is private: Streamlit answers with a redirect to its login. 404 or 5xx means trouble."""
    response = get(url, allow_redirects=False, timeout=30)
    location = response.headers.get("Location", "")
    if response.status_code == 200:
        return True, "App erreichbar"
    if response.status_code in (302, 303) and "streamlit" in location:
        return True, "App erreichbar (Anmeldung bei Streamlit nötig)"
    return False, f"HTTP {response.status_code} {location[:80]}".strip()


def probe_app_pages() -> tuple[bool, str]:
    """Render every page with the data in the repository, as the app would."""
    from streamlit.testing.v1 import AppTest

    import app

    broken = []
    for index, page in enumerate(app.PAGES):
        # page names carry emoji; the index keeps the generated script ASCII (Windows code pages)
        script = f"import app\nimport streamlit as st\nst.session_state['page'] = app.PAGES[{index}]\napp.render_app()\n"
        test = AppTest.from_string(script)
        test.run(timeout=120)
        if test.exception:
            broken.append(f"{page}: {str(test.exception[0].message)[:120]}")
            continue
        text = " ".join(str(element.value) for element in list(test.markdown) + list(test.subheader))
        if PAGE_MARKERS[index] not in text:
            broken.append(f"{page}: Seite nicht gezeigt (kein „{PAGE_MARKERS[index]}“)")
    return not broken, "; ".join(broken) or f"{len(app.PAGES)} Seiten fehlerfrei"


# ── last week's runs (repository data only) ─────────────────────────────────

def last_week(today: date) -> list[date]:
    """Monday to Friday of the last complete week before ``today``."""
    monday = today - timedelta(days=today.weekday() + 7) if today.weekday() < 5 else today - timedelta(days=today.weekday())
    return [monday + timedelta(days=offset) for offset in range(5)]


def _snapshot_items(path: Path) -> list[dict]:
    data = json.load(gzip.open(path, "rt", encoding="utf-8"))
    snapshot = data[0] if isinstance(data, list) and data else data
    return snapshot.get("items", []) if isinstance(snapshot, dict) else []


def week_snapshots(today: date | None = None, directory: Path = SNAPSHOT_DIR) -> tuple[bool, str]:
    """Every weekday needs a snapshot with fresh data for 90 % of the stocks and every run group."""
    import snapshot_store
    from stock_agent import RUN_GROUPS, run_group

    days = last_week(today or date.today())
    good, notes = 0, []
    for day in days:
        path = directory / f"{day.isoformat()}{snapshot_store.DAILY_SUFFIX}"
        if not path.exists():
            notes.append(f"{day:%d.%m.} fehlt")
            continue
        items = _snapshot_items(path)
        fresh = snapshot_store.fresh_items(items)
        share = len(fresh) / len(items) if items else 0.0
        groups = {run_group(item.get("symbol")) for item in fresh}
        missing_groups = [group for group in RUN_GROUPS if group not in groups]
        if share >= MIN_FRESH_SHARE and not missing_groups:
            good += 1
        else:
            reason = f"{share:.0%} frisch" + (f", ohne {', '.join(missing_groups)}" if missing_groups else "")
            notes.append(f"{day:%d.%m.} {reason}")
    detail = f"{good} von 5 Handelstagen in Ordnung ({days[0]:%d.%m.}–{days[-1]:%d.%m.})"
    return good >= MIN_GOOD_DAYS, detail + (f" · {'; '.join(notes)}" if notes else "")


def week_bot(today: date | None = None, path: Path = STATE_FILE) -> tuple[bool, str]:
    """The paper bot must have booked a value for the weekdays of last week."""
    if not path.exists():
        return False, "kein Bot-Zustand"
    state = json.loads(path.read_text(encoding="utf-8"))
    booked = {row.get("day") for row in state.get("equity", [])}
    days = last_week(today or date.today())
    missing = [f"{day:%d.%m.}" for day in days if day.isoformat() not in booked]
    good = len(days) - len(missing)
    return good >= MIN_GOOD_DAYS, f"Depotwerte an {good} von 5 Tagen" + (f" · fehlen: {', '.join(missing)}" if missing else "")


def repo_sizes(base: Path = Path(".")) -> tuple[bool, str]:
    sizes = {}
    for folder in SIZE_LIMITS_MB:
        files = [file for file in (base / folder).rglob("*") if file.is_file()] if (base / folder).exists() else []
        sizes[folder] = sum(file.stat().st_size for file in files) / 1e6
    too_big = [f"{folder} {size:.0f} MB > {SIZE_LIMITS_MB[folder]} MB" for folder, size in sizes.items() if size > SIZE_LIMITS_MB[folder]]
    return not too_big, "; ".join(too_big) or ", ".join(f"{folder} {size:.1f} MB" for folder, size in sizes.items())


# ── run everything ──────────────────────────────────────────────────────────

LIVE_PROBES: list[tuple[str, str, Callable[[], tuple[bool, str]], bool]] = [
    ("Yahoo", "Kurse je Region", probe_yahoo_prices, True),
    ("Yahoo", "Tageskerzen Paper-Bot", probe_yahoo_bars, True),
    ("Yahoo", "Stammdaten", probe_yahoo_info, True),
    ("Yahoo", "Analysten", probe_yahoo_analysts, True),
    ("Yahoo", "News, Termine, GuV, Dividenden", probe_yahoo_company_data, True),
    ("Yahoo", "Insider-Tabellen", probe_yahoo_insider, True),
    ("Yahoo", "Symbolsuche", probe_yahoo_search, True),
    ("Yahoo", "Wechselkurse", probe_fx, True),
    ("Finnhub", "Empfehlungen und Insider", probe_finnhub, True),
    ("Gemini", "News-Stimmung", probe_gemini, False),
    ("Indizes", "Wikipedia und Nasdaq", probe_indices, True),
    ("Insider", "Tracefour Deutschland", insider_check.probe_tracefour, True),
    ("Insider", "SIX Schweiz", insider_check.probe_six, True),
    ("Insider", "AMF Frankreich", insider_check.probe_amf, True),
    ("Insider", "AFM Niederlande", insider_check.probe_afm, True),
    ("Nachtlauf", "AAPL, SAP, Toyota komplett", probe_pipeline, True),
    ("App", "Adresse erreichbar", probe_app_url, True),
]

OFFLINE_CHECKS: list[tuple[str, str, Callable[[], tuple[bool, str]], bool]] = [
    ("App", "Alle Seiten rendern", probe_app_pages, True),
    ("Woche", "Snapshots", week_snapshots, True),
    ("Woche", "Paper-Bot", week_bot, True),
    ("Woche", "Insider-Abdeckung", lambda: insider_check.snapshot_coverage(insider_check.latest_snapshot_items()), True),
    ("Woche", "BaFin-Ersatzdatei", insider_check.bafin_file_age, False),
    ("Woche", "Größe der Datenordner", repo_sizes, False),
]


def run_checks() -> list[Check]:
    checks = [run_probe(area, name, probe, hard) for area, name, probe, hard in LIVE_PROBES]
    checks += [run_probe(area, name, probe, hard, retries=0) for area, name, probe, hard in OFFLINE_CHECKS]
    return checks


def report(checks: list[Check], now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    failed = [check for check in checks if not check.ok and check.hard]
    warned = [check for check in checks if not check.ok and not check.hard]
    head = (f"**Wochencheck {now:%d.%m.%Y %H:%M} UTC:** "
            + ("alles in Ordnung" if not failed and not warned else f"{len(failed)} Fehler, {len(warned)} Warnungen"))
    lines = [head, "", "| Bereich | Prüfung | Ergebnis | Detail |", "|---|---|---|---|"]
    for check in checks:
        mark = "✅" if check.ok else ("❌" if check.hard else "⚠️")
        lines.append(f"| {check.area} | {check.name} | {mark} | {check.detail.replace('|', '/')} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Weekly check of all connections and last week's runs.")
    parser.add_argument("--report", help="also write the markdown report to this file")
    args = parser.parse_args(argv)
    checks = run_checks()
    text = report(checks)
    print(text)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    return 1 if any(not check.ok and check.hard for check in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
