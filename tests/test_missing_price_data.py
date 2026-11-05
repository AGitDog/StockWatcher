"""Entries whose Yahoo fetch failed must not show up as a real score of 0 (Verlaufskurve fiel auf 0)."""
from datetime import datetime

import snapshot_store
from app import breakdown_table_height, build_score_history_frame
from backtest_engine.engine import snapshots_with_datetimes
from stock_agent import build_signal_delta_report, retry_missing_price_items

MISSING = snapshot_store.MISSING_PRICE_SUMMARY


def _item(symbol, score, missing=False):
    summary = MISSING if missing else "Kurs ueber MA20."
    return {
        "symbol": symbol,
        "input_name": symbol,
        "name": symbol,
        "brodel_score": score,
        "signal_items": [summary],
        "signal_breakdown": {"Preis/Volumen": {"name": "Preis/Volumen", "score": 0 if missing else 5, "summary": summary}},
    }


def test_item_has_price_data():
    assert snapshot_store.item_has_price_data(_item("A", 40))
    assert not snapshot_store.item_has_price_data(_item("A", 0, missing=True))
    assert not snapshot_store.item_has_price_data({**_item("A", 40), "data_missing": True})
    assert snapshot_store.item_has_price_data({"symbol": "A", "brodel_score": 3})  # minimal items stay usable
    assert not snapshot_store.item_has_price_data(None)


def test_score_history_skips_failed_fetches():
    history = [
        {"timestamp": "2026-10-19T10:00:00Z", "items": [_item("A", 53)]},
        {"timestamp": "2026-10-20T10:00:00Z", "items": [_item("A", 0, missing=True)]},
        {"timestamp": "2026-10-21T10:00:00Z", "items": [_item("A", 50)]},
    ]
    frame = build_score_history_frame(history)
    assert list(frame["brodel_score"]) == [53, 50]


def test_evaluations_skip_failed_fetches():
    history = [{"timestamp": "2026-10-20T10:00:00Z", "items": [_item("A", 40), _item("B", 0, missing=True)]}]
    [(_, items)] = snapshots_with_datetimes(history, datetime(2026, 1, 1))
    assert [item["symbol"] for item in items] == ["A"]


def test_delta_report_ignores_failed_fetch_on_either_day():
    previous = {"items": [_item("A", 50), _item("B", 0, missing=True)]}
    current = [_item("A", 0, missing=True), _item("B", 30)]
    assert build_signal_delta_report(current, previous) == []


def test_same_day_run_keeps_good_data(tmp_path):
    snapshot_store.write_daily_snapshot(tmp_path, "wl", {"timestamp": "2026-11-04T04:00:00Z", "items": [_item("A", 50), _item("B", 20)]})
    later = {"timestamp": "2026-11-04T13:00:00Z", "items": [_item("A", 0, missing=True), _item("B", 25), _item("C", 0, missing=True)]}
    merged, filled = snapshot_store.fill_missing_from_same_day(tmp_path, "wl", later)
    assert filled == 1
    assert [item["brodel_score"] for item in merged["items"]] == [50, 25, 0]
    assert merged["timestamp"] == later["timestamp"]


def test_same_day_merge_without_earlier_file(tmp_path):
    snap = {"timestamp": "2026-11-04T13:00:00Z", "items": [_item("A", 0, missing=True)]}
    assert snapshot_store.fill_missing_from_same_day(tmp_path, "wl", snap) == (snap, 0)


def test_retry_recovers_and_flags_remaining():
    results = [_item("A", 40), _item("B", 0, missing=True), _item("C", 0, missing=True)]
    calls = []

    def builder(entry, mappings):
        calls.append(entry)
        return _item(entry, 33) if entry == "B" else _item(entry, 0, missing=True)

    output, retried, recovered = retry_missing_price_items(results, builder=builder, sleep=lambda s: None)
    assert (retried, recovered) == (2, 1)
    assert sorted(calls) == ["B", "C"]
    assert output[0] is results[0]
    assert output[1]["brodel_score"] == 33
    assert output[2]["data_missing"] is True


def test_retry_skips_when_nothing_missing():
    results = [_item("A", 40)]
    slept = []
    output, retried, recovered = retry_missing_price_items(results, builder=None, sleep=slept.append)
    assert (output, retried, recovered, slept) == (results, 0, 0, [])


def test_retry_respects_time_budget():
    results = [_item("B", 0, missing=True)]
    times = iter([0.0, 1000.0])
    output, retried, recovered = retry_missing_price_items(
        results, builder=lambda e, m: _item(e, 30), sleep=lambda s: None, time_budget_seconds=10, clock=lambda: next(times)
    )
    assert (retried, recovered) == (1, 0)
    assert output[0]["data_missing"] is True


def test_rotate_entries_moves_start_each_run():
    from stock_agent import rotate_entries

    entries = [f"S{i}" for i in range(1000)]
    morning = rotate_entries(entries, datetime(2026, 11, 5, 4), stride=350)
    afternoon = rotate_entries(entries, datetime(2026, 11, 5, 14), stride=350)
    next_day = rotate_entries(entries, datetime(2026, 11, 6, 4), stride=350)
    assert sorted(morning) == sorted(entries)
    starts = [entries.index(order[0]) for order in (morning, afternoon, next_day)]
    assert (starts[1] - starts[0]) % 1000 == 350
    assert (starts[2] - starts[1]) % 1000 == 350
    assert rotate_entries([]) == []


def test_breakdown_table_shows_all_rows():
    assert breakdown_table_height(11) >= 35 * 12


def test_trailing_row_without_close_is_ignored():
    """Yahoo appends today's row without a close before the open; it must not become the latest price."""
    import numpy as np
    import pandas as pd

    from stock_agent import _summarize_price_volume, clean_price_history

    index = pd.date_range("2026-08-01", periods=61, freq="B")
    close = list(np.linspace(100, 130, 60)) + [np.nan]
    history = pd.DataFrame({"Close": close, "Volume": [1000] * 60 + [1700]}, index=index)
    assert len(clean_price_history(history)) == 60
    result = _summarize_price_volume(history)
    assert "nan" not in result["summary"]
    assert result["summary"].startswith("Kurs 130.00")
    assert result["score"] == 10  # above MA20 and MA50 (capped at the 1.0 maximum)
    assert clean_price_history(None) is None


def test_relative_strength_ignores_rows_without_close():
    import numpy as np
    import pandas as pd

    import stock_agent

    index = pd.date_range("2026-09-01", periods=41, freq="B")
    stock = pd.DataFrame({"Close": list(np.linspace(100, 110, 40)) + [np.nan], "Volume": [1000] * 41}, index=index)
    bench = pd.DataFrame({"Close": [100.0] * 21 + [np.nan], "Volume": [1] * 22}, index=index[-22:])
    stock_agent._benchmark_cache.clear()
    try:
        with patch_benchmark(bench):
            result = stock_agent._summarize_relative_strength(stock, "DHL.DE")
    finally:
        stock_agent._benchmark_cache.clear()
    assert "nan" not in result["summary"]
    assert "^GDAXI 0.0%" in result["summary"]


def patch_benchmark(frame):
    from unittest.mock import patch

    import stock_agent

    return patch.object(stock_agent, "_safe_dataframe", return_value=frame)
