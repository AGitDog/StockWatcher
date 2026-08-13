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
    load_signal_snapshot_history,
    build_signal_delta_report,
)

DEFAULT_WATCHLIST_NAME = "meine_watchlist.txt"
WATCHLIST_PATH = os.path.join("watchlists", DEFAULT_WATCHLIST_NAME)
MAPPINGS_PATH = "stock_mappings.txt"
MAX_WORKERS = 4
PER_SYMBOL_TIMEOUT = 90  # seconds

def main():
    print(f"Starte täglichen Job für {DEFAULT_WATCHLIST_NAME}...", flush=True)
    job_start = time.time()

    if not os.path.exists(WATCHLIST_PATH):
        print(f"FEHLER: Watchlist {WATCHLIST_PATH} nicht gefunden.", flush=True)
        sys.exit(1)
        
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        watchlist_text = f.read()

    mapping_text = ""
    if os.path.exists(MAPPINGS_PATH):
        with open(MAPPINGS_PATH, "r", encoding="utf-8") as f:
            mapping_text = f.read()

    entries = parse_watchlist_text(watchlist_text)
    symbol_mappings = parse_symbol_mappings(mapping_text)

    if not entries:
        print("Watchlist ist leer oder enthält keine gültigen Einträge.", flush=True)
        sys.exit(0)

    print(f"{len(entries)} Einträge gefunden. Berechne Signale mit {MAX_WORKERS} Threads...", flush=True)
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
                print(f"[{completed}/{len(entries)}] Fehler bei {entry}: {e}", flush=True)

    print(f"Signalberechnung abgeschlossen in {time.time() - job_start:.1f}s ({len(raw_results)}/{len(entries)} erfolgreich).", flush=True)

    if not raw_results:
        print("FEHLER: Keine Ergebnisse berechnet (Datenabruf fehlgeschlagen).", flush=True)
        sys.exit(1)

    print("Berechne Sektor- und Peer-Kontext...", flush=True)
    enriched_results = add_watchlist_peer_context(raw_results)
    
    # Sort results
    sorted_results = sorted(enriched_results, key=lambda x: x.get("brodel_score", 0), reverse=True)

    # Save snapshot
    snapshot_path = save_signal_snapshot(DEFAULT_WATCHLIST_NAME, sorted_results)
    print(f"Snapshot erfolgreich gespeichert unter: {snapshot_path}", flush=True)

    # Check for alerts based on previous history
    history = load_signal_snapshot_history(DEFAULT_WATCHLIST_NAME)
    # history has the new snapshot at the end, so previous is at -2
    if len(history) > 1:
        previous_snapshot = history[-2]
        delta_items = build_signal_delta_report(sorted_results, previous_snapshot)
        
        print("\n--- DELTA ALERTS ---", flush=True)
        for item in delta_items:
            # Report items that have changed significantly
            if item["score_delta"] >= 10 or item["change_type"] == "Neu":
                print(f"ALERT: {item['symbol']} | {item['change_type']} | Score: {item['previous_score']} -> {item['current_score']} (Delta {item['score_delta']})", flush=True)

    print("Job abgeschlossen.", flush=True)

if __name__ == "__main__":
    main()
