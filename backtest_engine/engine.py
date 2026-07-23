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
