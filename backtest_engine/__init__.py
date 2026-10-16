"""Backtest engine for strategy validation."""

from .engine import (
    BacktestEngine,
    BacktestResult,
    ScoreRangeBacktestResult,
    ScoreRangePosition,
    run_backtest_on_snapshots,
    run_score_range_backtest,
)
from .portfolio import Portfolio, Trade

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "Portfolio",
    "ScoreRangeBacktestResult",
    "ScoreRangePosition",
    "Trade",
    "run_backtest_on_snapshots",
    "run_score_range_backtest",
]
