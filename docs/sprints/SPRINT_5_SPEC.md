# Sprint 5 Spezifikation: UI-Veredelung, Tabellen-Klick-Navigation, Dividenden-Streak & Clean Monitor

**Sprint-Status:** Abgeschlossen / Fertiggestellt (Phase 3: Implementation)  
**Erstellt am:** 20.10.2026  
**Abgeschlossen am:** 20.10.2026  
**Ziel:** Modernisierung des UI-Headers mit Hero-Banner („Was wir tun vs. Was wir nicht tun“), direkte Synchronisation der Detailansicht per Klick auf eine Tabellenzeile (`st.dataframe` on_select), Verschiebung des manuellen Aktualisierungs-Buttons in den Backtest-Tab, Entfernung des Strategie-Blocks und von "V2", Bereinigung von PEG/EPS im Tab Unternehmenswerte, Korrektur des Dividenden-Streaks bei aktuellem Rückgang sowie Bereitstellung eines Cache-Refresh-Buttons für Einzeltitel.

## Testergebnisse & Verifikation:
- **177 Tests erfolgreich bestanden** (0 Fehler, 0 Regressionen in `pytest tests/`).
- Neue & erweiterte Testsuiten: `tests/test_interactive_table.py` (4 Tests), `tests/test_deep_fundamentals.py` (5 Tests), `tests/test_app_startup.py` (7 Tests).

---

## 1. Scope & Hintergrund
Der Signal Monitor soll fokussiert, extrem performant und modern wirken. Bisher war die Auswahl einer Detailaktie über eine separate Dropdown-Box vom Tabellenklick entkoppelt, Berechnungs-Buttons im Monitor lenkten ab und die Benennung („Signal Monitor V2“) war uneinheitlich. Gleichzeitig verfälschte die Dividenden-Streak-Berechnung Serien, wenn im aktuellen Jahr gekürzt wurde, und überfrachtete Kennzahlen wie PEG/EPS in Tab 2 verwirrten das Gesamtbild.

---

## 2. Detaillierte Task-Liste

### Task 1: Interaktive Tabellen-Zeilenauswahl ohne Checkboxen (Option C) in `app.py`
- **Komponente:** `stock_monitor_app/components/interactive_table/index.html`, `app.py` (`render_interactive_signals_table`)
- **Implementierungsdetails:**
  1. Eigenes leichtgewichtiges Streamlit-Custom-Component (`interactive_table`) via `components.declare_component`:
     - 100% frei von Checkboxen / Radio-Spalten.
     - Jeder Klick auf eine Spalte/Zelle einer Zeile ruft `Streamlit.setComponentValue(symbol)` auf.
     - Visuelles Feedback über Zeilen-Hover und aktive Zeilenhervorhebung.
     - Integriertes schnelles Client-Suchfeld (`#searchInput`) und Spaltensortierung.
     - Fester Scrollbereich (450px) mit Sticky-Header.
  2. Integration in `app.py`:
     ```python
     clicked_symbol = render_interactive_signals_table(
         table_rows,
         selected_symbol=active_sym,
         key="main_signals_table",
     )
     if clicked_symbol and clicked_symbol != active_sym:
         st.session_state["active_selected_symbol"] = clicked_symbol
         st.rerun()
     ```
  3. Automatische Synchronisation mit dem Dropdown-Index der Detailansicht.
- **Akzeptanzkriterien:**
  - Keine Checkboxen in der Tabelle sichtbar.
  - Ein Klick auf jede beliebige Spalte einer Zeile selektiert die gesamte Zeile und schaltet die darunterliegende Detailansicht sofort auf diese Aktie um.
  - Das Dropdown spiegelt die Auswahl wider und bleibt als alternative Schnellauswahl voll funktionsfähig.

---

### Task 2: UI-Header, Hero-Banner & Monitor-Verschlankung
- **Komponente:** `app.py` (`render_stock_agent`, `render_watchlist_signal_monitor`, `render_backtest_tab`)
- **Implementierungsdetails:**
  1. **Titel & Tabs:**
     - Tab-Reiter umbenennen: `stock_tabs = st.tabs(["🔥 Signal Monitor", "Backtest & ML", "Hilfe & Methodik"])`.
     - Überschrift im Monitor: `st.subheader("🔥 Signal Monitor")` (kein "V2" mehr).
  2. **Hero-Banner (Was wir tun vs. Was wir NICHT tun):**
     - Modernes, einklappbares Info-Banner (`with st.expander("ℹ️ Über diesen StockWatcher – Mission & Prinzipien", expanded=False)`):
       - **🎯 Was dieser Monitor leistet:** Systematische Echtzeit-Filterung von Aktien nach 9 objektiven Frühsignalen (Brodel-Score) – EPS-Revisionen, Kursziel-Dynamik, Volumen-Akkumulation, Insider-Transaktionen und relative Stärke.
       - **⛔ Was dieser Monitor NICHT ist:** Keine Anlageberatung, keine Kaufempfehlungen, keine Glaskugel. Rein datengestützte Marktfrüherkennung.
  3. **Verschiebung des Aktualisierungs-Buttons:**
     - Der Button *"Signale aktualisieren"* und der Snapshot-Erstellungs-Trigger wandern aus dem Signal Monitor in den Reiter `Backtest & ML` (unter *„⚙️ Datenpflege & Signal-Snapshot erstellen“*).
     - Der Signal Monitor lädt standardmäßig direkt und blitzschnell den letzten gespeicherten Snapshot aus `watchlists/meine_watchlist.txt`.
  4. **Entfernung der Handlungsempfehlungen:**
     - Der Block `st.markdown("**Strategie-Signale & Handlungsempfehlungen**")` samt Tabelle wird aus dem Signal Monitor entfernt.
