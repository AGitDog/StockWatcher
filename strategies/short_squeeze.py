"""Short squeeze strategy."""

from __future__ import annotations

import re
from typing import Any

from .base import Strategy, StrategyResult


class ShortSqueezeStrategy(Strategy):
    """Long short-squeeze strategy.

    Conditions:
    - Short interest >= 10% of float
    - Price above MA50 (shorters under pressure)
    - Volume spike
    - Recent price strength
    """

    name = "short_squeeze"

    def evaluate(self, item: dict[str, Any]) -> StrategyResult | None:
        breakdown = item.get("signal_breakdown", {}) or {}
        short = breakdown.get("Short Interest", {})
        pv = breakdown.get("Preis/Volumen", {})
        tech = breakdown.get("Technische Indikatoren", {})

        short_summary = short.get("summary", "")
        pv_summary = pv.get("summary", "")
        tech_summary = tech.get("summary", "")

        checks = {
            "high_short": False,
            "above_ma50": "ueber MA20/MA50" in pv_summary and "ja/ja" in pv_summary,
            "volume_spike": False,
            "recent_strength": False,
            "not_overbought": "Ueberkauft" not in tech_summary,
        }

        short_match = re.search(r"Short-Float:\s+([0-9.]+)%", short_summary)
        if short_match:
            short_pct = float(short_match.group(1))
            checks["high_short"] = short_pct >= 10.0

        vol_match = re.search(r"Volumen\s+([0-9.]+)x", pv_summary)
        if vol_match:
            vol_ratio = float(vol_match.group(1))
            checks["volume_spike"] = vol_ratio >= 1.3

        ret_match = re.search(r"5T\s+([\-0-9.]+)%", pv_summary)
        if ret_match:
            ret_5d = float(ret_match.group(1))
            checks["recent_strength"] = ret_5d >= 3.0

        score = sum(checks.values())
        confidence = score / len(checks)

        if confidence < 0.5:
            return None

        entry = self._current_price(item)
        atr = self._atr_estimate(item)
        stop = entry - (atr * 2.5) if entry and atr else None
        take = entry * 1.20 if entry else None

        rationale_parts = ["Short-Squeeze-Setup erkannt:"]
        if checks["high_short"]:
            rationale_parts.append("hohe Leerverkaufsquote")
        if checks["above_ma50"]:
            rationale_parts.append("Kurs über MA50")
        if checks["volume_spike"]:
            rationale_parts.append("Volumen-Spitze")
        if checks["recent_strength"]:
            rationale_parts.append("kürzliche Kursstärke")

        return StrategyResult(
            strategy_name=self.name,
            setup="short_squeeze",
            confidence=round(confidence, 2),
            direction="long",
            rationale=" | ".join(rationale_parts),
            entry_price=entry,
            stop_loss=stop,
            take_profit=take,
            position_size_pct=round(min(0.04 * confidence, 0.08), 4),
            metadata={"checks": checks, "score": score},
        )
