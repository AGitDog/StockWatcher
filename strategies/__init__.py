"""Strategy definitions for the Stock Monitor app.

Each strategy evaluates a signal item and returns a classification dict with:
- setup: one of the strategy names or None
- confidence: 0-1 score
- direction: "long", "short", or "neutral"
- rationale: human-readable explanation
- entry_price, stop_loss, take_profit: optional price levels
- position_size_pct: suggested portfolio allocation
"""

from .base import StrategyResult, Strategy
from .momentum import MomentumStrategy
from .mean_reversion import MeanReversionStrategy
from .pre_earnings import PreEarningsStrategy
from .short_squeeze import ShortSqueezeStrategy
from .registry import StrategyRegistry, build_strategy_signals

__all__ = [
    "StrategyResult",
    "Strategy",
    "MomentumStrategy",
    "MeanReversionStrategy",
    "PreEarningsStrategy",
    "ShortSqueezeStrategy",
    "StrategyRegistry",
    "build_strategy_signals",
]
