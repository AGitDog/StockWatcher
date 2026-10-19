# Sprint 1 Spezifikation: Detail-Box Tabs, Bruttokennzahlen, Zukünftiger Wert & Neue Indizes

**Sprint-Status:** Abgeschlossen / Fertiggestellt  
**Abgeschlossen am:** 19.10.2026  
**Ziel:** Strukturierung der Detail-Box in zwei übersichtliche Tabs, Integration historischer Bruttogewinn- und Bruttomargen-Kennzahlen, Schätzung des zukünftigen Firmenwerts via Analysten-Konsens & Forward-Bewertung, Unterstützung der Indizes SOX & NBI sowie Behebung des Nikkei 225 Nummern-Problems.

## Testergebnisse & Verifikation:
- **165 Tests erfolgreich bestanden** (0 Fehler, 0 Regressionen).
- Neue Test-Suiten: `tests/test_indices.py` (6 Tests), `tests/test_deep_fundamentals.py` (2 Tests).

---

## 1. Scope & Hintergrund
In früheren Iterationen führte das sequentielle Anzeigen von Unternehmenszahlen, Kennzahlen und Signalen zu einer überladenen Detailansicht. Dieser Sprint führt eine klare Tab-Trennung ein, ergänzt fokussierte Profitabilitäts- und Bewertungswerte und erweitert die Index-Unterstützung nach Nutzeranforderung.

---

## 2. Detaillierte Task-Liste

### Task 1: Neue Indizes (PHLX Semiconductor Sector & NASDAQ Biotechnology Index)
- **Komponente:** `stock_agent.py` (`INDEX_DEFINITIONS`, `load_index_constituents`, `_looks_like_index_candidate`)
- **Implementierungsdetails:**
  1. **PHLX Semiconductor Sector (SOX):**
     - Aliase: `{"PHLX SEMICONDUCTOR SECTOR", "PHLX SEMICONDUCTOR", "PHLX", "SOX", "^SOX", "SOXX", "INDEX:SOX", "INDEX:PHLX", "PHILADELPHIA SEMICONDUCTOR", "PHILADELPHIA SEMICONDUCTOR INDEX"}`.
     - Dynamischer Parser: Regex-Scraping der Wikipedia-Seite (`https://en.wikipedia.org/wiki/PHLX_Semiconductor_Sector`) für 30 Halbleiteraktien (`Company, TICKER`).
     - Statischer Fallback: Vollständige Liste der 30 Ticker (NVDA, AMD, INTC, ASML, TSM, AVGO, QCOM, AMAT, LRCX, TXN, MU, ADI, MPWR, KLAC, NXPI, MRVL, MCHP, ON, QRVO, SWKS, TER, ENTG, GFS, LSCC, ACLS, ALGM, AMKR, COHR, RMBS, WOLF) bei Timeout/Netzwerkfehler.
  2. **NASDAQ Biotechnology Index (NBI):**
     - Aliase: `{"NASDAQ BIOTECHNOLOGY INDEX", "NASDAQ BIOTECHNOLOGY", "NBI", "^NBI", "IBB", "IBBQ", "INDEX:NBI", "INDEX:NASDAQ BIOTECHNOLOGY"}`.
     - Dynamischer Parser: POST-Request an `https://indexes.nasdaqomx.com/Index/WeightingData` mit Parametern `id="NBI"`, `timeOfDay="SOD"` zur Abfrage aller 245 Konstituenten inkl. Ticker und Namen.
     - Statischer Fallback: Top-Biotech-Titel (GILD, AMGN, VRTX, REGN, MRNA, BIIB, ILMN, ARGX, NTRA, RVMD etc.).
  3. **Erkennung:** Keywords in `_looks_like_index_candidate` um `"SOX"`, `"PHLX"`, `"NBI"`, `"BIOTECH"`, `"SEMICONDUCTOR"` ergänzen.
