"""Tests for the daily, compressed snapshot storage (fix for GitHub's 100 MB file limit)."""
import gzip
import json
from pathlib import Path
from unittest.mock import patch

import snapshot_store
from backtest_engine.engine import load_snapshots
from stock_agent import load_signal_snapshot_history, save_signal_snapshot


def _legacy(tmp_path: Path, key: str, snapshots: list[dict]) -> Path:
    path = tmp_path / f"{key}.json"
    path.write_text(json.dumps(snapshots, indent=2), encoding="utf-8")
    return path


def test_write_daily_snapshot_is_gzip_json_list(tmp_path):
    snap = {"timestamp": "2026-11-03T05:00:00Z", "items": [{"symbol": "AAPL"}]}
    path = snapshot_store.write_daily_snapshot(tmp_path, "wl", snap)
    assert path == tmp_path / "wl" / "2026-11-03.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        assert json.load(handle) == [snap]


def test_write_is_deterministic_for_identical_content(tmp_path):
    snap = {"timestamp": "2026-11-03T05:00:00Z", "items": [{"symbol": "AAPL"}]}
    first = snapshot_store.write_daily_snapshot(tmp_path, "wl", snap).read_bytes()
    second = snapshot_store.write_daily_snapshot(tmp_path, "wl", snap).read_bytes()
    assert first == second


def test_load_history_merges_legacy_and_daily_files(tmp_path):
    _legacy(tmp_path, "wl", [
        {"timestamp": "2026-10-01T10:00:00Z", "items": [{"symbol": "A", "brodel_score": 1}]},
        {"timestamp": "2026-10-02T10:00:00Z", "items": [{"symbol": "A", "brodel_score": 2}]},
    ])
    snapshot_store.write_daily_snapshot(tmp_path, "wl", {"timestamp": "2026-10-02T20:00:00Z", "items": [{"symbol": "A", "brodel_score": 3}]})
    snapshot_store.write_daily_snapshot(tmp_path, "wl", {"timestamp": "2026-10-03T10:00:00Z", "items": [{"symbol": "A", "brodel_score": 4}]})
    history = snapshot_store.load_history(tmp_path, "wl")
    assert [snap["items"][0]["brodel_score"] for snap in history] == [1, 3, 4]  # newer run of the same day wins


def test_migrate_legacy_file_splits_into_days_and_removes_it(tmp_path):
    legacy = _legacy(tmp_path, "wl", [
        {"timestamp": "2026-10-01T10:00:00Z", "items": []},
        {"timestamp": "2026-10-01T22:00:00Z", "items": [{"symbol": "late"}]},
        {"timestamp": "2026-10-05T10:00:00Z", "items": []},
    ])
    assert snapshot_store.migrate_legacy_file(tmp_path, "wl") == 2
    assert not legacy.exists()
    assert [p.name for p in snapshot_store.daily_files(tmp_path, "wl")] == ["2026-10-01.json.gz", "2026-10-05.json.gz"]
    assert snapshot_store.load_history(tmp_path, "wl")[0]["items"] == [{"symbol": "late"}]
    assert snapshot_store.migrate_legacy_file(tmp_path, "wl") == 0


def test_migration_keeps_existing_daily_file(tmp_path):
    snapshot_store.write_daily_snapshot(tmp_path, "wl", {"timestamp": "2026-10-01T23:00:00Z", "items": [{"symbol": "daily"}]})
    _legacy(tmp_path, "wl", [{"timestamp": "2026-10-01T10:00:00Z", "items": [{"symbol": "legacy"}]}])
    snapshot_store.migrate_legacy_file(tmp_path, "wl")
    assert snapshot_store.load_history(tmp_path, "wl")[0]["items"] == [{"symbol": "daily"}]


def test_broken_files_are_skipped(tmp_path):
    (tmp_path / "wl").mkdir()
    (tmp_path / "wl" / "2026-10-01.json.gz").write_bytes(b"not gzip")
    (tmp_path / "other.json").write_text("{broken", encoding="utf-8")
    assert snapshot_store.load_history(tmp_path, "wl") == []
    assert snapshot_store.load_history(tmp_path, "other") == []


def test_prune_keeps_newest_days(tmp_path):
    for day in ("01", "02", "03"):
        snapshot_store.write_daily_snapshot(tmp_path, "wl", {"timestamp": f"2026-10-{day}T10:00:00Z", "items": []})
    snapshot_store.prune_daily_files(tmp_path, "wl", 2)
    assert [p.name for p in snapshot_store.daily_files(tmp_path, "wl")] == ["2026-10-02.json.gz", "2026-10-03.json.gz"]


def test_list_sources_and_load_all(tmp_path):
    _legacy(tmp_path, "old", [{"timestamp": "2026-10-01T10:00:00Z", "items": []}])
    snapshot_store.write_daily_snapshot(tmp_path, "new", {"timestamp": "2026-10-02T10:00:00Z", "items": []})
    (tmp_path / "empty_dir").mkdir()
    assert snapshot_store.list_sources(tmp_path) == ["new", "old"]
    assert set(snapshot_store.load_all(tmp_path)) == {"new", "old"}


def test_save_signal_snapshot_migrates_and_writes_daily_file(tmp_path):
    _legacy(tmp_path, "watchlist", [{"timestamp": "2026-10-01T12:00:00Z", "items": [{"symbol": "OLD"}]}])
    path = save_signal_snapshot("watchlist.txt", [{"symbol": "NEW"}], directory=str(tmp_path))
    assert path.parent == tmp_path / "watchlist"
    assert not (tmp_path / "watchlist.json").exists()
    history = load_signal_snapshot_history("watchlist.txt", directory=str(tmp_path))
    assert [snap["items"][0]["symbol"] for snap in history] == ["OLD", "NEW"]


def test_backtest_engine_reads_daily_files(tmp_path):
    snapshot_store.write_daily_snapshot(tmp_path, "wl", {"timestamp": "2026-10-02T10:00:00Z", "items": [{"symbol": "B"}]})
    _legacy(tmp_path, "legacy", [{"timestamp": "2026-10-01T10:00:00Z", "items": [{"symbol": "A"}]}])
    snapshots = load_snapshots(tmp_path)
    assert [items[0]["symbol"] for _, items in snapshots] == ["A", "B"]


def test_daily_snapshot_of_real_size_stays_far_below_github_limit(tmp_path):
    items = [
        {
            "symbol": f"S{i}",
            "name": f"Company {i}",
            "brodel_score": i % 50,
            "brodel_score_v2": i % 40,
            "signal_items": [f"Signal text number {j} for company {i}" for j in range(10)],
            "signal_breakdown": {f"C{j}": {"name": f"C{j}", "score": j, "summary": f"Detail {j} {i}"} for j in range(10)},
        }
        for i in range(1500)
    ]
    path = snapshot_store.write_daily_snapshot(tmp_path, "wl", {"timestamp": "2026-11-03T05:00:00Z", "items": items})
    assert path.stat().st_size < 5_000_000


def test_v2_breakdown_does_not_duplicate_summaries():
    from stock_agent import compute_brodel_v2_breakdown

    v2 = compute_brodel_v2_breakdown({"Preis/Volumen": {"name": "Preis/Volumen", "score": 10, "summary": "long text"}})
    assert v2["Preis/Volumen"] == {"name": "Preis/Volumen", "score": 5}
