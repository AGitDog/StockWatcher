"""Nightly update in region groups (Yahoo blocks a run after ~350 symbols)."""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

import snapshot_store
from stock_agent import (
    RUN_GROUPS,
    merge_group_run,
    run_group,
    save_signal_snapshot,
    select_group_entries,
    snapshot_day,
    snapshot_timestamp,
    symbol_region,
)

MISSING = snapshot_store.MISSING_PRICE_SUMMARY


def _item(symbol, score, missing=False):
    summary = MISSING if missing else "Kurs ueber MA20."
    return {
        "symbol": symbol,
        "brodel_score": score,
        "signal_breakdown": {"Preis/Volumen": {"name": "Preis/Volumen", "score": 0, "summary": summary}},
    }


@pytest.mark.parametrize("symbol,region", [
    ("AAPL", "america"), ("BRK-B", "america"), ("CNQ.TO", "america"), ("^GSPC", "america"),
    ("7203.T", "asia"), ("M&M.NS", "asia"), ("^N225", "asia"),
    ("SAP.DE", "europe"), ("BRBY.L", "europe"), ("MC.PA", "europe"), ("NESN.SW", "europe"), ("^GDAXI", "europe"),
    ("", "america"), (None, "america"),
])
def test_symbol_region(symbol, region):
    assert symbol_region(symbol) == region


def test_run_group_splits_america_stably():
    symbols = [f"SYM{i}" for i in range(400)]
    groups = [run_group(symbol) for symbol in symbols]
    assert set(groups) == {"america-1", "america-2", "america-3"}
    assert 100 < groups.count("america-1") < 170
    assert groups == [run_group(symbol) for symbol in symbols]  # same every run
    assert run_group("SAP.DE") == "europe"


def test_select_group_entries_covers_every_entry_once():
    entries = ["AAPL", "MSFT", "7203.T", "SAP.DE", "BRBY.L", "CNQ.TO", "NVDA"]
    selected = [entry for group in RUN_GROUPS for entry in select_group_entries(entries, group, {})]
    assert sorted(selected) == sorted(entries)
    assert select_group_entries(entries, "all", {}) == entries
    assert select_group_entries(entries, "asia", {}) == ["7203.T"]
    with pytest.raises(ValueError):
        select_group_entries(entries, "mars", {})


def test_snapshot_day_counts_early_utc_runs_to_previous_day():
    assert snapshot_day(datetime(2026, 11, 5, 22, 30, tzinfo=timezone.utc)) == "2026-11-05"
    assert snapshot_day(datetime(2026, 11, 6, 3, 0, tzinfo=timezone.utc)) == "2026-11-05"  # delayed US run
    assert snapshot_day(datetime(2026, 11, 6, 7, 30, tzinfo=timezone.utc)) == "2026-11-05"  # 8 hours late
    assert snapshot_day(datetime(2026, 11, 6, 10, 30, tzinfo=timezone.utc)) == "2026-11-06"
    assert snapshot_timestamp(datetime(2026, 11, 6, 3, 0, tzinfo=timezone.utc)) == "2026-11-05T23:59:59Z"
    assert snapshot_timestamp(datetime(2026, 11, 6, 10, 30, 5, tzinfo=timezone.utc)) == "2026-11-06T10:30:05Z"


def test_merge_same_day_keeps_other_groups_fresh():
    base = {"timestamp": "2026-11-05T08:10:00Z", "items": [_item("7203.T", 40), _item("SAP.DE", 30)]}
    merged = snapshot_store.merge_into_day(base, "2026-11-05", [_item("SAP.DE", 35), _item("AAPL", 50)])
    by_symbol = {item["symbol"]: item for item in merged}
    assert by_symbol["7203.T"]["brodel_score"] == 40 and "stale_from" not in by_symbol["7203.T"]
    assert by_symbol["SAP.DE"]["brodel_score"] == 35
    assert by_symbol["AAPL"]["brodel_score"] == 50


