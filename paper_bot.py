"""Paper-trading bot: trades the Brodel 2.0 signals with a trailing stop-loss, forward only.

Rules (agreed in chat, 05.11.2026):
- Once a day after the last region run (america-2). The decision uses that day's snapshot only.
- Buy every fresh entry with Brodel 2.0 >= 60, highest score first, 5,000 EUR each, at most 20 positions.
  Orders are filled at the next trading day's open of the stock's exchange (1 EUR fee).
- Stop-loss 15 % below entry. It follows the highest close upwards and never goes down.
  Once the highest close is 25 % above entry the distance tightens to 10 %.
- A stop is triggered when the day's low touches it. If the stock opens below the stop
  (gap), it is sold at the open, otherwise at the stop price minus 0.5 % slippage
  (a triggered stop becomes a market order), but never below the day's low.
- A stock that was stopped out may be bought again only after 28 calendar days (about 20 trading days).

Two comparison portfolios run alongside: the same rules without stop-loss, and a MSCI World ETF.
State lives in ``bot_depot/state.json`` (committed by the workflow).

    python paper_bot.py run       # daily step (workflow)
    python paper_bot.py status    # print positions and values
    python paper_bot.py reset     # start over with fresh capital
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

import snapshot_store
from stock_agent import load_signal_snapshot_history, primary_score, snapshot_day

STATE_FILE = Path("bot_depot/state.json")
WATCHLIST_NAME = "meine_watchlist.txt"
ETF_SYMBOL = "EUNL.DE"  # iShares Core MSCI World, Xetra, EUR

DEFAULT_CONFIG: dict[str, Any] = {
    "capital": 100_000.0,
    "position_budget": 5_000.0,
    "max_positions": 20,
    "buy_threshold": 60,
    "initial_stop": 0.15,
    "tight_stop": 0.10,
    "tighten_after_gain": 0.25,
    "cooldown_days": 28,
    "fee": 1.0,
    "stop_slippage": 0.005,
    "order_expiry_days": 7,
}

PORTFOLIOS = {
    "bot": {"label": "Bot mit Stop-Loss", "use_stop": True},
    "no_stop": {"label": "Gleiche Käufe ohne Stop-Loss", "use_stop": False},
}

# exchange suffix -> (currency, price divisor); London quotes in pence
SUFFIX_CURRENCY = {
    "": ("USD", 1), "TO": ("CAD", 1), "V": ("CAD", 1), "NE": ("CAD", 1),
    "T": ("JPY", 1), "NS": ("INR", 1), "BO": ("INR", 1), "HK": ("HKD", 1), "AX": ("AUD", 1),
    "KS": ("KRW", 1), "KQ": ("KRW", 1), "SI": ("SGD", 1), "TW": ("TWD", 1),
    "L": ("GBP", 100), "IL": ("USD", 1), "SW": ("CHF", 1), "VX": ("CHF", 1),
    "ST": ("SEK", 1), "CO": ("DKK", 1), "OL": ("NOK", 1), "WA": ("PLN", 1),
}


# ----------------------------------------------------------------------------- helpers
def currency_of(symbol: str) -> tuple[str, int]:
    value = str(symbol).upper()
    if value.startswith("^"):
        return "USD", 1
    suffix = value.rsplit(".", 1)[1] if "." in value else ""
    return SUFFIX_CURRENCY.get(suffix, ("EUR", 1) if suffix else ("USD", 1))


def fx_symbol(currency: str) -> str | None:
    return None if currency == "EUR" else f"EUR{currency}=X"


def decision_cutoff(now: datetime) -> date:
    """Last day whose daily bars are complete everywhere (US closes 21:00 UTC)."""
    day = date.fromisoformat(snapshot_day(now))
    if 7 <= now.hour < 21 and now.date() == day:
        return day - timedelta(days=1)
    return day


def _bars_after(frame: pd.DataFrame | None, after: date, until: date) -> list[tuple[date, pd.Series]]:
    if frame is None or frame.empty:
        return []
    rows = []
    for stamp, bar in frame.iterrows():
        day = pd.Timestamp(stamp).date()
        if after < day <= until and all(pd.notna(bar.get(col)) for col in ("Open", "Low", "Close")):
            rows.append((day, bar))
    return rows


def _fx_rate(fx: dict[str, pd.DataFrame], currency: str, day: date) -> float | None:
    """EUR -> currency rate on ``day`` (last known close up to that day)."""
    symbol = fx_symbol(currency)
    if symbol is None:
        return 1.0
    frame = fx.get(symbol)
    if frame is None or frame.empty:
        return None
    closes = frame["Close"].dropna()
    closes = closes[[pd.Timestamp(i).date() <= day for i in closes.index]]
    return float(closes.iloc[-1]) if len(closes) else None


def to_eur(price: float, symbol: str, day: date, fx: dict[str, pd.DataFrame]) -> float | None:
    currency, divisor = currency_of(symbol)
    rate = _fx_rate(fx, currency, day)
    if rate is None or not rate or price is None or not math.isfinite(price):
        return None
    return price / divisor / rate


# ----------------------------------------------------------------------------- state
def new_state(now: datetime, config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    state: dict[str, Any] = {
        "config": cfg,
        "started": now.strftime("%Y-%m-%d"),
        "last_run": None,
        "portfolios": {},
        "etf": {"symbol": ETF_SYMBOL, "cash": cfg["capital"], "shares": 0.0, "bought_on": None, "last_value": cfg["capital"]},
        "equity": [],
    }
    for key, meta in PORTFOLIOS.items():
        state["portfolios"][key] = {
            "label": meta["label"],
            "use_stop": meta["use_stop"],
            "cash": cfg["capital"],
            "positions": [],
            "pending": [],
            "trades": [],
            "cooldown": {},
        }
    return state


def load_state(path: Path = STATE_FILE) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any], path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    temp.replace(path)


# ----------------------------------------------------------------------------- trading logic
def stop_distance(position: dict[str, Any], cfg: dict[str, Any]) -> float:
    gain = position["high_close"] / position["entry_price"] - 1
    return cfg["tight_stop"] if gain > cfg["tighten_after_gain"] else cfg["initial_stop"]


def _sell(pf: dict, position: dict, day: date, price: float, reason: str, fx: dict, cfg: dict) -> bool:
    price_eur = to_eur(price, position["symbol"], day, fx)
    if price_eur is None:
        return False  # no FX rate yet: keep the position, retry next run
    proceeds = position["shares"] * price_eur - cfg["fee"]
    pf["cash"] += proceeds
    cost = position["cost_eur"]
    pf["trades"].append({
        "symbol": position["symbol"], "name": position.get("name", ""), "side": "Verkauf", "reason": reason,
        "day": day.isoformat(), "price": round(price, 4), "shares": position["shares"],
        "value_eur": round(proceeds, 2), "pnl_eur": round(proceeds - cost, 2),
        "pnl_pct": round((proceeds / cost - 1) * 100, 2) if cost else None,
        "held_since": position["entry_day"],
    })
    pf["cooldown"][position["symbol"]] = day.isoformat()
    return True


def process_position(pf: dict, position: dict, bars: list[tuple[date, pd.Series]], fx: dict, cfg: dict) -> bool:
    """Walk new daily bars; returns False when the position was closed."""
    for day, bar in bars:
        if pf["use_stop"]:
            stop = position["stop"]
            if float(bar["Open"]) <= stop:
                if _sell(pf, position, day, float(bar["Open"]), "Stop-Loss (Kurslücke, Verkauf zur Eröffnung)", fx, cfg):
                    return False
            elif float(bar["Low"]) <= stop:
                # a triggered stop becomes a market order: assume a small slippage, never below the day's low
                price = max(float(bar["Low"]), stop * (1 - cfg.get("stop_slippage", 0.0)))
                if _sell(pf, position, day, price, "Stop-Loss", fx, cfg):
                    return False
        close = float(bar["Close"])
        position["high_close"] = max(position["high_close"], close)
        position["last_price"] = close
        position["last_day"] = day.isoformat()
        if pf["use_stop"]:
            position["stop"] = round(max(position["stop"], position["high_close"] * (1 - stop_distance(position, cfg))), 6)
    return True


def fill_pending(pf: dict, order: dict, bars: list[tuple[date, pd.Series]], fx: dict, cfg: dict) -> dict | None:
    """Fill a buy order at the first open after its decision day. Returns the new position or None."""
    if not bars:
        return None
    day, bar = bars[0]
    open_price = float(bar["Open"])
    open_eur = to_eur(open_price, order["symbol"], day, fx)
    if open_eur is None or open_eur <= 0:
        return None
    shares = math.floor((cfg["position_budget"] - cfg["fee"]) / open_eur)
    order["status"] = "done"
    if shares <= 0:
        pf["cash"] += order["reserved"]
        pf["trades"].append({"symbol": order["symbol"], "name": order.get("name", ""), "side": "Storniert",
                             "reason": "Eine Aktie kostet mehr als das Budget", "day": day.isoformat()})
        return None
    cost = shares * open_eur + cfg["fee"]
    pf["cash"] += order["reserved"] - cost
    position = {
        "symbol": order["symbol"], "name": order.get("name", ""), "score_at_buy": order["score"],
        "entry_day": day.isoformat(), "entry_price": open_price, "shares": shares, "cost_eur": round(cost, 2),
        "high_close": open_price, "stop": round(open_price * (1 - cfg["initial_stop"]), 6),
        "last_price": open_price, "last_day": day.isoformat(), "currency": currency_of(order["symbol"])[0],
    }
    pf["trades"].append({"symbol": order["symbol"], "name": order.get("name", ""), "side": "Kauf",
                         "reason": f"Brodel 2.0 = {order['score']}", "day": day.isoformat(),
                         "price": round(open_price, 4), "shares": shares, "value_eur": round(cost, 2)})
    return position


def buy_candidates(snapshot: dict | None, threshold: float) -> list[dict]:
    """Fresh entries of the decision snapshot at or above the threshold, best first."""
    items = snapshot_store.fresh_items(snapshot.get("items", [])) if snapshot else []
    scored = [(primary_score(item), item) for item in items if item.get("symbol")]
    chosen = [(score, item) for score, item in scored if score >= threshold]
    chosen.sort(key=lambda pair: (-pair[0], str(pair[1]["symbol"])))
    return [{"symbol": item["symbol"], "name": item.get("name", ""), "score": score} for score, item in chosen]


def place_orders(pf: dict, candidates: list[dict], decision_day: date, cfg: dict) -> list[dict]:
    held = {p["symbol"] for p in pf["positions"]} | {o["symbol"] for o in pf["pending"]}
    placed = []
    for cand in candidates:
        if len(pf["positions"]) + len(pf["pending"]) >= cfg["max_positions"]:
            break
        if cand["symbol"] in held:
            continue
        sold_on = pf["cooldown"].get(cand["symbol"])
        if sold_on and (decision_day - date.fromisoformat(sold_on)).days < cfg["cooldown_days"]:
            continue
        if pf["cash"] < cfg["position_budget"]:
            break
        pf["cash"] -= cfg["position_budget"]
        order = {**cand, "order_day": decision_day.isoformat(), "reserved": cfg["position_budget"], "status": "open"}
        pf["pending"].append(order)
        held.add(cand["symbol"])
        placed.append(order)
    return placed


def portfolio_value(pf: dict, fx: dict, day: date) -> float:
    total = pf["cash"] + sum(order["reserved"] for order in pf["pending"])
    for position in pf["positions"]:
        value = to_eur(position["last_price"], position["symbol"], day, fx)
        if value is not None:
            position["last_value_eur"] = round(value * position["shares"], 2)
        total += position.get("last_value_eur", position["cost_eur"])
    return round(total, 2)


def step(state: dict, snapshot: dict | None, bars: dict[str, pd.DataFrame], fx: dict[str, pd.DataFrame], now: datetime) -> dict:
    """One daily run for all portfolios. Idempotent: bars are processed once, orders once per day."""
    cfg = state["config"]
    cutoff = decision_cutoff(now)
    decision_day = date.fromisoformat(snapshot_day(now))
    summary: dict[str, Any] = {"cutoff": cutoff.isoformat(), "decision_day": decision_day.isoformat()}

    for key, pf in state["portfolios"].items():
        # 1. fill orders of earlier days at the next open
        still_open = []
        for order in pf["pending"]:
            order_bars = _bars_after(bars.get(order["symbol"]), date.fromisoformat(order["order_day"]), cutoff)
            position = fill_pending(pf, order, order_bars, fx, cfg)
            if position is not None:
                # the stop is active from the fill day on: the low of the fill day already counts
                if process_position(pf, position, order_bars, fx, cfg):
                    pf["positions"].append(position)
            elif order.get("status") != "done":
                age = (cutoff - date.fromisoformat(order["order_day"])).days
                if age > cfg["order_expiry_days"]:
                    pf["cash"] += order["reserved"]
                    pf["trades"].append({"symbol": order["symbol"], "name": order.get("name", ""), "side": "Storniert",
                                         "reason": "Keine Kursdaten nach der Kaufentscheidung", "day": cutoff.isoformat()})
                else:
                    still_open.append(order)
        pf["pending"] = still_open

        # 2. walk new bars of held positions (stops, trailing)
        kept = []
        for position in pf["positions"]:
            new_bars = _bars_after(bars.get(position["symbol"]), date.fromisoformat(position["last_day"]), cutoff)
            if process_position(pf, position, new_bars, fx, cfg):
                kept.append(position)
        pf["positions"] = kept

        # 3. new orders from today's snapshot (once per decision day)
        if pf.get("last_decision") != decision_day.isoformat():
            placed = place_orders(pf, buy_candidates(snapshot, cfg["buy_threshold"]), decision_day, cfg)
            pf["last_decision"] = decision_day.isoformat()
            summary[f"{key}_orders"] = [o["symbol"] for o in placed]

    # ETF benchmark: invest everything at the first available open
    etf = state["etf"]
    # bought at the first open after the start day, like the bot's first orders
    etf_bars = _bars_after(bars.get(etf["symbol"]), date.fromisoformat(state["started"]), cutoff)
    if etf["bought_on"] is None and etf_bars:
        day, bar = etf_bars[0]
        etf["shares"] = (etf["cash"] - cfg["fee"]) / float(bar["Open"])
        etf["cash"] = 0.0
        etf["bought_on"] = day.isoformat()
    if etf["bought_on"] and etf_bars:
        etf["last_value"] = round(etf["cash"] + etf["shares"] * float(etf_bars[-1][1]["Close"]), 2)

    point = {"day": cutoff.isoformat(), "etf": etf["last_value"]}
    for key, pf in state["portfolios"].items():
        point[key] = portfolio_value(pf, fx, cutoff)
    state["equity"] = [p for p in state["equity"] if p["day"] != point["day"]] + [point]
    state["last_run"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    summary["equity"] = point
    return summary


# ----------------------------------------------------------------------------- data
def symbols_needed(state: dict) -> list[str]:
    symbols = {state["etf"]["symbol"]}
    for pf in state["portfolios"].values():
        symbols.update(p["symbol"] for p in pf["positions"])
        symbols.update(o["symbol"] for o in pf["pending"])
    return sorted(symbols)


def download_bars(symbols: list[str], start: date) -> dict[str, pd.DataFrame]:
    """Daily OHLC for few symbols in one request."""
    import yfinance as yf

    if not symbols:
        return {}
    raw = yf.download(symbols, start=start.isoformat(), auto_adjust=False, group_by="ticker", progress=False, threads=True)
    result: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        try:
            frame = raw[symbol] if isinstance(raw.columns, pd.MultiIndex) else raw
        except KeyError:
            continue
        frame = frame[["Open", "High", "Low", "Close"]].dropna(subset=["Close"])
        if not frame.empty:
            result[symbol] = frame
    return result


def run(
    now: datetime | None = None,
    state_path: Path = STATE_FILE,
    loader: Callable[[list[str], date], dict[str, pd.DataFrame]] = download_bars,
    snapshot: dict | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    state = load_state(state_path) or new_state(now)
    if snapshot is None:
        history = load_signal_snapshot_history(WATCHLIST_NAME)
        snapshot = history[-1] if history else None
        if snapshot and snapshot_store._day_of(snapshot) != snapshot_day(now):
            snapshot = None  # no snapshot for today: manage positions, but no new buys
    symbols = symbols_needed(state)  # new orders need prices only from the next run on
    currencies = {currency_of(s)[0] for s in symbols}
    fx_symbols = sorted(filter(None, (fx_symbol(c) for c in currencies)))
    oldest = min(
        [date.fromisoformat(state["started"])]
        + [date.fromisoformat(p["last_day"]) for pf in state["portfolios"].values() for p in pf["positions"]]
        + [date.fromisoformat(o["order_day"]) for pf in state["portfolios"].values() for o in pf["pending"]]
    ) - timedelta(days=10)
    data = loader(symbols + fx_symbols, oldest)
    fx = {s: data[s] for s in fx_symbols if s in data}
    summary = step(state, snapshot, data, fx, now)
    save_state(state, state_path)
    return summary


def status_text(state: dict) -> str:
    lines = [f"Start {state['started']}, letzter Lauf {state['last_run']}"]
    last = state["equity"][-1] if state["equity"] else {}
    for key, pf in state["portfolios"].items():
        lines.append(f"\n{pf['label']}: {last.get(key, pf['cash']):,.2f} EUR, Cash {pf['cash']:,.2f}, "
                     f"{len(pf['positions'])} Positionen, {len(pf['pending'])} offene Orders")
        for p in pf["positions"]:
            lines.append(f"  {p['symbol']:10s} seit {p['entry_day']}  Kauf {p['entry_price']:.2f}  "
                         f"aktuell {p['last_price']:.2f}  Stop {p['stop']:.2f}")
    lines.append(f"\nETF {state['etf']['symbol']}: {state['etf']['last_value']:,.2f} EUR")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Brodel paper-trading bot")
    parser.add_argument("command", choices=("run", "status", "reset"))
    args = parser.parse_args(argv)
    if args.command == "run":
        print(json.dumps(run(), indent=1, ensure_ascii=False))
    elif args.command == "status":
        state = load_state()
        print(status_text(state) if state else "Noch kein Bot-Depot angelegt.")
    else:
        save_state(new_state(datetime.now(timezone.utc)))
        print("Bot-Depot neu angelegt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
