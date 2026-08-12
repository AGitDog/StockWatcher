import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from stock_agent import (
    parse_watchlist_text,
    parse_symbol_mappings,
    build_symbol_signal_monitor,
    add_watchlist_peer_context,
    save_signal_snapshot,
    DEFAULT_MAPPING_FILE,
    DEFAULT_WATCHLIST_DIR
)

MAX_WORKERS = 4
PER_SYMBOL_TIMEOUT = 90  # seconds

def run_update():
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
            
    entries = parse_watchlist_text(watchlist_text)
    symbol_mappings = parse_symbol_mappings(mapping_text)
    
    if not entries:
        print("No valid entries found in watchlist.", flush=True)
        sys.exit(0)
        
    print(f"Starting update for {len(entries)} entries with {MAX_WORKERS} threads...", flush=True)
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
        print("No results calculated.", flush=True)
        sys.exit(0)
            
    print("Applying peer context...", flush=True)
    enriched_results = add_watchlist_peer_context(raw_results)
    sorted_results = sorted(enriched_results, key=lambda x: x.get("brodel_score", 0), reverse=True)
    
    print("Saving snapshot...", flush=True)
    snapshot_path = save_signal_snapshot(watchlist_name, sorted_results)
    
    print(f"Successfully saved snapshot to {snapshot_path}", flush=True)
    print("Update complete.", flush=True)

if __name__ == "__main__":
    run_update()
