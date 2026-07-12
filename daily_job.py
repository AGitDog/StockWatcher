import os
import sys

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

def main():
    print(f"Starte täglichen Job für {DEFAULT_WATCHLIST_NAME}...")

    if not os.path.exists(WATCHLIST_PATH):
        print(f"FEHLER: Watchlist {WATCHLIST_PATH} nicht gefunden.")
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
        print("Watchlist ist leer oder enthält keine gültigen Einträge.")
        sys.exit(0)

    print(f"{len(entries)} Einträge gefunden. Berechne Signale...")
    raw_results = []
    for i, entry in enumerate(entries):
        print(f"[{i+1}/{len(entries)}] Lade Daten für {entry}...")
        item = build_symbol_signal_monitor(entry, symbol_mappings)
        raw_results.append(item)

    print("Berechne Sektor- und Peer-Kontext...")
    enriched_results = add_watchlist_peer_context(raw_results)
    
    # Sort results
    sorted_results = sorted(enriched_results, key=lambda x: x.get("brodel_score", 0), reverse=True)

    # Save snapshot
    snapshot_path = save_signal_snapshot(DEFAULT_WATCHLIST_NAME, sorted_results)
    print(f"Snapshot erfolgreich gespeichert unter: {snapshot_path}")

    # Check for alerts based on previous history
    history = load_signal_snapshot_history(DEFAULT_WATCHLIST_NAME)
    # history has the new snapshot at the end, so previous is at -2
    if len(history) > 1:
        previous_snapshot = history[-2]
        delta_items = build_signal_delta_report(sorted_results, previous_snapshot)
        
        print("\n--- DELTA ALERTS ---")
        for item in delta_items:
            # Report items that have changed significantly
            if item["score_delta"] >= 10 or item["change_type"] == "Neu":
                print(f"ALERT: {item['symbol']} | {item['change_type']} | Score: {item['previous_score']} -> {item['current_score']} (Delta {item['score_delta']})")

    print("Job abgeschlossen.")

if __name__ == "__main__":
    main()
