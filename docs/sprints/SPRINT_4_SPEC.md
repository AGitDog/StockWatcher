# Sprint 4 Spezifikation: Operative Kosten (OpEx) & Aufwandsaufschlüsselung (F&E vs. SG&A)

**Sprint-Status:** Abgeschlossen / Fertiggestellt (Phase 3: Implementation)  
**Erstellt am:** 20.10.2026  
**Abgeschlossen am:** 20.10.2026  
**Ziel:** Ermittlung, historische Aufbereitung (letzte 4–5 Geschäftsjahre) und Visualisierung der operativen Kosten (Operating Expenses / OpEx) inklusive detaillierter Aufschlüsselung nach Forschung & Entwicklung (F&E / R&D) sowie Vertrieb & Verwaltung (SG&A) im Reiter „🏢 Unternehmenswerte“.

## Testergebnisse & Verifikation:
- **172 Tests erfolgreich bestanden** (0 Fehler, 0 Regressionen in `pytest tests/`).
- Neue & erweiterte Testsuiten: `tests/test_deep_fundamentals.py` (4 Tests), `tests/test_app_startup.py` (7 Tests).

---

## 1. Scope & Hintergrund
Zur fundamentalen Beurteilung von Geschäftsmodellen und Skaleneffekten ist die Kenntnis der operativen Kostenstruktur essenziell. Während Sprint 1 die Bruttomargen etabliert hat, beantwortet Sprint 4, wie viel des Bruttogewinns für operative Kernaufwendungen (F&E, Vertrieb, Verwaltung) verwendet wird und welche operative Marge nach Abzug aller Betriebskosten verbleibt.

---

## 2. Detaillierte Task-Liste

### Task 1: Backend-Datenextraktion in `stock_agent.py`
- **Komponente:** `stock_agent.py` (`fetch_company_extended_fundamentals`)
- **Implementierungsdetails:**
  1. Auslesen relevanter Zeilen aus `ticker.income_stmt`:
     - Gesamte operative Kosten (`"Operating Expense"` / `"Total Operating Expense"` / `"Operating Expenses"`).
     - F&E-Kosten (`"Research And Development"` / `"Research & Development"`).
     - SG&A-Kosten (`"Selling General And Administration"` / `"Selling General Administrative"` / `"Selling General and Administrative"`).
     - Operativer Gewinn (`"Operating Income"` / `"Operating Profit"` / `"EBIT"`).
  2. Berechnung der jährlichen Kennzahlen und Quoten:
     - `OpEx` (absolut), `F&E` (absolut), `SG&A` (absolut).
     - Operative Marge in Prozent: `(Operating Income / Total Revenue) * 100`.
     - OpEx-Quote in Prozent: `(OpEx / Total Revenue) * 100`.
     - F&E-Quote in Prozent: `(F&E / Total Revenue) * 100`.
     - SG&A-Quote in Prozent: `(SG&A / Total Revenue) * 100`.
  3. Abfrage der aktuellen TTM-Operativen-Marge aus `info.get("operatingMargins")`.
  4. Rückgabe in `fetch_company_extended_fundamentals`:
     - `"operating_margin_ttm"`: Float (z. B. 24.5 für 24.5 %) oder `None`.
     - `"operating_cost_history"`: Chronologisch sortierte Liste von Dictionaries für die letzten 4–5 Jahre.
  5. Ausfallsicherheit: Robuste Behandlung fehlender Zeilen (z. B. Banken ohne klassische OpEx oder Unternehmen ohne separate R&D-Kosten).
- **Akzeptanzkriterien:**
  - Standard-Aktien (z. B. AAPL, MSFT, SAP.DE) liefern historische OpEx-, F&E- und SG&A-Werte.
  - Sonderfälle (Banken, ETFs) stürzen nicht ab, sondern liefern saubere `None`-Werte.
  - Quoten werden kaufmännisch auf 1–2 Dezimalstellen gerundet.

---

