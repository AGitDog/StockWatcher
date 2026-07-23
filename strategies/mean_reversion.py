"""Mean reversion strategy: oversold bounce potential."""

from __future__ import annotations

import re
from typing import Any

from .base import Strategy, StrategyResult


class MeanReversionStrategy(Strategy):
    """Long mean-reversion strategy.

    Conditions:
    - RSI < 35 (oversold)
    - Price near or below lower Bollinger Band
    - Recent crash (5-day return <= -7%)
    - Positive or neutral news sentiment
    - No heavy selling pressure (short interest not bearish)
    """

    name = "mean_reversion"

    def evaluate(self, item: dict[str, Any]) -> StrategyResult | None:
        breakdown = item.get("signal_breakdown", {}) or {}
        tech = breakdown.get("Technische Indikatoren", {})
        pv = breakdown.get("Preis/Volumen", {})
        news = breakdown.get("News-Sentiment", {})
        short = breakdown.get("Short Interest", {})

        tech_summary = tech.get("summary", "")
        pv_summary = pv.get("summary", "")

        checks = {
            "oversold_rsi": False,
            "bollinger_lower": "Unteres Band" in tech_summary,
            "recent_crash": False,
            "not_bearish_news": news.get("score", 0) >= -2,
            "not_bearish_short": "baerisch" not in short.get("summary", "").lower(),
            "macd_turning": "Bullisch" in tech_summary or "MACD" in tech_summary,
        }

        rsi_match = re.search(r"RSI:\s+([0-9.]+)", tech_summary)
        if rsi_match:
            rsi = float(rsi_match.group(1))
            checks["oversold_rsi"] = rsi < 35

        ret_match = re.search(r"5T\s+([\-0-9.]+)%", pv_summary)
        if ret_match:
            ret_5d = float(ret_match.group(1))
            checks["recent_crash"] = ret_5d <= -7.0

        score = sum(checks.values())
        confidence = score / len(checks)

        if confidence < 0.45:
            return None

        entry = self._current_price(item)
        atr = self._atr_estimate(item)
        stop = entry - (atr * 2) if entry and atr else None
        take = entry + (atr * 4) if entry and atr else None

        rationale_parts = ["Mean-Reversion-Setup erkannt:"]
        if checks["oversold_rsi"]:
            rationale_parts.append("RSI überverkauft")
        if checks["bollinger_lower"]:
            rationale_parts.append("Kurs am unteren Bollinger Band")
        if checks["recent_crash"]:
            rationale_parts.append("kürzlicher Kursrücksetzer")
        if checks["not_bearish_news"]:
            rationale_parts.append("News-Sentiment nicht negativ")

        return StrategyResult(
            strategy_name=self.name,
            setup="oversold_bounce",
            confidence=round(confidence, 2),
            direction="long",
            rationale=" | ".join(rationale_parts),
            entry_price=entry,
            stop_loss=stop,
            take_profit=take,
            position_size_pct=round(min(0.04 * confidence, 0.08), 4),
            metadata={"checks": checks, "score": score},
        )
