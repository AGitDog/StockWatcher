"""Registry for all strategies."""

from __future__ import annotations

from typing import Any

from .base import Strategy, StrategyResult
from .momentum import MomentumStrategy
from .mean_reversion import MeanReversionStrategy
from .pre_earnings import PreEarningsStrategy
from .short_squeeze import ShortSqueezeStrategy


class StrategyRegistry:
    """Holds and runs all registered strategies."""

    def __init__(self) -> None:
        self._strategies: list[Strategy] = [
            MomentumStrategy(),
            MeanReversionStrategy(),
            PreEarningsStrategy(),
            ShortSqueezeStrategy(),
        ]

    def register(self, strategy: Strategy) -> None:
        self._strategies.append(strategy)

    def evaluate(self, item: dict[str, Any]) -> list[StrategyResult]:
        """Run all strategies against a signal item and return non-null results."""
        results: list[StrategyResult] = []
        for strategy in self._strategies:
            try:
                result = strategy.evaluate(item)
                if result is not None:
                    results.append(result)
            except Exception:
                # Strategy evaluation should never crash the pipeline
                continue
        return sorted(results, key=lambda r: r.confidence, reverse=True)

    def best_signal(self, item: dict[str, Any]) -> StrategyResult | None:
        """Return the highest-confidence strategy result for an item."""
        results = self.evaluate(item)
        return results[0] if results else None


def build_strategy_signals(signal_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enrich signal items with strategy results."""
    registry = StrategyRegistry()
    enriched: list[dict[str, Any]] = []
    for item in signal_items:
        new_item = dict(item)
        results = registry.evaluate(new_item)
        new_item["strategy_signals"] = [r.to_dict() for r in results]
        best = registry.best_signal(new_item)
        new_item["best_strategy"] = best.to_dict() if best else None
        enriched.append(new_item)
    return enriched