- **Akzeptanzkriterien:**
  - `load_index_constituents("PHLX Semiconductor Sector")` liefert 30 Ticker.
  - `load_index_constituents("NASDAQ Biotechnology Index")` liefert > 200 Ticker.
  - Eingabe von `SOX` oder `NBI` in Watchlists expandiert automatisch in die entsprechenden Aktien.

---

### Task 2: Behebung des Nikkei 225 Klarnamen-Problems ("Nur Nummern")
- **Komponente:** `stock_agent.py` (`NIKKEI_225_NAMES`, `resolve_name_fallback`, `INDEX_CONSTITUENT_NAMES`)
- **Implementierungsdetails:**
  1. **Persistentes Klarnamen-Wörterbuch:** Hinterlegung von `NIKKEI_225_NAMES: dict[str, str]` mit allen 225 japanischen Titeln (z. B. `'9983.T': 'Fast Retailing'`, `'7203.T': 'Toyota Motor'`, `'6758.T': 'Sony Group'`, `'7974.T': 'Nintendo'`, `'8035.T': 'Tokyo Electron'`).
  2. **Fallback-Hierarchie:** `resolve_name_fallback(symbol, current_name)` prüft vor Online-Suchen sofort, ob `symbol` in `NIKKEI_225_NAMES` oder `INDEX_CONSTITUENT_NAMES` existiert, und liefert sofort den echten Namen zurück.
  3. **Watchlist-Kommentar-Format:** Beim automatischen Expandieren von `Nikkei 225` werden die Namen als Kommentar beigefügt (`9983.T # Fast Retailing`).
- **Akzeptanzkriterien:**
  - Japanische Aktien werden überall (Tabelle, Detail-Kopfzeile, Dropdowns) mit Klarnamen angezeigt (z. B. `Fast Retailing (9983.T)`), selbst wenn yfinance gedrosselt ist oder offline läuft.
  - Keine reinen Zahlenkürzel mehr als Anzeigename.

---

### Task 3: Backend – Bruttogewinn, Bruttomarge & Zukünftiger Wert
- **Komponente:** `stock_agent.py` (`fetch_company_extended_fundamentals`)
- **Implementierungsdetails:**
  1. **Bruttogewinn & Bruttomarge Historie:**
     - Auslesen der letzten 4–5 Jahre aus `ticker.income_stmt` (`"Gross Profit"`, `"Total Revenue"`).
     - Berechnung der jährlichen Bruttomarge in Prozent: `round((gross_profit / revenue) * 100, 2)`.
     - Bereitstellung als sortierte Liste `gross_margin_history: list[dict[str, Any]]` mit Feldern `Jahr`, `Umsatz`, `Bruttogewinn`, `Bruttomarge (%)`.
     - Abfrage der aktuellen TTM-Bruttomarge aus `info.get('grossMargins')`.
  2. **Zukünftig geschätzter Wert der Firma (Analysten-Konsens & Forward-Bewertung):**
     - Kursziele: `target_mean_price`, `target_median_price`, `target_high_price`, `target_low_price`.
     - Berechnung des prozentualen Aufwärtspotenzials: `round(((target_mean_price - current_price) / current_price) * 100, 1)`.
     - Berechnung der impliziten Marktkapitalisierung: Marktkapitalisierung * (target_mean_price / current_price).
     - Forward-Bewertung: `forward_pe`, `trailing_pe`, `forward_eps`.
  3. **Ausfallsicherheit:** Robuste Null- und NaN-Behandlung für Sonderfälle (ETFs, Banken/Versicherungen ohne Bruttogewinn-Ausweis, fehlende Analysten-Coverage).
- **Akzeptanzkriterien:**
  - Für Standardaktien (z. B. AAPL, MSFT, SAP.DE) werden die 4–5 Jahresabschlüsse für Bruttogewinn und -marge sauber extrahiert.
  - Für Titel ohne Bruttogewinn (z. B. Banken/ETFs) stürzt die Funktion nicht ab, sondern liefert `None`/leere Liste.
  - Analystenziele und Forward-KGV werden strukturiert im Dictionary zurückgegeben.