def test_merge_from_previous_day_marks_stale_and_excludes_from_measurement():
    base = {"timestamp": "2026-11-04T22:40:00Z", "items": [_item("AAPL", 50), _item("SAP.DE", 30)]}
    merged = snapshot_store.merge_into_day(base, "2026-11-05", [_item("7203.T", 40)])
    by_symbol = {item["symbol"]: item for item in merged}
    assert by_symbol["AAPL"]["stale_from"] == "2026-11-04"
    assert not snapshot_store.is_fresh_measurement(by_symbol["AAPL"])
    assert snapshot_store.is_fresh_measurement(by_symbol["7203.T"])
    assert [item["symbol"] for item in snapshot_store.fresh_items(merged)] == ["7203.T"]


def test_merge_keeps_old_data_when_new_fetch_failed():
    base = {"timestamp": "2026-11-04T22:40:00Z", "items": [_item("AAPL", 50)]}
    merged = snapshot_store.merge_into_day(base, "2026-11-05", [_item("AAPL", 0, missing=True)])
    assert merged[0]["brodel_score"] == 50 and merged[0]["stale_from"] == "2026-11-04"
    # stale marker keeps the original day when carried again
    again = snapshot_store.merge_into_day({"timestamp": "2026-11-05T22:40:00Z", "items": merged}, "2026-11-06", [])
    assert again[0]["stale_from"] == "2026-11-04"


def test_merge_drops_removed_and_too_old_entries():
    base = {"timestamp": "2026-11-04T22:40:00Z", "items": [_item("AAPL", 50), _item("GONE", 10)]}
    assert [i["symbol"] for i in snapshot_store.merge_into_day(base, "2026-11-05", [], allowed_symbols={"AAPL"})] == ["AAPL"]
    old = {"timestamp": "2026-10-01T22:40:00Z", "items": [_item("AAPL", 50)]}
    assert snapshot_store.merge_into_day(old, "2026-11-05", [_item("7203.T", 40)]) == [_item("7203.T", 40)]
    assert snapshot_store.merge_into_day(None, "2026-11-05", [_item("7203.T", 40)]) == [_item("7203.T", 40)]


def test_four_group_runs_build_one_daily_snapshot(tmp_path):
    runs = [
        (datetime(2026, 11, 5, 10, 35, tzinfo=timezone.utc), [_item("7203.T", 40)]),
        (datetime(2026, 11, 5, 17, 40, tzinfo=timezone.utc), [_item("SAP.DE", 30)]),
        (datetime(2026, 11, 5, 21, 45, tzinfo=timezone.utc), [_item("AAPL", 50)]),
        (datetime(2026, 11, 6, 1, 15, tzinfo=timezone.utc), [_item("MSFT", 45)]),  # delayed past midnight UTC
    ]
    for now, items in runs:
        merged = merge_group_run("wl.txt", items, now=now, directory=str(tmp_path))
        save_signal_snapshot("wl.txt", merged, directory=str(tmp_path), now=now)
    files = snapshot_store.daily_files(tmp_path, "wl")
    assert [path.name for path in files] == ["2026-11-05.json.gz"]
    [snapshot] = snapshot_store.load_history(tmp_path, "wl")
    assert sorted(item["symbol"] for item in snapshot["items"]) == ["7203.T", "AAPL", "MSFT", "SAP.DE"]
    assert all(snapshot_store.is_fresh_measurement(item) for item in snapshot["items"])


@patch("update_signals.os.path.exists", return_value=True)
@patch("builtins.open", new_callable=mock_open, read_data="AAPL\n7203.T\nSAP.DE")
@patch("update_signals.build_symbol_signal_monitor")
@patch("update_signals.save_signal_snapshot", return_value=Path("dummy.json.gz"))
@patch("update_signals.merge_group_run")
def test_update_script_runs_only_its_group_and_merges(mock_merge, mock_save, mock_build, mock_file, mock_exists):
    mock_build.side_effect = lambda entry, mappings: _item(entry, 10)
    mock_merge.side_effect = lambda name, items, allowed_symbols=None: items + [_item("OTHER", 5)]
    from update_signals import main

    main(["--group", "asia"])
    assert [call.args[0] for call in mock_build.call_args_list] == ["7203.T"]
    assert mock_merge.call_args.kwargs["allowed_symbols"] == {"AAPL", "7203.T", "SAP.DE"}
    assert sorted(item["symbol"] for item in mock_save.call_args[0][1]) == ["7203.T", "OTHER"]
