"""Nightly signal update, run per region group.

    python update_signals.py --group asia|europe|america-1|america-2|all

Yahoo blocks a run after roughly 350 symbols, so the watchlist is split into four groups that
each run after their exchanges closed. A group run merges its results with the other groups'
latest entries into one daily snapshot. ``all`` computes the whole list at once (manual use).
"""
import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from stock_agent import (
    RUN_GROUPS,
    parse_watchlist_text,
    parse_symbol_mappings,
    build_symbol_signal_monitor,
    add_watchlist_peer_context,
    entry_symbol,
    merge_group_run,
    primary_score,
    retry_missing_price_items,
    rotate_entries,
    save_signal_snapshot,
    select_group_entries,
    DEFAULT_MAPPING_FILE,
    DEFAULT_WATCHLIST_DIR
)

MAX_WORKERS = 4
PER_SYMBOL_TIMEOUT = 90  # seconds


def run_update(group: str = "all"):
    watchlist_name = "meine_watchlist.txt"
    watchlist_path = os.path.join(DEFAULT_WATCHLIST_DIR, watchlist_name)

    if not os.path.exists(watchlist_path):
        print(f"Watchlist file not found: {watchlist_path}", flush=True)
        sys.exit(1)

    with open(watchlist_path, "r", encoding="utf-8") as f:
        watchlist_text = f.read()

    mapping_text = ""
    if os.path.exists(DEFAULT_MAPPING_FILE):
        with open(DEFAULT_MAPPING_FILE, "r", encoding="utf-8") as f:
            mapping_text = f.read()

    all_entries = parse_watchlist_text(watchlist_text)
    symbol_mappings = parse_symbol_mappings(mapping_text)

    if not all_entries:
        print("No valid entries found in watchlist.", flush=True)
        sys.exit(0)

    entries = rotate_entries(select_group_entries(all_entries, group, symbol_mappings))
    print(f"Group {group}: {len(entries)} of {len(all_entries)} entries, {MAX_WORKERS} threads...", flush=True)
    if not entries:
        print("No entries in this group.", flush=True)
        sys.exit(0)

    job_start = time.time()
    raw_results = []
    completed = 0

    def _fetch_symbol(entry):
        return build_symbol_signal_monitor(entry, symbol_mappings)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_fetch_symbol, entry): entry
            for entry in entries
        }
        for future in as_completed(futures):
            entry = futures[future]
            completed += 1
            try:
                item = future.result(timeout=PER_SYMBOL_TIMEOUT)
                raw_results.append(item)
                print(f"[{completed}/{len(entries)}] OK: {entry}", flush=True)
            except Exception as e:
                print(f"[{completed}/{len(entries)}] Error for {entry}: {e}", flush=True)

    print(f"Signal calculation done in {time.time() - job_start:.1f}s ({len(raw_results)}/{len(entries)} successful).", flush=True)

    if not raw_results:
        print("ERROR: No results calculated (data fetch failed).", flush=True)
        sys.exit(1)

    raw_results, retried, recovered = retry_missing_price_items(raw_results, symbol_mappings)
    if retried:
        print(f"Retry: {recovered}/{retried} Titel ohne Kursdaten nachgeladen.", flush=True)
    without_data = sum(1 for item in raw_results if item.get("data_missing"))
    print(f"Ohne Kursdaten: {without_data}/{len(raw_results)}", flush=True)

    if group != "all":
        allowed = {entry_symbol(entry, symbol_mappings) for entry in all_entries}
        raw_results = merge_group_run(watchlist_name, raw_results, allowed_symbols=allowed)
        print(f"Merged with the other groups: {len(raw_results)} entries in today's snapshot.", flush=True)

    print("Applying peer context...", flush=True)
    enriched_results = add_watchlist_peer_context(raw_results)
    sorted_results = sorted(enriched_results, key=primary_score, reverse=True)

    print("Saving snapshot...", flush=True)
    snapshot_path = save_signal_snapshot(watchlist_name, sorted_results)

    print(f"Successfully saved snapshot to {snapshot_path}", flush=True)
    print("Update complete.", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Nightly signal update per region group.")
    parser.add_argument("--group", default="all", choices=("all",) + RUN_GROUPS)
    args = parser.parse_args(argv)
    run_update(args.group)


if __name__ == "__main__":
    main()
