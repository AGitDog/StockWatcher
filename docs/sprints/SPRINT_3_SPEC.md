# Sprint 3 Spezifikation: Automatisierte Tages-Snapshots & UI-Fokus-Bereinigung

**Sprint-Status:** Abgeschlossen / Fertiggestellt (Phase 3: Implementation)  
**Erstellt am:** 19.10.2026  
**Abgeschlossen am:** 19.10.2026  
**Ziel:** Automatisierung der Signal-Snapshots pro Kalendertag (idempotent, bis zu 365 Tage), Entfernung des manuellen Speicher-Buttons und vollständige Bereinigung der Delta-Alerts / Vergleichsfunktionen zu gestern aus dem Signal Monitor.

---

## 1. Scope & Motivation
- Die bisherige Delta-Vergleichsfunktion zu gestern überfrachtet das UI mit Warnungen und Slidern, während der strategische Mehrwert im absoluten Score-Ranking und in der kontinuierlichen Historie für Backtests liegt.
- Das manuelle Speichern von Snapshots führt zu Lücken oder zu versehentlichem Mehrfach-Speichern an einem Tag.
- Lösung: Automatisches Speichern bei jeder Aktualisierung, Ersetzung am gleichen Kalendertag, Erhöhung des Rollierungs-Limits auf 365 Tage und Reduktion des UI auf die wesentlichen Signale.

---

## 2. Detaillierte Task-Liste

### Task 1: Idempotente Tages-Snapshots in `stock_agent.py`
- **Komponente:** `stock_agent.py` (`save_signal_snapshot`, `MAX_SIGNAL_HISTORY_SNAPSHOTS`)
- **Implementierungsdetails:**
  1. `MAX_SIGNAL_HISTORY_SNAPSHOTS = 365`.
  2. In `save_signal_snapshot`:
     - Ermittlung des aktuellen Kalendertags (`YYYY-MM-DD`).
     - Prüfen, ob bereits ein Snapshot mit diesem Datum existiert. Falls ja, diesen Eintrag aktualisieren.
     - Falls nein, neuen Snapshot anhängen.
     - Liste auf maximal 365 Einträge rollieren.
- **Akzeptanzkriterien:**
  - Mehrmaliges Aufrufen von `save_signal_snapshot` am selben Tag erzeugt keinen zusätzlichen Listeneintrag, sondern aktualisiert den Eintrag des Tags.
  - Das Limit von 365 Tagen wird eingehalten.

### Task 2: Signal Monitor Bereinigung & Auto-Snapshot in `app.py`
- **Komponente:** `app.py` (`render_watchlist_signal_monitor`)
- **Implementierungsdetails:**
  1. Automatischer Aufruf von `save_signal_snapshot` unmittelbar nach Berechnung der Signale.
  2. Entfernen des Schwellwert-Sliders `alert_threshold = st.slider(...)`.
  3. Entfernen des manuellen Buttons `st.button("Snapshot speichern")`.
  4. Entfernen des gesamten Abschnitts `st.markdown("**Delta-Alerts seit letztem Snapshot**")` samt Tabelle und Alert-Warnungen.
  5. Anzeige einer dezenten Statuszeile über die Anzahl der gespeicherten Tages-Snapshots für Backtest & ML.
- **Akzeptanzkriterien:**
  - Nach Klick auf *„Signale aktualisieren“* ist der Snapshot sofort persistent auf der Festplatte gespeichert.
  - Kein Delta-Slider oder Delta-Alert-Block mehr im UI.
  - Detail-Analyse, Strategie-Setups und Backtests funktionieren weiterhin einwandfrei.

### Task 3: Automatisierte Tests & Verifikation
- **Komponente:** `tests/test_stock_agent.py`, `tests/test_app_startup.py`
- **Implementierungsdetails:**
  1. Testfall für `save_signal_snapshot`: Verifiziert Idempotenz am gleichen Kalendertag und Snapshot-Aktualisierung.
  2. Vollständige Test-Suite ausführen (`pytest tests/`).
- **Akzeptanzkriterien:**
  - Alle Tests laufen zu 100 % grün durch (0 Fehler, 0 Regressionen).

---

## 3. Gesamte Akzeptanzkriterien für Sprint 3
1. Snapshot-Speicherung erfolgt automatisch bei Datenberechnung ohne manuellen Button.
2. Mehrfaches Aktualisieren am selben Tag aktualisiert den Datensatz des Tags (idempotent, keine Duplikate).
3. Historien-Rollierung ist auf 365 Tage erweitert.
4. Delta-Alerts und Schwellwert-Slider sind vollständig aus dem UI entfernt.
5. Alle 169 Tests laufen erfolgreich durch.

---

## 4. Verifikation & Testergebnisse
- **Automatisierte Tests:** 169 Tests erfolgreich (0 Fehler, 0 Regressionen in `pytest tests/`).
- **Idempotenz:** `test_save_signal_snapshot_idempotent_same_day` bestätigt, dass Mehrfachaufrufe am selben Tag den bestehenden Snapshot aktualisieren.
- **Tagesübergang:** `test_save_signal_snapshot_appends_on_different_day` bestätigt das saubere Fortführen der Historie bei neuem Kalendertag.
- **UI-Bereinigung:** Streamlit startet fehlerfrei; Alert-Slider und Delta-Tabelle sind entfernt; automatischer Snapshot-Trigger aktiv.

