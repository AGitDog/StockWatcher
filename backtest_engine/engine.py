"""Backtest engine that simulates a portfolio from signal snapshots."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

from .portfolio import Portfolio, Trade

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

HISTORY_DIR = Path("signal_history")


@dataclass
class BacktestResult:
    """Container for backtest results."""

    strategy_name: str
    initial_cash: float
    final_value: float
    total_return_pct: float
    cagr_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    num_trades: int
    benchmark_return_pct: float
    alpha_pct: float
    equity_curve: pd.DataFrame = field(default_factory=pd.DataFrame)
    trades: list[dict[str, Any]] = field(default_factory=list)
    component_correlation: pd.Series | None = None

    def summary(self) -> str:
        lines = [
            f"--- Backtest: {self.strategy_name} ---",
            f"Initial Cash:        ${self.initial_cash:,.2f}",
            f"Final Value:         ${self.final_value:,.2f}",
            f"Total Return:        {self.total_return_pct:+.2f}%",
            f"CAGR:                {self.cagr_pct:+.2f}%",
            f"Sharpe Ratio:        {self.sharpe_ratio:.2f}",
            f"Max Drawdown:        {self.max_drawdown_pct:.2f}%",
            f"Win Rate:            {self.win_rate:.1f}%",
            f"Profit Factor:       {self.profit_factor:.2f}",
            f"# Trades:            {self.num_trades}",
            f"Benchmark Return:    {self.benchmark_return_pct:+.2f}%",
            f"Alpha:               {self.alpha_pct:+.2f}%",
        ]
        return "\n".join(lines)


def load_snapshots(history_dir: Path = HISTORY_DIR) -> list[tuple[datetime, list[dict[str, Any]]]]:
    """Load all signal snapshots from disk."""
    snapshots: list[tuple[datetime, list[dict[str, Any]]]] = []
    if not history_dir.exists():
        return snapshots

    for file_path in history_dir.glob("*.json"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            mtime = file_path.stat().st_mtime
            if isinstance(data, list) and data:
                for snapshot in data:
                    if not isinstance(snapshot, dict) or "items" not in snapshot:
                        continue
                    timestamp = snapshot.get("timestamp")
                    parsed_timestamp = pd.to_datetime(timestamp, errors="coerce", utc=True)
                    if pd.isna(parsed_timestamp):
                        dt = datetime.fromtimestamp(mtime)
                    else:
                        dt = parsed_timestamp.to_pydatetime().replace(tzinfo=None)
                    snapshots.append((dt, snapshot["items"]))
        except Exception as e:
            logger.error(f"Fehler beim Laden von {file_path}: {e}")

    snapshots.sort(key=lambda x: x[0])
    return snapshots


def fetch_prices(
    symbols: set[str],
    start_date: datetime,
    end_date: datetime,
) -> dict[str, pd.DataFrame]:
    """Fetch historical prices for a set of symbols."""
    prices: dict[str, pd.DataFrame] = {}
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = (end_date + timedelta(days=1)).strftime("%Y-%m-%d")

    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(start=start_str, end=end_str, auto_adjust=True)
            if not hist.empty and "Close" in hist.columns:
                prices[symbol] = hist
        except Exception as e:
            logger.debug(f"Konnte Preise für {symbol} nicht laden: {e}")

    return prices


def fetch_benchmark_return(
    benchmark: str,
    start_date: datetime,
    end_date: datetime,
) -> float:
    """Calculate buy-and-hold return for a benchmark."""
    try:
        ticker = yf.Ticker(benchmark)
        hist = ticker.history(
            start=start_date.strftime("%Y-%m-%d"),
            end=(end_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            auto_adjust=True,
        )
        if hist.empty or len(hist) < 2:
            return 0.0
        start_price = float(hist["Close"].iloc[0])
        end_price = float(hist["Close"].iloc[-1])
        return (end_price / start_price - 1.0) * 100.0
    except Exception as e:
        logger.warning(f"Benchmark-Daten konnten nicht geladen werden: {e}")
        return 0.0


def _price_on_or_after(
    hist: pd.DataFrame,
    target_date: datetime,
) -> float | None:
    """Get the first available close price on or after target_date."""
    if hist.empty:
        return None
    tz = hist.index.tz
    if tz:
        target_ts = pd.Timestamp(target_date).tz_localize(tz)
    else:
        target_ts = pd.Timestamp(target_date)

    mask = hist.index >= target_ts
    if not mask.any():
        return None
    return float(hist.loc[mask, "Close"].iloc[0])


def _price_on_or_before(
    hist: pd.DataFrame,
    target_date: datetime,
) -> float | None:
    """Get the last available close price on or before target_date."""
    if hist.empty:
        return None
    tz = hist.index.tz
    if tz:
        target_ts = pd.Timestamp(target_date).tz_localize(tz)
    else:
        target_ts = pd.Timestamp(target_date)

    mask = hist.index <= target_ts
    if not mask.any():
        return None
    return float(hist.loc[mask, "Close"].iloc[-1])


def _trading_dates(
    prices: dict[str, pd.DataFrame],
    start_date: datetime,
    end_date: datetime,
) -> list[datetime]:
    """Return sorted, unique market dates available in the price data."""
    dates: set[datetime] = set()
    for hist in prices.values():
        for value in hist.index:
            timestamp = pd.Timestamp(value)
            if timestamp.tzinfo is not None:
                timestamp = timestamp.tz_localize(None)
            date = timestamp.normalize().to_pydatetime()
            if start_date.date() <= date.date() <= end_date.date():
                dates.add(date)
    return sorted(dates)


def _calculate_metrics(equity_curve: pd.DataFrame, risk_free_rate: float = 0.0) -> dict[str, float]:
    """Calculate performance metrics from an equity curve."""
    if equity_curve.empty or "total_value" not in equity_curve.columns:
        return {
            "total_return_pct": 0.0,
            "cagr_pct": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
        }

    values = equity_curve["total_value"].values
    total_return = (values[-1] / values[0] - 1.0) * 100.0

    # Prefer the actual calendar span; fall back to trading rows for synthetic tests.
    if isinstance(equity_curve.index, pd.DatetimeIndex) and len(equity_curve.index) > 1:
        calendar_days = max(1, (equity_curve.index[-1] - equity_curve.index[0]).days)
        years = calendar_days / 365.25
    else:
        years = max(1, len(values) - 1) / 252.0
    cagr = ((values[-1] / values[0]) ** (1.0 / years) - 1.0) * 100.0 if years > 0 else 0.0

    # Daily returns
    daily_returns = np.diff(values) / values[:-1]
    if len(daily_returns) > 1 and daily_returns.std() > 0:
        sharpe = (daily_returns.mean() - risk_free_rate / 252.0) / daily_returns.std() * np.sqrt(252.0)
    else:
        sharpe = 0.0

    # Max drawdown
    peak = np.maximum.accumulate(values)
    drawdown = (values - peak) / peak
    max_dd = drawdown.min() * 100.0

    return {
        "total_return_pct": total_return,
        "cagr_pct": cagr,
        "sharpe_ratio": sharpe,
        "max_drawdown_pct": max_dd,
    }


class BacktestEngine:
    """Run a strategy backtest over historical snapshots."""

    def __init__(
        self,
        initial_cash: float = 100_000.0,
        transaction_cost_pct: float = 0.001,
        max_positions: int = 10,
        rebalance_days: int = 30,
        benchmark: str = "SPY",
        max_lookback_days: int = 365,
        risk_per_trade_pct: float | None = 0.0075,
    ) -> None:
        self.initial_cash = initial_cash
        self.transaction_cost_pct = transaction_cost_pct
        self.max_positions = max_positions
        self.rebalance_days = rebalance_days
        self.benchmark = benchmark
        self.max_lookback_days = max_lookback_days
        self.risk_per_trade_pct = risk_per_trade_pct

    def run(
        self,
        snapshots: list[tuple[datetime, list[dict[str, Any]]]],
        signal_filter: Any | None = None,
        strategy_name: str = "brodel_top_n",
    ) -> BacktestResult:
        """Run backtest on a list of snapshots.

        signal_filter: callable that receives (item, snapshot_date) and returns
        a dict with keys: direction, position_size_pct, stop_loss, take_profit, strategy.
        If None, defaults to top-N long positions by brodel_score.
        """
        if not snapshots:
            return BacktestResult(strategy_name=strategy_name, initial_cash=self.initial_cash, final_value=self.initial_cash)

        start_date = snapshots[0][0]
        end_date = snapshots[-1][0]

        # Collect all symbols
        all_symbols: set[str] = set()
        for _, items in snapshots:
            for item in items:
                symbol = item.get("symbol")
                if symbol:
                    all_symbols.add(symbol)

        # Fetch prices
        prices = fetch_prices(all_symbols, start_date, end_date + timedelta(days=self.rebalance_days + 5))

        portfolio = Portfolio(
            initial_cash=self.initial_cash,
            transaction_cost_pct=self.transaction_cost_pct,
            max_positions=self.max_positions,
        )

        market_dates = _trading_dates(prices, start_date, end_date)
        if not market_dates:
            market_dates = [start_date]

        snapshots_by_date = {
            snapshot_date.date(): (snapshot_date, items)
            for snapshot_date, items in snapshots
            if (end_date - snapshot_date).days >= self.rebalance_days - 5
        }
        last_rebalance: datetime | None = None
        pending_signals: list[dict[str, Any]] = []

        for market_date in market_dates:
            day_prices = {
                symbol: _price_on_or_before(hist, market_date)
                for symbol, hist in prices.items()
            }
            portfolio.apply_stop_take(day_prices, market_date)

            # Execute yesterday's signal at the first available next-day close.
            for signal in pending_signals:
                symbol = signal["symbol"]
                entry_price = day_prices.get(symbol)
                if entry_price is None:
                    continue
                portfolio.open_trade(
                    symbol=symbol,
                    direction=signal.get("direction", "long"),
                    entry_date=market_date,
                    entry_price=entry_price,
                    position_size_pct=signal.get("position_size_pct", 1.0 / self.max_positions),
                    stop_loss=signal.get("stop_loss"),
                    take_profit=signal.get("take_profit"),
                    strategy=signal.get("strategy", strategy_name),
                    risk_per_trade_pct=self.risk_per_trade_pct,
                )
            pending_signals = []

            snapshot_entry = snapshots_by_date.get(market_date.date())
            if snapshot_entry:
                snapshot_date, items = snapshot_entry
                if last_rebalance is None or (snapshot_date - last_rebalance).days >= self.rebalance_days:
                    last_rebalance = snapshot_date
                    for trade in list(portfolio.open_trades()):
                        exit_price = day_prices.get(trade.symbol)
                        if exit_price is not None:
                            portfolio.close_trade(trade.symbol, market_date, exit_price)
                    pending_signals = self._select_signals(items, snapshot_date, signal_filter)

            portfolio.record_equity(market_date, day_prices)

        # Final valuation
        final_date = market_dates[-1]
        final_prices = {s: _price_on_or_before(hist, final_date) for s, hist in prices.items()}
        for trade in list(portfolio.open_trades()):
            exit_price = final_prices.get(trade.symbol)
            if exit_price is not None:
                portfolio.close_trade(trade.symbol, final_date, exit_price)

        final_value = portfolio.total_value(final_prices)

        equity_df = pd.DataFrame(portfolio.equity_curve)
        if not equity_df.empty:
            equity_df["date"] = pd.to_datetime(equity_df["date"])
            equity_df = equity_df.set_index("date").sort_index()

        metrics = _calculate_metrics(equity_df)

        closed_trades = [t for t in portfolio.trades if t.status == "closed"]
        winners = [t for t in closed_trades if (t.pnl_pct or 0) > 0]
        losers = [t for t in closed_trades if (t.pnl_pct or 0) <= 0]
        win_rate = (len(winners) / len(closed_trades) * 100.0) if closed_trades else 0.0
        gross_profit = sum((t.pnl_amount or 0) for t in winners)
        gross_loss = abs(sum((t.pnl_amount or 0) for t in losers))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)

        benchmark_return = fetch_benchmark_return(self.benchmark, start_date, end_date)
        alpha = metrics["total_return_pct"] - benchmark_return

        return BacktestResult(
            strategy_name=strategy_name,
            initial_cash=self.initial_cash,
            final_value=final_value,
            total_return_pct=metrics["total_return_pct"],
            cagr_pct=metrics["cagr_pct"],
            sharpe_ratio=metrics["sharpe_ratio"],
            max_drawdown_pct=metrics["max_drawdown_pct"],
            win_rate=win_rate,
            profit_factor=profit_factor,
            num_trades=len(closed_trades),
            benchmark_return_pct=benchmark_return,
            alpha_pct=alpha,
            equity_curve=equity_df,
            trades=[
                {
                    "symbol": t.symbol,
                    "direction": t.direction,
                    "entry_date": t.entry_date.isoformat(),
                    "entry_price": t.entry_price,
                    "exit_date": t.exit_date.isoformat() if t.exit_date else None,
                    "exit_price": t.exit_price,
                    "pnl_pct": t.pnl_pct,
                    "pnl_amount": t.pnl_amount,
                    "strategy": t.strategy,
                }
                for t in closed_trades
            ],
        )

    def _select_signals(
        self,
        items: list[dict[str, Any]],
        snapshot_date: datetime,
        signal_filter: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Select signals from a snapshot."""
        if signal_filter is not None:
            signals = []
            for item in items:
                try:
                    sig = signal_filter(item, snapshot_date)
                    if sig:
                        sig["symbol"] = item.get("symbol")
                        signals.append(sig)
                except Exception:
                    continue
            return signals[: self.max_positions]

        # Default: top-N by brodel_score
        sorted_items = sorted(
            [i for i in items if i.get("symbol")],
            key=lambda x: x.get("brodel_score", 0),
            reverse=True,
        )
        signals = []
        for item in sorted_items[: self.max_positions]:
            signals.append(
                {
                    "symbol": item.get("symbol"),
                    "direction": "long",
                    "position_size_pct": 1.0 / self.max_positions,
                    "stop_loss": None,
                    "take_profit": None,
                    "strategy": "brodel_top_n",
                }
            )
        return signals


