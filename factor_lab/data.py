"""Price data and universe loading for the factor research.

Survivorship warning: index constituent lists are today's members. Companies that
left the index or went bankrupt are missing, which flatters absolute returns.
Point-in-time constituent lists are not freely available; the report states this.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

CACHE_DIR = Path("cache/factor_lab")
SHARE_CLASS_SUFFIXES = {"A", "B", "C"}
_SUFFIX = re.compile(r"^(?P<root>[A-Z0-9]+)\.(?P<suffix>[A-Z]{1,4})$")


def to_yahoo_symbol(symbol: str) -> str:
    """Convert US share classes such as BRK.B to the Yahoo spelling BRK-B."""
    symbol = symbol.strip().upper()
    match = _SUFFIX.match(symbol)
    if match and match.group("suffix") in SHARE_CLASS_SUFFIXES:
        return f"{match.group('root')}-{match.group('suffix')}"
    return symbol


def is_us_listing(symbol: str) -> bool:
    """True for symbols without a foreign exchange suffix like .DE, .T or .AX."""
    symbol = to_yahoo_symbol(symbol)
    if symbol.startswith("^"):
        return False
    return _SUFFIX.match(symbol) is None


def filter_single_currency(symbols: list[str], us_only: bool = True) -> list[str]:
    """Keep one listing currency so portfolio returns are not distorted by FX.

    Mixing USD, EUR and JPY prices without conversion would make the backtest wrong.
    """
    converted = [to_yahoo_symbol(s) for s in symbols if s and s.strip()]
    if us_only:
        converted = [s for s in converted if is_us_listing(s)]
    seen: set[str] = set()
    unique = []
    for symbol in converted:
        if symbol not in seen:
            seen.add(symbol)
            unique.append(symbol)
    return unique


def load_universe(source: str, us_only: bool = True) -> list[str]:
    """Load symbols from an index name (e.g. ``S&P 500``) or a watchlist file path."""
    import stock_agent

    path = Path(source)
    if path.suffix == ".txt" and path.exists():
        symbols = stock_agent.parse_watchlist_text(path.read_text(encoding="utf-8"))
    else:
        index_name = stock_agent._match_index_alias(source) or source
        symbols = stock_agent.load_index_constituents(index_name)
        if not symbols:
            raise ValueError(f"Unbekanntes Universum: {source}")
    return filter_single_currency(symbols, us_only=us_only)


def _cache_path(symbols: list[str], start: str, end: str | None, cache_dir: Path) -> Path:
    key = json.dumps({"s": sorted(symbols), "start": start, "end": end or date.today().isoformat()})
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"close_{digest}.pkl"


def _extract_close(raw: pd.DataFrame, chunk: list[str]) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = raw.columns.get_level_values(0)
        if "Close" in level0:
            close = raw["Close"]
        else:
            close = raw.xs("Close", axis=1, level=1)
    else:
        close = raw[["Close"]].rename(columns={"Close": chunk[0]})
    close = close.copy()
    close.index = pd.to_datetime(close.index)
    if close.index.tz is not None:
        close.index = close.index.tz_localize(None)
    return close


def download_close_prices(
    symbols: list[str],
    start: str = "2005-01-01",
    end: str | None = None,
    cache_dir: Path = CACHE_DIR,
    chunk_size: int = 100,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Download split- and dividend-adjusted daily closes as a wide frame."""
    import yfinance as yf

    symbols = [s for s in dict.fromkeys(symbols) if s]
    if not symbols:
        return pd.DataFrame()
    cache_file = _cache_path(symbols, start, end, cache_dir)
    if use_cache and cache_file.exists():
        try:
            return pd.read_pickle(cache_file)
        except Exception as exc:  # corrupt cache, fall through to download
            logger.warning("Cache %s unlesbar: %s", cache_file, exc)

    frames = []
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i : i + chunk_size]
        try:
            raw = yf.download(
                chunk,
                start=start,
                end=end,
                auto_adjust=True,
                progress=False,
                threads=True,
                group_by="column",
            )
            frames.append(_extract_close(raw, chunk))
        except Exception as exc:
            logger.warning("Download fuer %s Symbole fehlgeschlagen: %s", len(chunk), exc)
    if not frames:
        return pd.DataFrame()
    close = pd.concat(frames, axis=1)
    close = close.loc[:, ~close.columns.duplicated()].sort_index()
    close = close.dropna(axis=1, how="all")
    if use_cache:
        cache_dir.mkdir(parents=True, exist_ok=True)
        close.to_pickle(cache_file)
    return close


def load_sector_map(history_dir: Path = Path("signal_history")) -> dict[str, str]:
    """Sector per symbol from the stored signal snapshots (latest entry wins)."""
    sectors: dict[str, str] = {}
    if not history_dir.exists():
        return sectors
    for file_path in sorted(history_dir.glob("*.json")):
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for snapshot in data if isinstance(data, list) else []:
            for item in snapshot.get("items", []) if isinstance(snapshot, dict) else []:
                symbol = item.get("symbol")
                sector = item.get("sector")
                if symbol and sector and sector != "Unbekannt":
                    sectors[to_yahoo_symbol(symbol)] = str(sector)
    return sectors
