# Sprint 2 Spezifikation: Hintergrund-Watchlist-Verwaltung & UI-Bereinigung

**Sprint-Status:** Abgeschlossen / Fertiggestellt (Phase 3: Implementation)  
**Erstellt am:** 19.10.2026  
**Abgeschlossen am:** 19.10.2026  
**Ziel:** Vollständige Entfernung des "Watchlist Verwaltung"-Reiters aus der Streamlit-Oberfläche (`app.py`), Etablierung von `watchlists/meine_watchlist.txt` als zentraler Hintergrund-Quelle inklusive der neuen Indizes `SOX`, `NBI` und `Nikkei 225`, sowie Bereinigung verwaister temporärer Upload-Dateien.

---

## 1. Scope & Hintergrund
Die App wird als Single-User-Dashboard betrieben. Die bisherige interaktive Watchlist-Verwaltung mit Upload-Komponenten im UI ist nicht mehr zeitgemäß, bläht die Oberfläche auf und hinterlässt temporäre Dateifragmente. Das Feature vereinfacht die Benutzeroberfläche auf drei Kernreiter und steuert die Watchlist rein im Hintergrund.

---

## 2. Detaillierte Task-Liste

### Task 1: Hintergrund-Watchlist (`watchlists/meine_watchlist.txt`) aktualisieren & Verzeichnis bereinigen
- **Komponente:** `watchlists/meine_watchlist.txt`, Ordner `watchlists/`
- **Implementierungsdetails:**
  1. Ergänzung der neuen Indizes in `watchlists/meine_watchlist.txt` unter `# Alle unterstuetzten Indizes`:
     - `SOX` (PHLX Semiconductor Sector)
     - `NBI` (NASDAQ Biotechnology Index)
     - `Nikkei 225`
  2. Bereinigung verwaister temporärer Upload-Dateien aus `watchlists/`:
     - Löschen von `1832802889664.txt`, `2067778739696.txt`, `2139592820016.txt`, `2370096009280.txt`, `2553904700432.txt`, `2583596769088.txt`, `2857798066992.txt`.
     - Beibehalten sauberer Basis-Listen: `meine_watchlist.txt`, `stock.txt`, `test.txt`.
- **Akzeptanzkriterien:**
  - `meine_watchlist.txt` enthält `SOX`, `NBI` und `Nikkei 225`.
  - Keine temporären Zahlen-Textdateien mehr im Ordner `watchlists/`.

---

### Task 2: UI-Bereinigung in `app.py`
- **Komponente:** `app.py` (`render_stock_agent`, Tabs)
- **Implementierungsdetails:**
  1. Reduktion der Haupt-Tabs von 4 auf 3:
     ```python
     stock_tabs = st.tabs(["Signal Monitor V2", "Backtest & ML", "Hilfe & Methodik"])
     ```
  2. Entfernung nicht mehr benötigter UI-Funktionen:
     - `render_watchlist_source_controls()`
     - `append_indices_to_watchlist()`
  3. Sicherstellung, dass `render_watchlist_signal_monitor` automatisch `DEFAULT_WATCHLIST_NAME = "meine_watchlist.txt"` verwendet, ohne dass die Session-State-Initialisierung nach einem vierten Tab sucht.
- **Akzeptanzkriterien:**
  - Die Streamlit-App startet fehlerfrei und zeigt exakt die 3 Tabs an.
  - Signal Monitor und Backtest greifen weiterhin stabil auf `meine_watchlist.txt` zu.

---

### Task 3: Dokumentation & Hilfe-Bereinigung
- **Komponente:** `README.md`, `render_help_tab` in `app.py`
- **Implementierungsdetails:**
  1. Aktualisierung der Dokumentation in `README.md`:
     - Entfernen veralteter Erläuterungen zur "Watchlist Verwaltung"-Seite.
     - Dokumentation der zentralen Hintergrund-Watchlist `watchlists/meine_watchlist.txt`.
  2. Aktualisierung von `render_help_tab` in `app.py`:
     - Schnellstart-Schritt 1 anpassen (Hinweis auf Konfiguration in `watchlists/meine_watchlist.txt`).
- **Akzeptanzkriterien:**
  - Dokumentation und In-App-Hilfe spiegeln den schlanken 3-Tab-Workflow wider.

---

### Task 4: Automatisierte Tests & Regressionstests
- **Komponente:** `tests/test_app_startup.py`, `tests/`
- **Implementierungsdetails:**
  1. Anpassung / Erweiterung der Smoke-Tests in `tests/test_app_startup.py` zur Überprüfung des 3-Tab-Layouts und der standardmäßigen Hintergrund-Watchlist.
  2. Vollständige Ausführung der Testsuite mit `.venv\Scripts\python.exe -m pytest tests/`.
- **Akzeptanzkriterien:**
  - Alle Tests laufen zu 100 % grün durch (0 Fehler, 0 Regressionen).

---

## 3. Gesamte Akzeptanzkriterien für Sprint 2
1. Streamlit-App besitzt exakt die 3 Tabs `Signal Monitor V2`, `Backtest & ML`, `Hilfe & Methodik`.
2. `watchlists/meine_watchlist.txt` enthält `SOX`, `NBI` und `Nikkei 225`.
3. Verwaiste Upload-Dateien in `watchlists/` sind vollständig bereinigt.
4. Alle automatisierten Tests laufen erfolgreich durch.

---

## 4. Verifikation & Testergebnisse
- **Automatisierte Tests:** 167 Tests erfolgreich (0 Fehler, 0 Regressionen in `pytest tests/`).
- **Layout & Tabs:** `test_render_stock_agent_layout` verifiziert das 3-Tab-Layout.
- **Hintergrund-Watchlist:** `test_default_watchlist_contains_new_indices` bestätigt `SOX`, `NBI` und `Nikkei 225` in `watchlists/meine_watchlist.txt`.
- **Bereinigung:** Alle 7 verwaisten numerischen Upload-Dateien aus `watchlists/` rückstandslos entfernt.

