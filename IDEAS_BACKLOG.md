# Ideas Backlog (Parkplatz-Modus)

Dieses Dokument dient der strukturierten Aufnahme spontaner Ideen und Funktionswünsche während laufender Arbeitsphasen gemäß `AGENTS.md`.

---

## Offene Ideen (UNREFINED)

### IDEA-001: Watchlist-Verwaltung aus dem UI entfernen & im Hintergrund verwalten
- **Eingereicht am:** 19.10.2026
- **Status:** `UNREFINED`
- **Kontext / Motivation:** Die App ist nicht mehrbenutzerbezogen. Der Reiter "Watchlist Verwaltung" im Streamlit-UI bläht die Oberfläche unnötig auf.
- **Kernanforderung:**
  - Tab "Watchlist Verwaltung" aus dem Streamlit-Interface (`app.py`) entfernen.
  - Watchlist-Verwaltung vollständig im Hintergrund durchführen (z. B. über zentrale Konfigurations-/Watchlist-Dateien).
  - Neue Indizes (z. B. SOX, NBI) standardmäßig in die Hintergrund-Watchlist integrieren, damit sie automatisch bei jedem Snapshot-Lauf (`daily_job.py` / App-Start) analysiert werden.
