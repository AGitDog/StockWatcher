"""Momentum strategy: strong trend with volume confirmation."""

from __future__ import annotations

from typing import Any

from .base import Strategy, StrategyResult


class MomentumStrategy(Strategy):
    """Long-only momentum strategy.

    Conditions:
    - Price above MA20 and MA50
    - 5-day return >= 5%
    - Volume spike on up-day
    - Positive EPS revisions or strong analyst consensus
    - Relative strength positive
    """

    name = "momentum"

    def evaluate(self, item: dict[str, Any]) -> StrategyResult | None:
        breakdown = item.get("signal_breakdown", {}) or {}
        pv = breakdown.get("Preis/Volumen", {})
        eps = breakdown.get("EPS-Revisionen", {})
        targets = breakdown.get("Kursziele & Konsens", {})
        rs = breakdown.get("Relative Staerke", {})
        tech = breakdown.get("Technische Indikatoren", {})

        pv_summary = pv.get("summary", "")
        tech_summary = tech.get("summary", "")

        checks = {
            "above_ma20": "ueber MA20" in pv_summary and "ja" in pv_summary.split("ueber MA20/MA50")[0] if "ueber MA20/MA50" in pv_summary else False,
            "above_ma50": "ueber MA20/MA50" in pv_summary and "ja/ja" in pv_summary,
            "rally_5d": False,
            "volume_spike": False,
            "positive_eps": eps.get("score", 0) > 0,
            "strong_consensus": targets.get("score", 0) >= 5,
            "relative_strength": rs.get("score", 0) >= 3,
            "macd_bullish": "Bullisch" in tech_summary,
            "not_overbought": "Ueberkauft" not in tech_summary,
        }

        # Parse 5-day return and volume ratio from summary
        import re

        ret_match = re.search(r"5T\s+([\-0-9.]+)%", pv_summary)
        if ret_match:
            ret_5d = float(ret_match.group(1))
            checks["rally_5d"] = ret_5d >= 5.0

        vol_match = re.search(r"Volumen\s+([0-9.]+)x", pv_summary)
        if vol_match:
            vol_ratio = float(vol_match.group(1))
            checks["volume_spike"] = vol_ratio >= 1.5 and "ueber MA20" in pv_summary

        score = sum(checks.values())
        confidence = score / len(checks)

        if confidence < 0.5:
            return None

        entry = self._current_price(item)
        atr = self._atr_estimate(item)
        stop = entry - (atr * 3) if entry and atr else None
        take = entry * 1.15 if entry else None

        rationale_parts = ["Momentum-Setup erkannt:"]
        if checks["above_ma20"] and checks["above_ma50"]:
            rationale_parts.append("Kurs über MA20 und MA50")
        if checks["rally_5d"]:
            rationale_parts.append("5-Tage-Rallye")
        if checks["volume_spike"]:
            rationale_parts.append("Volumen-Spitze bestätigt Trend")
        if checks["positive_eps"]:
            rationale_parts.append("positive EPS-Revisionen")
        if checks["relative_strength"]:
            rationale_parts.append("Outperformance vs. Markt")

        return StrategyResult(
            strategy_name=self.name,
            setup="breakout_momentum",
            confidence=round(confidence, 2),
            direction="long",
            rationale=" | ".join(rationale_parts),
            entry_price=entry,
            stop_loss=stop,
            take_profit=take,
            position_size_pct=round(min(0.05 * confidence, 0.10), 4),
            metadata={"checks": checks, "score": score},
        )