def run_backtest_on_snapshots(
    history_dir: Path = HISTORY_DIR,
    initial_cash: float = 100_000.0,
    max_positions: int = 10,
    rebalance_days: int = 30,
    benchmark: str = "SPY",
    risk_per_trade_pct: float | None = 0.0075,
) -> BacktestResult:
    """Convenience function to run the default backtest."""
    snapshots = load_snapshots(history_dir)
    engine = BacktestEngine(
        initial_cash=initial_cash,
        max_positions=max_positions,
        rebalance_days=rebalance_days,
        benchmark=benchmark,
        risk_per_trade_pct=risk_per_trade_pct,
    )
    return engine.run(snapshots, strategy_name="brodel_top_n")


@dataclass
class ScoreRangePosition:
    """Represents a stock position bought when entering a score range."""

    symbol: str
    name: str
    buy_date: datetime
    buy_score: float
    prev_score: float | None
    buy_price: float
    allocated_capital: float
    shares: float
    current_price: float
    current_value: float
    profit_loss: float
    return_pct: float
    status: str = "Aktiv"


@dataclass
class ScoreRangeBacktestResult:
    """Container for score-range entry backtest results."""

    initial_capital: float
    total_current_value: float
    total_profit_loss: float
    total_return_pct: float
    num_positions: int
    win_rate: float
    positions: list[ScoreRangePosition] = field(default_factory=list)
    min_score: float = 70.0
    max_score: float = 80.0
    lookback_days: int = 100
    start_date: datetime | None = None
    end_date: datetime | None = None
    unallocated_cash: float = 0.0

    def to_dataframe(self) -> pd.DataFrame:
        """Export detailed trade and holding list as a pandas DataFrame."""
        if not self.positions:
            return pd.DataFrame()
        rows = []
        for p in self.positions:
            rows.append(
                {
                    "Symbol": p.symbol,
                    "Name": p.name,
                    "Kaufdatum": p.buy_date.strftime("%Y-%m-%d") if p.buy_date else "-",
                    "Kauf-Score": round(p.buy_score, 1),
                    "Vorheriger Score": round(p.prev_score, 1) if p.prev_score is not None else "Neu",
                    "Kaufkurs (€/$)": round(p.buy_price, 2),
                    "Investiert (€)": round(p.allocated_capital, 2),
                    "Stückzahl": round(p.shares, 4),
                    "Aktueller Kurs (€/$)": round(p.current_price, 2),
                    "Aktueller Wert (€)": round(p.current_value, 2),
                    "Gewinn/Verlust (€)": round(p.profit_loss, 2),
                    "Rendite (%)": round(p.return_pct, 2),
                    "Status": p.status,
                }
            )
        return pd.DataFrame(rows)


