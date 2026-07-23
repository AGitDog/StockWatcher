"""Base strategy interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StrategyResult:
    """Result of evaluating a single signal item against a strategy."""

    strategy_name: str
    setup: str | None = None
    confidence: float = 0.0
    direction: str = "neutral"
    rationale: str = ""
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    position_size_pct: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "setup": self.setup,
            "confidence": self.confidence,
            "direction": self.direction,
            "rationale": self.rationale,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "position_size_pct": self.position_size_pct,
            "metadata": self.metadata,
        }


class Strategy:
    """Abstract base class for all strategies."""

    name: str = "base"

    def evaluate(self, item: dict[str, Any]) -> StrategyResult | None:
        """Evaluate a signal item and return a strategy result or None."""
        raise NotImplementedError

    @staticmethod
    def _get_breakdown(item: dict[str, Any], name: str) -> dict[str, Any]:
        breakdown = item.get("signal_breakdown", {}) or {}
        return breakdown.get(name, {}) or {}

    @staticmethod
    def _current_price(item: dict[str, Any]) -> float | None:
        breakdown = item.get("signal_breakdown", {}) or {}
        pv = breakdown.get("Preis/Volumen", {})
        summary = pv.get("summary", "")
        match = __import__("re").search(r"Kurs\s+([0-9]+\.?[0-9]*)", summary)
        if match:
            return float(match.group(1))
        return None

    @staticmethod
    def _atr_estimate(item: dict[str, Any]) -> float | None:
        """Estimate ATR from price/volume summary if available."""
        breakdown = item.get("signal_breakdown", {}) or {}
        pv = breakdown.get("Preis/Volumen", {})
        summary = pv.get("summary", "")
        match = __import__("re").search(r"Kurs\s+([0-9]+\.?[0-9]*)", summary)
        if match:
            price = float(match.group(1))
            # rough estimate: 2% of price per day
            return price * 0.02
        return None
