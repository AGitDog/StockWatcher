"""Tokyo stocks whose smallest tradable lot costs more than one paper-bot position are not scanned.

Tokyo trades in lots of 100 shares. A lot above the position budget (5,000 EUR) can never be
bought by a depot, so the nightly run leaves these stocks out entirely (decided 25.11.2026).

The list is rebuilt by every Asia run and stored in ``signal_history/zu_teure_pakete.json``,
which the workflow commits with the snapshots, so the later groups of the night use the same list.
Prices come from the latest snapshot; stocks already on the list are refreshed with one small
download, so a stock comes back after a split or a price drop. Without an exchange rate nothing
changes, and a failed refresh keeps a stock on the list with its last known lot cost.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Iterable

EXCLUSION_FILE = Path("signal_history") / "zu_teure_pakete.json"
JAPAN_LOT = 100


def is_tokyo(symbol: str) -> bool:
    return str(symbol).upper().endswith(".T")


def load_exclusions(path: Path | None = None) -> dict:
    try:
        data = json.loads((path or EXCLUSION_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"symbols": {}}
    return data if isinstance(data.get("symbols"), dict) else {"symbols": {}}


def excluded_symbols(path: Path | None = None) -> set[str]:
    return set(load_exclusions(path)["symbols"])


def drop_excluded(entries: list[str], to_symbol: Callable[[str], str], path: Path | None = None) -> tuple[list[str], list[str]]:
    """Watchlist entries without the excluded stocks, and the symbols that were left out."""
    excluded = excluded_symbols(path)
    kept, dropped = [], []
    for entry in entries:
        symbol = to_symbol(entry)
        if symbol in excluded:
            dropped.append(symbol)
        else:
            kept.append(entry)
    return kept, dropped


def lot_cost_eur(price: float | None, eur_jpy: float | None, lot: int = JAPAN_LOT) -> float | None:
    if not price or not eur_jpy or price <= 0 or eur_jpy <= 0:
        return None
    return price * lot / eur_jpy


def update_exclusions(
    symbols: Iterable[str],
    snapshot_prices: dict[str, float],
    eur_jpy: float | None,
    refresh_prices: Callable[[list[str]], dict[str, float]],
    limit_eur: float,
    today: date,
    path: Path | None = None,
) -> dict:
    """Rebuild the list for the Tokyo stocks among ``symbols`` and save it. Returns the new list."""
    previous = load_exclusions(path)
    if not eur_jpy:
        return previous  # no rate: keep yesterday's decision
    tokyo = sorted({s for s in symbols if is_tokyo(s)})
    on_list = [s for s in tokyo if s in previous["symbols"]]
    try:
        fresh = refresh_prices(on_list) if on_list else {}
    except Exception as exc:  # noqa: BLE001 - a failed refresh must not stop the nightly run
        print(f"Kursabruf der ausgelassenen Tokio-Aktien fehlgeschlagen: {exc}", flush=True)
        fresh = {}
    excluded: dict[str, int] = {}
    for symbol in tokyo:
        cost = lot_cost_eur(fresh.get(symbol) or snapshot_prices.get(symbol), eur_jpy)
        if cost is None and symbol in previous["symbols"]:
            cost = float(previous["symbols"][symbol])  # no new price: stay out with the last known cost
        if cost is not None and cost > limit_eur:
            excluded[symbol] = round(cost)
    data = {"day": today.isoformat(), "eur_jpy": round(eur_jpy, 4), "limit_eur": limit_eur,
            "lot": JAPAN_LOT, "symbols": dict(sorted(excluded.items()))}
    path = path or EXCLUSION_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return data


def refresh_for_watchlist(symbols: list[str], today: date | None = None, path: Path | None = None) -> dict:
    """The nightly step: prices from the latest snapshot, rate and refresh via Yahoo."""
    import paper_bot
    import snapshot_store
    from stock_agent import load_signal_snapshot_history

    today = today or date.today()
    history = load_signal_snapshot_history(paper_bot.WATCHLIST_NAME)
    items = history[-1].get("items", []) if history else []
    prices = {item["symbol"]: price for item in snapshot_store.fresh_items(items)
              if is_tokyo(item.get("symbol", "")) and (price := paper_bot.item_price(item))}

    def last_closes(tickers: list[str]) -> dict[str, float]:
        bars = paper_bot.download_bars(tickers, today - timedelta(days=10))
        return {symbol: float(frame["Close"].dropna().iloc[-1]) for symbol, frame in bars.items() if not frame["Close"].dropna().empty}

    try:
        eur_jpy = last_closes(["EURJPY=X"]).get("EURJPY=X")
    except Exception as exc:  # noqa: BLE001
        print(f"Wechselkurs EUR/JPY nicht abrufbar, Liste bleibt: {exc}", flush=True)
        eur_jpy = None
    cfg = paper_bot.DEFAULT_CONFIG
    return update_exclusions(symbols, prices, eur_jpy, last_closes, cfg["position_budget"] - cfg["fee"], today, path)