---

### Task 4: Frontend – Streamlit Tabs Unterteilung in `app.py`
- **Komponente:** `app.py` (`render_watchlist_signal_monitor`)
- **Implementierungsdetails:**
  1. **Tab-Struktur:** Ersetzen der linearen Detailbox durch:
     ```python
     tab_signals, tab_fundamentals = st.tabs(["🔥 Brodel-Index Kalkulation", "🏢 Unternehmenswerte"])
     ```
  2. **Reiter 1 (`🔥 Brodel-Index Kalkulation`):**
     - Signal-Zusammenfassung & Signal-Breakdown-Tabelle.
     - Peer- und Sektor-Kontext.
     - 100-Tage Brodel-Score Verlaufschart.
  3. **Reiter 2 (`🏢 Unternehmenswerte`):**
     - **Unternehmensprofil:** Sektor, Branche, Hauptsitz, Mitarbeiterzahl, deutsche Zusammenfassung.
     - **Zukünftig geschätzter Wert & Analysten-Konsens:**
       - Metrik-Kacheln: Aktueller Kurs, Analysten-Kursziel (Mean / Median), Upside in %, Implizite Marktkapitalisierung.
       - KGV-Vergleich: Trailing-KGV vs. Forward-KGV und PEG-Ratio.
     - **Bruttogewinn & Bruttomarge:**
       - Metrik-Kachel: Aktuelle Bruttomarge (TTM) & letzter Jahres-Bruttogewinn.
       - Kombinierte Tabelle (Jahr, Umsatz, Bruttogewinn, Bruttomarge %).
       - Historischer Trend-Chart für die Bruttomarge.
     - **KGV- und Dividenden-Historie:** Kompakte Weiterführung der bestehenden KGV- und Dividenden-Analysen.
- **Akzeptanzkriterien:**
  - Beide Tabs schalten verzögerungsfrei um; kein unendliches vertikales Scrollen mehr nötig.
  - Alle neuen Kennzahlen werden übersichtlich formatiert (Währungen, %, Mrd./Mio.).
  - Klare Info-Meldungen bei fehlenden Daten (z. B. keine Analysten-Coverage).

---

### Task 5: Automatisierte Unit-Tests & Regressionstests
- **Komponente:** `tests/test_deep_fundamentals.py`, `tests/test_indices.py`
- **Implementierungsdetails:**
  1. Tests für `load_index_constituents` mit SOX und NBI (inklusive Mocking & Offline-Fallback-Prüfung).
  2. Tests für Nikkei 225 Namensauflösung (`resolve_name_fallback`).
  3. Tests für `fetch_company_extended_fundamentals`:
     - Berechnung von Bruttomarge und Historie.
     - Berechnung von Upside % und impliziter Marktkapitalisierung.
     - Verhalten bei Banken/ETFs/fehlenden Daten.
  4. App-Startup / Smoke-Test (`tests/test_app_startup.py`).
- **Akzeptanzkriterien:**
  - 100% Durchlauf aller Tests mit `.venv\Scripts\python.exe -m pytest tests/` ohne Fehler oder Regressionen.

---

## 3. Akzeptanzkriterien für den gesamten Sprint
1. Detail-Box jeder Aktie im Signal-Monitor besitzt die beiden Tabs "🔥 Brodel-Index Kalkulation" und "🏢 Unternehmenswerte".
2. Bruttogewinn und Bruttomarge werden über 4–5 Geschäftsjahre mit Tabelle und Trend dargestellt.
3. Analysten-Kursziel, Upside % und Forward-KGV werden als zukünftiger Schätzwert angezeigt.
4. Die Indizes `SOX` und `NBI` sind in Watchlists nutzbar und expandieren vollständig.
5. Nikkei 225 Aktien werden mit echtem Firmennamen dargestellt statt als Nummer.
6. Alle Tests im Testsuite laufen grün durch.
