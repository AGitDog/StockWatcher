import os
import sys

from stock_agent import (
    parse_watchlist_text,
    parse_symbol_mappings,
    build_symbol_signal_monitor,
    add_watchlist_peer_context,
    save_signal_snapshot,
    DEFAULT_MAPPING_FILE,
    DEFAULT_WATCHLIST_DIR
)

def run_update():
    watchlist_name = "meine_watchlist.txt"
    watchlist_path = os.path.join(DEFAULT_WATCHLIST_DIR, watchlist_name)
    
    if not os.path.exists(watchlist_path):
        print(f"Watchlist file not found: {watchlist_path}")
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
        print("No valid entries found in watchlist.")
        sys.exit(0)
        
    print(f"Starting update for {len(entries)} entries...")
    raw_results = []
    
    for i, entry in enumerate(entries):
        print(f"[{i+1}/{len(entries)}] Fetching signals for {entry}...")
        try:
            item = build_symbol_signal_monitor(entry, symbol_mappings)
            raw_results.append(item)
        except Exception as e:
            print(f"Error fetching signals for {entry}: {e}")
            
    print("Applying peer context...")
    enriched_results = add_watchlist_peer_context(raw_results)
    sorted_results = sorted(enriched_results, key=lambda x: x.get("brodel_score", 0), reverse=True)
    
    print("Saving snapshot...")
    snapshot_data = save_signal_snapshot(watchlist_name, sorted_results)
    
    print(f"Successfully saved snapshot to {snapshot_data['filepath']}")
    print("Update complete.")

if __name__ == "__main__":
    run_update()
