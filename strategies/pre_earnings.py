"""Pre-earnings momentum strategy."""

from __future__ import annotations

import re
from typing import Any

from .base import Strategy, StrategyResult


class PreEarningsStrategy(Strategy):
    """Long pre-earnings momentum strategy.

    Conditions:
    - Earnings within 7 days
    - Price above MA20
    - Positive EPS revision trend
    - Not already overbought (RSI < 70)
    """

    name = "pre_earnings"

    def evaluate(self, item: dict[str, Any]) -> StrategyResult | None:
        breakdown = item.get("signal_breakdown", {}) or {}
        event = breakdown.get("Event-Druck", {})
        pv = breakdown.get("Preis/Volumen", {})
        eps = breakdown.get("EPS-Revisionen", {})
        tech = breakdown.get("Technische Indikatoren", {})

        event_summary = event.get("summary", "")
        pv_summary = pv.get("summary", "")
        tech_summary = tech.get("summary", "")

        checks = {
            "earnings_near": False,
            "above_ma20": "ueber MA20" in pv_summary and "ja" in pv_summary.split("ueber MA20/MA50")[0] if "ueber MA20/MA50" in pv_summary else False,
            "positive_eps": eps.get("score", 0) > 0,
            "not_overbought": "Ueberkauft" not in tech_summary,
            "trend_intact": "ueber MA50" in pv_summary and "ja/ja" in pv_summary,
        }

        days_match = re.search(r"Naechster Termin in\s+(\d+)\s+Tagen", event_summary)
        if days_match:
            days = int(days_match.group(1))
            checks["earnings_near"] = days <= 7

        score = sum(checks.values())
        confidence = score / len(checks)

        if confidence < 0.5:
            return None

        entry = self._current_price(item)
        atr = self._atr_estimate(item)
        # Tight stop because of event risk
        stop = entry - (atr * 2) if entry and atr else None
        # Sell before or right after earnings
        take = entry * 1.10 if entry else None

        rationale_parts = ["Pre-Earnings-Setup erkannt:"]
        if checks["earnings_near"]:
            rationale_parts.append("Quartalszahlen stehen kurz bevor")
        if checks["positive_eps"]:
            rationale_parts.append("EPS-Revisionen positiv")
        if checks["trend_intact"]:
            rationale_parts.append("Trend intakt")

        return StrategyResult(
            strategy_name=self.name,
            setup="pre_earnings_run",
            confidence=round(confidence, 2),
            direction="long",
            rationale=" | ".join(rationale_parts),
            entry_price=entry,
            stop_loss=stop,
            take_profit=take,
            position_size_pct=round(min(0.03 * confidence, 0.06), 4),
            metadata={"checks": checks, "score": score, "days_to_earnings": days if 'days' in dir() else None},
        )
