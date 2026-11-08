"""Brodel 3.0: rank blocks per region, quality and valuation within sector, no macro influence."""
import pytest

from brodel_v3 import BRODEL_V3_WEIGHTS, compute_brodel_v3
from stock_agent import momentum_12_1


def _factors(value, **extra):
    return {
        "profit_margin": value, "return_on_equity": value, "debt_equity": 100 - value, "forward_pe": 100 - value,
        "fcf_yield": value, "momentum_12_1": value, "eps_up_ratio": value, "share_change": -value,
        "insider_buy_usd": None, **extra,
    }


def _item(symbol, value, sector="Tech", **extra):
    return {"symbol": symbol, "sector": sector, "factors_v3": _factors(value, **extra)}


def test_weights_sum_to_hundred():
    assert sum(BRODEL_V3_WEIGHTS.values()) == 100


def test_best_stock_scores_highest_and_range_is_0_to_100():
    items = [_item(f"S{i}", float(i)) for i in range(1, 21)]
    result = compute_brodel_v3(items)
    scores = [item["brodel_score_v3"] for item in result]
    assert scores == sorted(scores)
    assert scores[-1] == pytest.approx(100.0)
    assert 0 < scores[0] < 15
    assert result[-1]["signal_breakdown_v3"]["Qualitaet"] == 25
    assert result[-1]["signal_breakdown_v3"]["Insider"] is None  # no data outside the US
    assert "brodel_score_v3" not in items[0]  # input stays unchanged


def test_regions_are_ranked_separately():
    us = [_item(f"U{i}", float(i)) for i in range(1, 11)]
    europe = [_item(f"E{i}.DE", float(i) + 0.5) for i in range(1, 11)]
    by_symbol = {item["symbol"]: item["brodel_score_v3"] for item in compute_brodel_v3(us + europe)}
    assert by_symbol["U10"] == by_symbol["E10.DE"]


def test_quality_is_compared_within_the_sector():
    banks = [_item(f"B{i}", float(i), sector="Banks", debt_equity=900.0 + i) for i in range(1, 11)]
    tech = [_item(f"T{i}", float(i) * 5, sector="Tech") for i in range(1, 11)]
    by_symbol = {i["symbol"]: i["signal_breakdown_v3"]["Bewertung"] for i in compute_brodel_v3(banks + tech)}
    assert by_symbol["B10"] == by_symbol["T10"]


def test_small_sector_falls_back_to_region():
    items = [_item(f"S{i}", float(i)) for i in range(1, 21)] + [_item("LONE", 21.0, sector="Rare")]
    by_symbol = {i["symbol"]: i for i in compute_brodel_v3(items)}
    assert by_symbol["LONE"]["signal_breakdown_v3"]["Qualitaet"] == 25


def test_insider_buy_is_a_bonus_and_no_buy_is_neutral():
    items = [_item(f"S{i}", 5.0, insider_buy_usd=0.0) for i in range(8)]
    items += [_item("SMALL", 5.0, insider_buy_usd=5000.0), _item("BIG", 5.0, insider_buy_usd=250000.0)]
    result = {i["symbol"]: i["signal_breakdown_v3"]["Insider"] for i in compute_brodel_v3(items)}
    assert (result["S0"], result["SMALL"], result["BIG"]) == (5.0, 7.5, 10.0)


def test_loss_makers_rank_last_on_valuation():
    items = [_item(f"S{i}", 50.0, forward_pe=10.0 + i) for i in range(9)] + [_item("LOSS", 50.0, forward_pe=-5.0)]
    result = {i["symbol"]: i["signal_breakdown_v3"]["Bewertung"] for i in compute_brodel_v3(items)}
    assert result["LOSS"] == min(result.values())


def test_too_few_blocks_get_no_score():
    thin = {"symbol": "THIN", "sector": "Tech", "factors_v3": {"momentum_12_1": 0.5, "eps_up_ratio": 0.5}}
    assert "brodel_score_v3" not in compute_brodel_v3([thin] + [_item(f"S{i}", float(i)) for i in range(10)])[0]


