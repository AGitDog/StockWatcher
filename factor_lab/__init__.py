"""Wahrheitsmaschine: point-in-time factor research with honest, after-tax evaluation.

Every factor here is a pure function of prices known on the signal date, so it can be
reconstructed for any historical day. That makes a 15-20 year backtest possible,
unlike the snapshot-based Brodel-Score whose inputs (analyst targets, insider data,
news) are only available as of today.
"""

from .backtest import BacktestConfig, FactorBacktestResult, run_factor_backtest
from .evaluation import (
    deflated_sharpe_ratio,
    forward_returns,
    ic_summary,
    quantile_returns,
    rank_ic_series,
    snapshot_score_ic,
    walk_forward_weights,
)
from .factors import DEFAULT_FACTOR_WEIGHTS, composite_score, compute_factor_panel, month_end_dates
from .report import build_truth_report

__all__ = [
    "BacktestConfig",
    "FactorBacktestResult",
    "run_factor_backtest",
    "deflated_sharpe_ratio",
    "forward_returns",
    "ic_summary",
    "quantile_returns",
    "rank_ic_series",
    "snapshot_score_ic",
    "walk_forward_weights",
    "DEFAULT_FACTOR_WEIGHTS",
    "composite_score",
    "compute_factor_panel",
    "month_end_dates",
    "build_truth_report",
]
