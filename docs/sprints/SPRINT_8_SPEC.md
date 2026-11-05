# Sprint 8 Spezifikation: Brodel 2.0 – neu gewichteter Score auf der Einstiegsseite

**Sprint-Status:** Abgeschlossen / Fertiggestellt (Phase 3: Implementation)
**Erstellt am:** 02.11.2026
**Abgeschlossen am:** 02.11.2026
**Freigabe:** Im Chat freigegeben („OK dann setze diese neuen Brodel 2.0 direkt auf die Einstiegsseite und den Brodel Score 1.0 ganz nach hinten“). Weitere Datenquellen (EDGAR-Insiderkäufe, kleinere Firmen) ausdrücklich noch nicht umsetzen.
**Ziel:** Die App rankt nach einem neu gewichteten Brodel-Score 2.0. Brodel 1.0 läuft unverändert mit, damit der Prüfstand beide Versionen vergleichen kann.

## Testergebnisse & Verifikation
- **264 Tests erfolgreich bestanden** (0 Fehler, Ausgangsbasis 231). Stand nach Nachtrag Task 5.
- Neue Testsuiten: `tests/test_brodel_v2.py` (21 Tests), `tests/test_snapshot_store.py` (12 Tests).
- Manuelle Verifikation per Streamlit-AppTest mit den echten Snapshots: Signal Monitor (1376 Titel, 29 Snapshot-Tage), Brodel-Prüfstand und Hilfe rendern ohne Fehler.

---

## 1. Scope & Hintergrund
Grundlage ist die Auswertung der gespeicherten Snapshots (Aug. bis Nov. 2026) und ein Nachbau der Kursregeln über 20 Jahre (S&P 500, 2005–2026).

| Baustein | Befund |
|---|---|
| Fundamentale Bewertung | in den Snapshots stärkster Baustein (Rank-IC +0,165 bei 21 Tagen) |
| Kursziele & Konsens | falsche Richtung auf 3 Monate (IC −0,121 bei 63 Tagen) |
| Preis/Volumen, Technik | über 20 Jahre ohne Nutzen, auf Wochensicht leicht negativ (IC −0,013, t −3,0) |
| EPS-Revisionen | leicht negativ; die Nettoregel gab großen Firmen fast immer volle Punkte |
| Aktienrückkauf (neu) | 2017–2026 rund +1,8 % pro Jahr für das oberste Zehntel, t 1,0 bis 1,4: richtige Richtung, noch nicht signifikant |

Rückwirkend auf den Snapshots (ohne Rückkauf-Daten) sortiert Brodel 2.0 besser als 1.0:

| Horizont | Brodel 1.0 | Brodel 2.0 |
|---|---|---|
| 5 Tage | +0,070 | +0,073 |
| 21 Tage | +0,072 | +0,093 |
| 63 Tage | +0,062 | +0,091 |

**Einschränkung:** Die Gewichte wurden an denselben Snapshots ausgesucht (In-Sample, nur zwei Marktphasen). Der Vorsprung ist daher kein Beweis. 1.0 bleibt zur laufenden Kontrolle erhalten.

---

## 2. Task-Liste

### Task 1: Brodel 2.0 im Kern (`stock_agent.py`)
- Neue Konstanten `BRODEL_V1_MAX_POINTS` und `BRODEL_V2_MAX_POINTS` (Summe 100 bzw. 90).
- Gewichte 2.0: Fundamentale Bewertung 15 (×1,5), Kursziele 5 (×⅓), Preis/Volumen 5 (×½), Technik 5 (×½), Aktienrückkauf 5 (neu), übrige Bausteine unverändert.
- `eps_revision_ratio_points`: Anteil der Hochstufungen bei mindestens 2 Revisionen. Ab 80 % +15, ab 65 % +10, ab 50 % +5, höchstens 35 % −5.
- `_summarize_eps_revisions` liefert zusätzlich `up` und `down`. Für alte Snapshots werden die Zahlen aus dem Summary-Text gelesen.
- `_summarize_share_buyback` nutzt `get_shares_full` und vergleicht den Median der letzten 30 Tage mit dem Median vor 330 bis 400 Tagen. Bei mindestens 3 % weniger Aktien +5, bei mindestens 1 % weniger +3, bei mindestens 5 % mehr −2. ETFs und fehlende Daten ergeben 0.
- `compute_brodel_v2_breakdown` rechnet die 1.0-Punkte um. `build_symbol_signal_monitor` speichert zusätzlich `brodel_score_v2` (gleiches Makro-Overlay, Grenzen −30 bis 100) und `signal_breakdown_v2`. `brodel_score` und `signal_breakdown` bleiben unverändert, damit ML-Training und alte Backtests weiter funktionieren.
- `ensure_brodel_v2` rechnet 2.0 für ältere Snapshot-Einträge nach (ohne Rückkauf, ohne Makro, Markierung `brodel_v2_estimated`). Einträge ohne Einzelpunkte bleiben unverändert.
- `primary_score` (2.0, sonst 1.0) steuert Sortierung, Sektor-Rang, Peer-Vergleich und Delta-Alerts. `daily_job.py` und `update_signals.py` sortieren ebenfalls danach.

### Task 2: Einstiegsseite (`app.py`, `components/interactive_table/index.html`)
- Haupttabelle: Spalte „Brodel 2.0“ an der Stelle des alten Scores und Standardsortierung. Die Einzelspalten zeigen 2.0-Punkte, die Spalte „Rückkauf“ ist neu, „Brodel 1.0“ steht als letzte Spalte.
- Neue Hilfsfunktionen `prepare_signal_items`, `build_signal_table_rows` und `build_breakdown_rows`.
- Detailansicht: Kopfzeile mit 2.0 und klein 1.0. Die Komponententabelle zeigt Punkte und Maxima beider Versionen, der Score-Verlauf zeichnet beide Linien. Bei nachgerechneten Werten erscheint ein Hinweis.

