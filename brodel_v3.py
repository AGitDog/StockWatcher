"""Brodel 3.0: six building blocks, ranked per day instead of fixed point rules.

Every block is a percentile rank (0-1) within the stock's region; quality and valuation within
region and sector. The weights are deliberately close to equal: they are a justified starting
point, not a fitted result (500 searched weightings only overfitted, see the weight search).

Why ranks: a missing data source or a market phase cannot shift the whole score, and stocks of
different run groups stay comparable. The macro regime is not part of the score.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

import snapshot_store
from stock_agent import symbol_region

BRODEL_V3_WEIGHTS = {
    "Qualitaet": 25,
    "Momentum": 20,
    "EPS-Revisionen": 20,
    "Bewertung": 15,
    "Aktienrueckkauf": 10,
    "Insider": 10,
}
MIN_BLOCKS = 4  # fewer known blocks: no score (ETFs, indices, stocks with thin data)
MIN_GROUP_SIZE = 8  # smaller sector groups are ranked within the whole region
INSIDER_LARGE_BUY_USD = 100_000


def _ranks(frame: pd.DataFrame, column: str, ascending: bool = True, groups: list[str] | None = None) -> pd.Series:
    """Percentile rank of a column, within ``groups`` when the group is large enough."""
    region_rank = frame.groupby("region")[column].rank(pct=True, ascending=ascending)
    if not groups:
        return region_rank
    grouped = frame.groupby(groups)[column]
    group_rank = grouped.rank(pct=True, ascending=ascending)
    return group_rank.where(grouped.transform("count") >= MIN_GROUP_SIZE, region_rank)


def _earnings_yield(forward_pe: Any) -> float | None:
    """Earnings per euro paid. A loss (P/E <= 0) ranks below every profitable company."""
    if forward_pe is None:
        return None
    return 1 / forward_pe if forward_pe > 0 else -1.0


def _insider_rank(value: Any) -> float | None:
    """Purchases are a bonus. No purchase is neutral, because most stocks have none."""
    if value is None:
        return None
    if value >= INSIDER_LARGE_BUY_USD:
        return 1.0
    return 0.75 if value > 0 else 0.5


def compute_brodel_v3(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return copies of the items with ``brodel_score_v3`` (0-100) and ``signal_breakdown_v3``."""
    rows = []
    for index, item in enumerate(items):
        factors = item.get("factors_v3")
        if not isinstance(factors, dict) or not snapshot_store.item_has_price_data(item):
            continue
        rows.append({
            "index": index,
            "region": symbol_region(item.get("symbol")),
            "sector": str(item.get("sector") or "Unbekannt"),
            "margin": factors.get("profit_margin"),
            "roe": factors.get("return_on_equity"),
            "debt": factors.get("debt_equity"),
            "earnings_yield": _earnings_yield(factors.get("forward_pe")),
            "fcf_yield": factors.get("fcf_yield"),
            "momentum": factors.get("momentum_12_1"),
            "eps": factors.get("eps_up_ratio"),
            "shares": factors.get("share_change"),
            "insider": _insider_rank(factors.get("insider_buy_usd")),
        })
    result = [{k: v for k, v in item.items() if k not in ("brodel_score_v3", "signal_breakdown_v3")} for item in items]
    if not rows:
        return result

    frame = pd.DataFrame(rows).set_index("index")
    numeric = [c for c in frame.columns if c not in ("region", "sector")]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
    by_sector = ["region", "sector"]
    blocks = pd.DataFrame(index=frame.index)
    blocks["Qualitaet"] = pd.concat([
        _ranks(frame, "margin", groups=by_sector),
        _ranks(frame, "roe", groups=by_sector),
        _ranks(frame, "debt", ascending=False, groups=by_sector),
    ], axis=1).mean(axis=1)
    blocks["Bewertung"] = pd.concat([
        _ranks(frame, "earnings_yield", groups=by_sector),
        _ranks(frame, "fcf_yield", groups=by_sector),
    ], axis=1).mean(axis=1)
    blocks["Momentum"] = _ranks(frame, "momentum")
    blocks["EPS-Revisionen"] = _ranks(frame, "eps")
    blocks["Aktienrueckkauf"] = _ranks(frame, "shares", ascending=False)  # fewer shares is better
    blocks["Insider"] = frame["insider"]

    weights = pd.Series(BRODEL_V3_WEIGHTS)[list(blocks.columns)]
    known_weight = blocks.notna().mul(weights).sum(axis=1)
    score = blocks.mul(weights).sum(axis=1).div(known_weight) * 100
    known_blocks = blocks.notna().sum(axis=1)

    for index in frame.index:
        if known_blocks[index] < MIN_BLOCKS:
            continue
        result[index]["brodel_score_v3"] = round(float(score[index]), 1)
        result[index]["signal_breakdown_v3"] = {
            name: None if pd.isna(blocks.loc[index, name]) else round(float(blocks.loc[index, name]) * BRODEL_V3_WEIGHTS[name], 1)
            for name in BRODEL_V3_WEIGHTS
        }
    return result
