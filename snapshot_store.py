"""Storage for signal snapshots: one gzip-compressed JSON file per watchlist and day.

Layout::

    signal_history/<watchlist>/<YYYY-MM-DD>.json.gz   one snapshot per day (current format)
    signal_history/<watchlist>.json                    legacy: list of all snapshots in one file

The legacy single file grew by several MB per day and hit GitHub's 100 MB file limit
(November 2026). Daily files stay small, are never rewritten after their day and keep the
git history lean. Every file holds a JSON list of snapshot dicts
(``{"timestamp": ..., "items": [...]}``), so all readers share one format.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

DAILY_SUFFIX = ".json.gz"


def read_snapshot_file(path: Path) -> list[dict[str, Any]]:
    """Read a legacy ``.json`` or a daily ``.json.gz`` file. Broken files yield an empty list."""
    try:
        if path.name.endswith(".gz"):
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                data = json.load(handle)
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, EOFError):
        return []
    if isinstance(data, dict) and "items" in data:
        data = [data]
    return [entry for entry in data if isinstance(entry, dict)] if isinstance(data, list) else []


def _day_of(snapshot: dict[str, Any]) -> str:
    timestamp = snapshot.get("timestamp")
    return timestamp[:10] if isinstance(timestamp, str) and len(timestamp) >= 10 else ""


def _merge_by_day(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the last snapshot per calendar day, sorted by timestamp. Undated entries are kept."""
    by_day: dict[str, dict[str, Any]] = {}
    undated: list[dict[str, Any]] = []
    for snapshot in snapshots:
        day = _day_of(snapshot)
        if day:
            by_day[day] = snapshot
        else:
            undated.append(snapshot)
    return undated + sorted(by_day.values(), key=lambda snap: str(snap.get("timestamp", "")))


def daily_files(directory: str | Path, key: str) -> list[Path]:
    folder = Path(directory) / key
    return sorted(folder.glob(f"*{DAILY_SUFFIX}")) if folder.is_dir() else []


def load_history(directory: str | Path, key: str) -> list[dict[str, Any]]:
    """All snapshots of one watchlist: legacy file plus daily files, one per day, oldest first."""
    snapshots: list[dict[str, Any]] = []
    legacy = Path(directory) / f"{key}.json"
    if legacy.exists():
        snapshots.extend(read_snapshot_file(legacy))
    for path in daily_files(directory, key):
        snapshots.extend(read_snapshot_file(path))
    return _merge_by_day(snapshots)


def write_daily_snapshot(directory: str | Path, key: str, snapshot: dict[str, Any]) -> Path:
    """Write (or replace) the snapshot file of the snapshot's day."""
    day = _day_of(snapshot) or "undated"
    folder = Path(directory) / key
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}{DAILY_SUFFIX}"
    payload = json.dumps([snapshot], ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    temp = path.with_name(path.name + ".tmp")
    # mtime=0 keeps the bytes identical for identical content, so git sees no spurious change
    with open(temp, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as handle:
        handle.write(payload)
    temp.replace(path)
    return path


def migrate_legacy_file(directory: str | Path, key: str) -> int:
    """Split a legacy single-file history into daily files and remove it. Returns the number of days written."""
    legacy = Path(directory) / f"{key}.json"
    if not legacy.exists():
        return 0
    existing_days = {path.name.removesuffix(DAILY_SUFFIX) for path in daily_files(directory, key)}
    written = 0
    for snapshot in _merge_by_day(read_snapshot_file(legacy)):
        day = _day_of(snapshot)
        if day and day not in existing_days:  # a daily file is never older than the legacy entry
            write_daily_snapshot(directory, key, snapshot)
            written += 1
    legacy.unlink()
    return written


def prune_daily_files(directory: str | Path, key: str, max_history: int) -> None:
    if max_history <= 0:
        return
    files = daily_files(directory, key)
    for path in files[: max(0, len(files) - max_history)]:
        path.unlink()


def list_sources(directory: str | Path) -> list[str]:
    """Watchlist keys that have snapshots (daily folders and legacy files)."""
    root = Path(directory)
    if not root.is_dir():
        return []
    keys = {path.stem for path in root.glob("*.json")}
    keys.update(path.name for path in root.iterdir() if path.is_dir() and any(path.glob(f"*{DAILY_SUFFIX}")))
    return sorted(keys)


def load_all(directory: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Snapshots of every watchlist in the directory, keyed by watchlist."""
    return {key: load_history(directory, key) for key in list_sources(directory)}
