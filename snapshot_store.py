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

# Summary written by the Preis/Volumen component when Yahoo returned (almost) no price history.
# On some nights Yahoo blocked most requests; those entries then carried a score of 0 for every
# component. They are no measurement and must not enter charts, the Pruefstand or ML training.
MISSING_PRICE_SUMMARY = "Nicht genug Kursdaten fuer Preis/Volumen-Signal."


def item_has_price_data(item: Any) -> bool:
    """False for entries whose data fetch failed (flag ``data_missing`` or no price history)."""
    if not isinstance(item, dict) or item.get("data_missing"):
        return False
    component = (item.get("signal_breakdown") or {}).get("Preis/Volumen")
    return not (isinstance(component, dict) and component.get("summary") == MISSING_PRICE_SUMMARY)


def is_fresh_measurement(item: Any) -> bool:
    """Price data present and computed for this snapshot's day (not carried over from an earlier day)."""
    return item_has_price_data(item) and not item.get("stale_from")


def fresh_items(items: Any) -> list[dict[str, Any]]:
    return [item for item in items or [] if is_fresh_measurement(item)]


def merge_into_day(
    base_snapshot: dict[str, Any] | None,
    day: str,
    new_items: list[dict[str, Any]],
    allowed_symbols: set[str] | None = None,
    max_carry_days: int = 7,
) -> list[dict[str, Any]]:
    """Combine one group run with the latest stored snapshot into the full list of ``day``.

    The nightly update runs per region (Asia, Europe, two US parts). Entries of the other groups
    come from the latest snapshot: from the same day they are fresh, from an earlier day (at most
    ``max_carry_days`` old) they are marked ``stale_from`` and kept only for display. A new entry
    without price data never replaces an old entry that has it.
    """
    result: dict[str, dict[str, Any]] = {}
    base_day = _day_of(base_snapshot) if isinstance(base_snapshot, dict) else ""
    carry = bool(base_day) and (
        base_day == day
        or 0 < (_to_date(day) - _to_date(base_day)).days <= max_carry_days
    )
    if carry:
        for item in base_snapshot.get("items", []) or []:
            symbol = str(item.get("symbol") or "") if isinstance(item, dict) else ""
            if not symbol or (allowed_symbols is not None and symbol not in allowed_symbols):
                continue
            if base_day != day and not item.get("stale_from"):
                item = {**item, "stale_from": base_day}
            result[symbol] = item
    for item in new_items:
        symbol = str(item.get("symbol") or "")
        old = result.get(symbol)
        if old is None or item_has_price_data(item) or not item_has_price_data(old):
            result[symbol] = item
    return list(result.values())


def _to_date(day: str):
    from datetime import date

    return date.fromisoformat(day[:10])


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


def _day_of(snapshot: dict[str, Any] | None) -> str:
    if not isinstance(snapshot, dict):
        return ""
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


def fill_missing_from_same_day(directory: str | Path, key: str, snapshot: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Replace entries without price data by the same symbol's valid entry of an earlier run that day.

    Two workflows write the same daily file; a later run hit by Yahoo blocks must not wipe out
    the good data of the earlier one. Returns the merged snapshot and the number of filled entries.
    """
    day = _day_of(snapshot)
    path = Path(directory) / key / f"{day}{DAILY_SUFFIX}"
    if not day or not path.exists():
        return snapshot, 0
    earlier = {
        str(item.get("symbol")): item
        for stored in read_snapshot_file(path)
        for item in stored.get("items", []) or []
        if isinstance(item, dict) and item.get("symbol") and item_has_price_data(item)
    }
    filled = 0
    items = []
    for item in snapshot.get("items", []) or []:
        if isinstance(item, dict) and not item_has_price_data(item) and str(item.get("symbol")) in earlier:
            items.append(earlier[str(item.get("symbol"))])
            filled += 1
        else:
            items.append(item)
    return {**snapshot, "items": items}, filled


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