### Task 2: Frontend-Integration im Tab „🏢 Unternehmenswerte“ in `app.py`
- **Komponente:** `app.py` (`render_watchlist_signal_monitor`, Tab `🏢 Unternehmenswerte`)
- **Implementierungsdetails:**
  1. Neuer Abschnitt: `st.markdown("#### ⚙️ Operative Kosten & Aufwand (OpEx)")`.
  2. 4 Metrik-Kacheln (`st.columns(4)`):
     - **Operative Marge (TTM):** z. B. `28.4 %`.
     - **OpEx gesamt:** Betrag des letzten Geschäftsjahres (Mrd. / Mio. Landeswährung).
     - **Forschung & Entwicklung (F&E / R&D):** Betrag und F&E-Quote in % (als Hilfetext/Delta).
     - **Verwaltung & Vertrieb (SG&A):** Betrag und SG&A-Quote in % (als Hilfetext/Delta).
  3. Gestapeltes Balkendiagramm (`st.bar_chart` oder Altair/Plotly):
     - Jährlicher Vergleich von F&E vs. SG&A zur Veranschaulichung des Kostenmix.
  4. Kombinierte Jahrestabelle (`st.dataframe`):
     - Spalten: `Jahr`, `Umsatz`, `OpEx gesamt`, `F&E (R&D)`, `SG&A`, `Op. Marge (%)`, `OpEx-Quote (%)`.
  5. Fallback-Hinweis:
     - Wenn keine OpEx-Daten vorliegen (z. B. Banken/Versicherungen), Einblendung einer dezenten Infobox: *"Keine klassischen operativen Kosten (OpEx / F&E) im Geschäftsbericht ausgewiesen (typisch für Banken, Versicherungen oder Finanzdienstleister)."*
- **Akzeptanzkriterien:**
  - Der Abschnitt fügt sich nahtlos in den Tab "🏢 Unternehmenswerte" ein (unter Bruttomarge, vor KGV/Dividenden).
  - Bei Titeln mit F&E und SG&A werden Kacheln, Chart und Tabelle sauber formatiert dargestellt.
  - Bei Banken/Finanztiteln wird der Fallback-Hinweis fehlerfrei angezeigt.

---

### Task 3: Automatisierte Unit-Tests
- **Komponente:** `tests/test_deep_fundamentals.py`
- **Implementierungsdetails:**
  1. Testfall für vollständige OpEx-Historie (Umsatz, OpEx, R&D, SG&A, Operating Income).
  2. Testfall für Sonderfälle (Bank/Versicherung ohne OpEx/F&E und Unternehmen mit SG&A aber ohne R&D).
  3. Regressionstests aller bestehenden Suiten (`pytest tests/`).
- **Akzeptanzkriterien:**
  - 100 % Bestehensquote aller Tests ohne Fehler oder Regressionen.

---

## 3. Gesamte Akzeptanzkriterien für Sprint 4
1. `stock_agent.py` extrahiert OpEx, F&E, SG&A und Operating Income aus `income_stmt` und berechnet Quoten.
2. Der Tab "🏢 Unternehmenswerte" in `app.py` zeigt Kacheln, gestapeltes Diagramm und Jahrestabelle für operative Kosten.
3. Banken und Sonderfälle werden ohne Absturz mit transparentem Hinweis behandelt.
4. Alle automatisierten Unit-Tests laufen fehlerfrei durch.

---

## 4. Verifikation & Testergebnisse
- **Automatisierte Tests:** 172 Tests erfolgreich (0 Fehler, 0 Regressionen in `pytest tests/`).
- **Backend-Extraktion & Fallback:** `test_fetch_company_extended_fundamentals_gross_margin_and_valuation`, `test_fetch_company_extended_fundamentals_opex_partial_sga_only` und `test_fetch_company_extended_fundamentals_ebit_calculated_fallback` bestätigen die korrekte Berechnung von OpEx, F&E, SG&A, EBIT (inklusive `Gross Profit - OpEx` Fallback), Quoten und Margen.
- **Sonderfall-Robustheit:** `test_fetch_company_extended_fundamentals_no_gross_profit_bank_or_etf` stellt sicher, dass Banken/ETFs ohne OpEx sauber als leere Historie ohne Exception verarbeitet werden.
- **UI-Stabilität:** `test_detail_fundamentals_rendering_with_opex` verifiziert, dass die Detailbox alle Kennzahlen (inkl. 5 Kacheln mit EBIT und der dedizierten EBIT-Spalte) fehlerfrei formatiert und visualisiert.