### Task 3: Brodel-Prüfstand misst beide Versionen
- `render_brodel_check_section` ergänzt alte Snapshots um 2.0 und misst `brodel_score_v2` und `brodel_score` mit `snapshot_score_ic` auf denselben Tagen. Das Ergebnis erscheint als Tabelle (`build_brodel_check_rows`).

### Task 4: Hilfe korrigiert und erweitert
- Neuer Abschnitt „Brodel 2.0: was ist neu und warum“ mit Gewichtstabelle, Umrechnungsbeispiel und ehrlichem In-Sample-Hinweis.
- „Die 11 Bausteine“: Jede Regel ist jetzt aus dem Code abgeschrieben, mit Maxima für 1.0 und 2.0. Korrigierte Abweichungen:
  - Preis/Volumen: +5 über MA20, +6 über MA50, +4 bei mindestens +7 % in 5 Tagen, −3 bei mindestens −7 %, Volumen ab 1,5-fach. Die alte Hilfe nannte +3/+2, −5 ab −10 % und 200 %.
  - EPS, Kursziele, News, Relative Stärke, Event-Druck und Short Interest entsprechend dem Code beschrieben.
- Neuer Baustein Aktienrückkauf erklärt.

---

### Task 5 (Nachtrag, Bugfix 03.11.2026): Snapshot-Speicherung pro Tag
- **Fehler:** Der nächtliche Lauf „Update Stock Signals“ vom 03.11.2026 scheiterte beim Push. Die Datei `signal_history/meine_watchlist.json` hatte das GitHub-Limit von 100 MB pro Datei erreicht. Sie wuchs um rund 4 MB pro Snapshot, und die 2.0-Daten machten jeden Snapshot zusätzlich größer.
- **Lösung:** Neues Modul `snapshot_store.py`. Jeder Tag wird als eigene gzip-komprimierte Datei `signal_history/<watchlist>/<YYYY-MM-DD>.json.gz` gespeichert, im selben Listenformat wie bisher. Ein zweiter Lauf am selben Tag ersetzt die Tagesdatei. Dateien früherer Tage werden nie wieder geschrieben, daher wächst die Git-Historie nur um rund 90 KB pro Tag.
- Die alte Einzeldatei wird beim ersten Speichern automatisch in Tagesdateien aufgeteilt und entfernt. 29 Einträge ergaben 23 Tage (106 MB → 2,5 MB). Gelesen werden weiterhin alte Einzeldateien und Tagesdateien.
- Angepasste Leser: `load_signal_snapshot_history`, `backtest_engine.engine.load_snapshots` (neu: `snapshots_with_datetimes`), `factor_lab.data.load_sector_map` und die Quellenauswahl im Event-Backtest.
- `signal_breakdown_v2` speichert für umgerechnete Bausteine nur Name und Punkte. Die Texte stehen bereits im 1.0-Breakdown.

### Task 6 (Nachtrag, Bugfix 05.11.2026): Verlaufskurve fällt auf 0, Yahoo blockiert
- **Fehler:** Der Score-Verlauf vieler Aktien sprang immer wieder auf 0. Yahoo blockiert einen Lauf nach rund 350 Titeln. Für alle weiteren Titel kamen keine Daten, also weder Kurse noch Fundamentaldaten, EPS, Insider oder Sektor. Gespeichert wurde trotzdem ein Score, nur aus News und Terminen. Seit dem 19.10. betraf das jeden Tag rund 75 % der Watchlist, und zwar immer denselben hinteren Teil der Liste.
- **Lösung:**
  - `snapshot_store.item_has_price_data` erkennt Einträge ohne Kursdaten am Preis/Volumen-Text oder an `data_missing`. Score-Verlauf, Prüfstand, Backtests und ML-Training (`snapshots_with_datetimes`) sowie Delta-Alerts lassen diese Einträge aus. Das gilt rückwirkend auch für alte Snapshots.
  - `rotate_entries` sorgt dafür, dass jeder Lauf an einer anderen Stelle der Watchlist beginnt. Die Startstelle rückt pro Lauf um 350 Einträge weiter, jeweils morgens und nachmittags.
  - `fill_missing_from_same_day`: Ein späterer Lauf am selben Tag ersetzt gute Daten des früheren Laufs nicht mehr durch leere.
  - `retry_missing_price_items`: Titel ohne Kursdaten werden nach 30 s Pause mit 2 Threads noch einmal geladen, höchstens 8 Minuten lang. Danach erhalten sie `data_missing`.
- Detailansicht: Die Tabelle „Signal-Breakdown“ nutzt die volle Breite und ist so hoch, dass alle Zeilen ohne Scrollen sichtbar sind.
- **Offen:** Rund 10 Yahoo-Abfragen pro Titel sind für 1376 Titel zu viele. Die eigentliche Lösung wäre, Kurse gesammelt zu laden und langsame Daten wie Fundamentaldaten seltener abzurufen.

## 3. Bewusst nicht umgesetzt
- Insider-Clusterkäufe aus SEC EDGAR (mehrere Insider kaufen kurz hintereinander) und eine stärkere Gewichtung solcher Doppelkäufe.
- Erweiterung auf kleinere Firmen, bei denen die Drift nach Quartalszahlen laut Forschung noch wirkt.
- Laut Freigabe zunächst nur besprechen.