- **Akzeptanzkriterien:**
  - Monitor lädt sofort ohne störende Rechen-Buttons.
  - Kein "V2" mehr in Tab- oder Überschriftstiteln.
  - Hero-Banner ist transparent und informativ.
  - Button zur manuellen Neuberechnung ist sauber im Tab Backtest & ML integriert.

---

### Task 3: Korrektur der Dividenden-Steigerungsserie (Streak-Reset) in `stock_agent.py`
- **Komponente:** `stock_agent.py` (`fetch_company_extended_fundamentals`)
- **Implementierungsdetails:**
  1. Einbezug des aktuellen Jahrs / der TTM-Ausschüttung:
     - Ermittlung der letzten vollständigen Jahresdividende `prev_year_val` (Vorjahr).
     - Ermittlung der aktuellen Dividendenrate `curr_rate = div_rate`.
     - Wenn `curr_rate` und `prev_year_val` vorliegen und `curr_rate < prev_year_val`:
       `streak_years = 0` (Kürzung im laufenden Jahr bricht die Serie sofort ab).
     - Andernfalls Weiterzählung der historischen Steigerungsjahre rückwärts, bis ein Jahr nicht höher als sein Vorjahr war.
- **Akzeptanzkriterien:**
  - Wenn eine Aktie 10 Jahre erhöht hat, im laufenden Jahr aber die Rate gesenkt wurde, ist der Streak exakt 0.
  - Wenn kontinuierlich erhöht wurde, wird die korrekte Jahreszahl ausgewiesen.

---

### Task 4: Bereinigung von PEG & EPS in Tab 2 (Unternehmenswerte) & Einzel-Cache-Refresh
- **Komponente:** `app.py` (`detail_tab_fundamentals`)
- **Implementierungsdetails:**
  1. Entfernung von `peg_ratio` und `forward_eps` aus der Bewertung in Tab 2.
  2. KGV-Analyse fokussiert auf Trailing-KGV und Forward-KGV.
  3. Button in der Detailbox:
     ```python
     if st.button("🔄 Fundamentaldaten neu laden", key=f"refresh_{selected_symbol}"):
         get_extended_fundamentals.clear(selected_symbol)
         st.rerun()
     ```
- **Akzeptanzkriterien:**
  - Tab 2 zeigt kein PEG und keine EPS-Reihen mehr an.
  - Ein Klick auf "Fundamentaldaten neu laden" leert den spezifischen Disk-Cache und zieht frische Daten von Yahoo Finance.

---

### Task 5: Automatisierte Tests & Verifikation
- **Komponente:** `tests/test_deep_fundamentals.py`, `tests/test_app_startup.py`
- **Implementierungsdetails:**
  1. Testfall für Dividenden-Streak bei aktueller Kürzung (Streak = 0 trotz historischer Steigerungen).
  2. Testfall für Streamlit-Layout (3 Tabs mit `🔥 Signal Monitor`, Verschiebung des Rechen-Buttons).
  3. Vollständige Test-Suite ausführen (`pytest tests/`).
- **Akzeptanzkriterien:**
  - 100 % Bestehensquote aller Tests ohne Fehler oder Regressionen.

---

## 3. Gesamte Akzeptanzkriterien für Sprint 5
1. Klick auf eine Zeile im Signal Monitor synchronisiert sofort die Detailansicht.
2. Der Tab-Titel und Monitor heißen einheitlich `🔥 Signal Monitor` (ohne V2).
3. Hero-Banner mit "Was wir tun vs. Was wir nicht tun" ist integriert.
4. "Signale aktualisieren" ist in `Backtest & ML` verschoben; Strategie-Tabelle ist entfernt.
5. Dividenden-Streak ist 0, wenn im aktuellen Jahr gekürzt wurde.
6. PEG und EPS sind aus Tab 2 entfernt; Cache-Refresh-Button für Einzeltitel ist vorhanden.
7. Alle automatisierten Tests laufen erfolgreich durch.

---

## 4. Verifikation & Testergebnisse
- **Automatisierte Tests:** 173 Tests erfolgreich (0 Fehler, 0 Regressionen in `pytest tests/`).
- **Dividenden-Streak:** `test_fetch_company_extended_fundamentals_dividend_streak_reset_on_cut` verifiziert, dass unterjährige Dividendenkürzungen die Steigerungsserie sofort auf 0 zurücksetzen.
- **Layout & Tabs:** `test_render_stock_agent_layout` bestätigt das 3-Tab-Layout mit `🔥 Signal Monitor`.
- **UI-Interaktivität:** Zeilenklicks in `st.dataframe` (`on_select="rerun"`) steuern den Session-State für die Detailbox direkt und ohne Umwege.
- **Cleaner Monitor:** "Signale aktualisieren" wurde sauber in den Tab `Backtest & ML` ausgelagert; Handlungsempfehlungen wurden aus dem Monitor entfernt; PEG und EPS wurden aus Tab 2 entfernt.