def run_score_range_backtest(
    snapshots: list[tuple[datetime, list[dict[str, Any]]]] | None = None,
    history_dir: Path = HISTORY_DIR,
    min_score: float = 70.0,
    max_score: float = 80.0,
    lookback_days: int = 100,
    initial_capital: float = 10_000.0,
    entry_mode: str = "fresh_entry",
    one_trade_per_symbol: bool = True,
    price_data: dict[str, pd.DataFrame] | None = None,
    current_date: datetime | None = None,
) -> ScoreRangeBacktestResult:
    """Run an event-driven backtest buying all stocks entering a specific score range.

    Parameters:
    - snapshots: Optional preloaded snapshots. If None, loaded from history_dir.
    - min_score, max_score: Boundaries for score entry (e.g. 70 to 80).
    - lookback_days: Days to look back from current_date (0 = all snapshots).
    - initial_capital: Total capital split evenly across all qualifying stocks.
    - entry_mode:
        * 'fresh_entry': stock was previously outside range or first seen in range.
        * 'climbed_from_below': stock was previously strictly below min_score.
        * 'all_in_range': all stocks appearing in score range during the window.
    - one_trade_per_symbol: Buy each stock once on its earliest entry in the period.
    - price_data: Optional pre-fetched price data dictionary for mocking or testing.
    """
    import re

    if snapshots is None:
        snapshots = load_snapshots(history_dir)

    snapshots = sorted(snapshots, key=lambda s: s[0])

    if not snapshots:
        return ScoreRangeBacktestResult(
            initial_capital=initial_capital,
            total_current_value=initial_capital,
            total_profit_loss=0.0,
            total_return_pct=0.0,
            num_positions=0,
            win_rate=0.0,
            positions=[],
            min_score=min_score,
            max_score=max_score,
            lookback_days=lookback_days,
            unallocated_cash=initial_capital,
        )

    ref_date = current_date or datetime.now()
    if ref_date.tzinfo is not None:
        ref_date = ref_date.replace(tzinfo=None)

    cutoff_dt = datetime.min if lookback_days <= 0 else (ref_date - timedelta(days=lookback_days))

    # Phase 1: Detect all qualifying entry events
    previous_scores: dict[str, float] = {}
    candidates: list[dict[str, Any]] = []
    bought_symbols: set[str] = set()

    for dt, items in snapshots:
        snapshot_in_window = dt >= cutoff_dt
        for item in items:
            sym = item.get("symbol")
            if not sym:
                continue
            score = float(item.get("brodel_score", 0))
            prev = previous_scores.get(sym)
            name = item.get("name") or sym

            if snapshot_in_window and (min_score <= score <= max_score):
                qualifies = False
                if entry_mode == "fresh_entry":
                    if prev is None or not (min_score <= prev <= max_score):
                        qualifies = True
                elif entry_mode == "climbed_from_below":
                    if prev is not None and prev < min_score:
                        qualifies = True
                elif entry_mode == "all_in_range":
                    qualifies = True

                if qualifies:
                    if not one_trade_per_symbol or sym not in bought_symbols:
                        bought_symbols.add(sym)
                        candidates.append(
                            {
                                "symbol": sym,
                                "name": name,
                                "entry_date": dt,
                                "entry_score": score,
                                "prev_score": prev,
                                "signal_items": item.get("signal_items", []),
                            }
                        )

            previous_scores[sym] = score

    if not candidates:
        return ScoreRangeBacktestResult(
            initial_capital=initial_capital,
            total_current_value=initial_capital,
            total_profit_loss=0.0,
            total_return_pct=0.0,
            num_positions=0,
            win_rate=0.0,
            positions=[],
            min_score=min_score,
            max_score=max_score,
            lookback_days=lookback_days,
            start_date=snapshots[0][0],
            end_date=snapshots[-1][0],
            unallocated_cash=initial_capital,
        )

    # Phase 2: Equal allocation across all identified stocks
    num_candidates = len(candidates)
    capital_per_stock = initial_capital / num_candidates

    # Phase 3: Price fetching
    prices: dict[str, pd.DataFrame] = {}
    if price_data is not None:
        prices = price_data
    else:
        unique_syms = list({c["symbol"] for c in candidates})
        min_date = min(c["entry_date"] for c in candidates) - timedelta(days=5)
        try:
            download_df = yf.download(
                unique_syms,
                start=min_date.strftime("%Y-%m-%d"),
                group_by="ticker",
                threads=True,
                progress=False,
            )
            if hasattr(download_df.columns, "levels") and len(unique_syms) > 1:
                for sym in unique_syms:
                    if sym in download_df.columns.levels[0]:
                        prices[sym] = download_df[sym]
            elif not download_df.empty and len(unique_syms) == 1:
                prices[unique_syms[0]] = download_df
        except Exception as e:
            logger.warning(f"Batch download failed: {e}")

        # Fallback for tickers missing in batch
        for sym in unique_syms:
            if sym not in prices or prices[sym].empty:
                try:
                    ticker = yf.Ticker(sym)
                    hist = ticker.history(start=min_date.strftime("%Y-%m-%d"), auto_adjust=True)
                    if not hist.empty and "Close" in hist.columns:
                        prices[sym] = hist
                except Exception as e:
                    logger.debug(f"Einzel-Abruf fehlgeschlagen für {sym}: {e}")

    # Phase 4: Valuation of each position
    positions: list[ScoreRangePosition] = []
    unallocated_cash = 0.0

    for cand in candidates:
        sym = cand["symbol"]
        entry_date = cand["entry_date"]
        hist = prices.get(sym, pd.DataFrame())

        buy_price = _price_on_or_after(hist, entry_date) if not hist.empty else None

        # Fallback to signal_items price mention if history is missing or gap
        if buy_price is None:
            for s_line in cand["signal_items"]:
                m = re.search(r"Kurs\s+([0-9.]+)", str(s_line))
                if m:
                    try:
                        buy_price = float(m.group(1))
                        break
                    except ValueError:
                        pass

        current_price = None
        if not hist.empty and "Close" in hist.columns and not hist["Close"].dropna().empty:
            current_price = float(hist["Close"].dropna().iloc[-1])

        if buy_price and buy_price > 0 and current_price and current_price > 0:
            shares = capital_per_stock / buy_price
            current_value = shares * current_price
            pnl = current_value - capital_per_stock
            ret_pct = ((current_price - buy_price) / buy_price) * 100.0
            status = "Aktiv"
        elif buy_price and buy_price > 0 and (current_price is None or current_price <= 0):
            # Bought, but current price missing
            shares = capital_per_stock / buy_price
            current_price = buy_price
            current_value = capital_per_stock
            pnl = 0.0
            ret_pct = 0.0
            status = "Aktueller Kurs fehlt (Einstandskurs)"
        else:
            # Completely missing price
            shares = 0.0
            buy_price = 0.0
            current_price = 0.0
            current_value = capital_per_stock
            pnl = 0.0
            ret_pct = 0.0
            unallocated_cash += capital_per_stock
            status = "Kurs nicht verfügbar (Barbestand)"

        positions.append(
            ScoreRangePosition(
                symbol=sym,
                name=cand["name"],
                buy_date=entry_date,
                buy_score=cand["entry_score"],
                prev_score=cand["prev_score"],
                buy_price=buy_price,
                allocated_capital=capital_per_stock,
                shares=shares,
                current_price=current_price,
                current_value=current_value,
                profit_loss=pnl,
                return_pct=ret_pct,
                status=status,
            )
        )

    # Sort positions by buy_date
    positions.sort(key=lambda p: p.buy_date)

    total_current_value = sum(p.current_value for p in positions)
    total_profit_loss = total_current_value - initial_capital
    total_return_pct = (total_profit_loss / initial_capital) * 100.0 if initial_capital > 0 else 0.0

    valid_positions = [p for p in positions if p.status == "Aktiv"]
    profitable = [p for p in valid_positions if p.profit_loss > 0]
    win_rate = (len(profitable) / len(valid_positions) * 100.0) if valid_positions else 0.0

    start_date = candidates[0]["entry_date"] if candidates else None
    end_date = snapshots[-1][0] if snapshots else None

    return ScoreRangeBacktestResult(
        initial_capital=initial_capital,
        total_current_value=total_current_value,
        total_profit_loss=total_profit_loss,
        total_return_pct=total_return_pct,
        num_positions=len(positions),
        win_rate=win_rate,
        positions=positions,
        min_score=min_score,
        max_score=max_score,
        lookback_days=lookback_days,
        start_date=start_date,
        end_date=end_date,
        unallocated_cash=unallocated_cash,
    )