def test_items_without_factors_or_prices_stay_out():
    from snapshot_store import MISSING_PRICE_SUMMARY

    missing = _item("MISS", 99.0)
    missing["signal_breakdown"] = {"Preis/Volumen": {"summary": MISSING_PRICE_SUMMARY}}
    items = [{"symbol": "OLD", "brodel_score": 5, "brodel_score_v3": 77}, missing] + [_item(f"S{i}", float(i)) for i in range(10)]
    result = compute_brodel_v3(items)
    assert "brodel_score_v3" not in result[0] and "brodel_score_v3" not in result[1]


def test_momentum_skips_the_last_month():
    import pandas as pd

    close = [100.0] * 229 + [150.0] + [10.0] * 21  # crash in the last month does not count
    assert momentum_12_1(pd.DataFrame({"Close": close})) == pytest.approx(0.5)
    assert momentum_12_1(pd.DataFrame({"Close": [100.0] * 150})) is None


def test_insider_value_counts_only_recent_purchases():
    import pandas as pd

    from stock_agent import insider_buy_value

    now = pd.Timestamp.now()
    frame = pd.DataFrame({
        "Text": ["Purchase at price 64.18 per share.", "Sale at price 10 per share.",
                 "Stock Award(Grant) at price 0.00 per share.", "Purchase at price 5 per share.", ""],
        "Value": [641800, 900000, 0, 50000, None],
        "Start Date": [now - pd.Timedelta(days=10), now, now, now - pd.Timedelta(days=200), now],
    })
    assert insider_buy_value(frame) == 641800
    assert insider_buy_value(frame.iloc[0:0]) == 0.0
    assert insider_buy_value(None) is None


def test_biotech_index_uses_last_trading_day_on_weekends():
    from unittest.mock import MagicMock, patch

    import stock_agent

    def post(url, data, headers, timeout):
        response = MagicMock()
        rows = [{"Symbol": "ABCL", "Name": "AbCellera"}] if data["tradeDate"] == "2026-11-06" else []
        response.json.return_value = {"aaData": rows}
        return response

    class Saturday(stock_agent.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 7, 3, 0)

    stock_agent.load_index_constituents.cache_clear()
    try:
        with patch.object(stock_agent.requests, "post", side_effect=post), patch.object(stock_agent, "datetime", Saturday):
            assert stock_agent.load_index_constituents("NASDAQ Biotechnology Index") == ["ABCL"]
    finally:
        stock_agent.load_index_constituents.cache_clear()  # other tests must not see this list


def test_implausible_share_count_jump_gets_no_buyback_points():
    from unittest.mock import MagicMock

    import pandas as pd

    import stock_agent

    days = pd.date_range(end=pd.Timestamp.now().normalize(), periods=420, freq="D")
    shares = pd.Series([132e6] * 300 + [1300e6] * 120, index=days)
    ticker = MagicMock()
    ticker.get_shares_full.return_value = shares
    result = stock_agent._summarize_share_buyback(ticker, False)
    assert result["score"] == 0 and "share_change" not in result and "unplausibel" in result["summary"]
    ticker.get_shares_full.return_value = pd.Series([100e6] * 300 + [96e6] * 120, index=days)
    assert stock_agent._summarize_share_buyback(ticker, False)["share_change"] == pytest.approx(-0.04)


def test_workflow_runs_only_on_weekdays():
    from pathlib import Path
    import re

    content = (Path(__file__).resolve().parent.parent / ".github/workflows/update_signals.yml").read_text(encoding="utf-8")
    crons = re.findall(r"cron: '([^']+)'", content)
    assert crons and all(cron.endswith("* * 1-5") for cron in crons)


def test_finnhub_brake_allows_55_calls_per_minute():
    import finnhub_cache

    now = [0.0]
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    finnhub_cache._call_times.clear()
    try:
        for _ in range(55):
            finnhub_cache.wait_for_rate_limit(clock=lambda: now[0], sleep=sleep)
        assert slept == []
        finnhub_cache.wait_for_rate_limit(clock=lambda: now[0], sleep=sleep)
        assert len(slept) == 1 and now[0] >= 60
    finally:
        finnhub_cache._call_times.clear()
