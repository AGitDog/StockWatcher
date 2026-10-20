# 🔥 Brodel-Radar – Quantitative Marktbeobachtung: System-Spezifikation (SPEC.md)

## 1. Architektur & Guardrails
- **Tech-Stack:** Streamlit, Python 3.12, Pandas, yfinance, Plotly / Altair.
- **Workflow:** Phasenbasiertes Agentic-Agile Framework nach `AGENTS.md`.
- **Datenquellen:** Yahoo Finance (`yfinance`) als primäre Quelle für Kurs-, Finanz- und Analystendaten.
- **Prinzip:** Klare Trennung zwischen Signalanalyse (Brodel-Score) und Unternehmenswerten (Fundamentaldaten), um visuelle Überfrachtung zu vermeiden.

---

## 2. Feature-Spezifikation: Unterteilung der Detail-Box & Erweiterte Unternehmenswerte

### 2.1 Ziel & Motivation
Die Detail-Box für jede Aktie soll strukturiert und aufgeräumt werden, um eine Überladung mit Informationen zu verhindern. Die Inhalte werden in zwei fokussierte Streamlit-Tabs aufgeteilt:
1. **Reiter 1: 🔥 Brodel-Index Kalkulation**
2. **Reiter 2: 🏢 Unternehmenswerte**

### 2.2 Spezifikation Tab 1: 🔥 Brodel-Index Kalkulation
- **Signal-Zusammenfassung:** Liste der aktiven Kaufs-/Verkaufs-Signale.
- **Signal-Breakdown:** Tabelle mit Punkten je Komponente (EPS, Kursziele, News, Insider, Event, Short Interest, Rel. Stärke, etc.).
- **Peer- & Sektor-Kontext:** Vergleich mit Sektor-Durchschnitt und stärkstem Watchlist-Peer.
- **Score-Verlauf:** Historischer Verlauf des Brodel-Scores über die letzten 100 Tage (sofern Snapshots vorhanden).

### 2.3 Spezifikation Tab 2: 🏢 Unternehmenswerte
- **Unternehmensprofil:**
  - Sektor, Branche, Land, Hauptsitz, Mitarbeiterzahl und KI-generierte Zusammenfassung.
- **Bruttogewinn & Bruttomarge (Historie & Aktuell):**
  - **Datenquelle:** `ticker.income_stmt` (Jahresabschlüsse der letzten 4-5 Geschäftsjahre) und `ticker.info.get('grossMargins')`.
  - **Kennzahlen:**
    - Absoluter Bruttogewinn (Gross Profit) in Landeswährung (z. B. Mrd./Mio. EUR/USD).
    - Bruttomarge (Gross Margin = Gross Profit / Total Revenue) in Prozent für jedes der letzten 4-5 Jahre.
    - Aktuelle TTM-Bruttomarge als Kern-Metrik.
  - **Darstellung:** Übersichtliche Metrik-Kacheln, kombinierte Tabelle (Jahr, Umsatz, Bruttogewinn, Bruttomarge %) und interaktiver Trend-Chart.
- **Zukünftig geschätzter Wert der Firma:**
  - **Analysten-Konsens & Upside:**
    - Kursziel (Target Mean & Median Price) im Vergleich zum aktuellen Kurs.
    - Berechnetes Aufwärtspotenzial (Upside in %).
    - Implizite Marktkapitalisierung bei Erreichen des Kursziels (`targetMeanPrice * sharesOutstanding` bzw. Kursziel-Faktor * aktuelle Marktkapitalisierung).
  - **Forward-Bewertung:**
    - Forward-KGV (`forwardPE`) vs. aktuelles Trailing-KGV (`trailingPE`) und PEG-Ratio.
- **KGV- & Dividenden-Historie:**
  - KGV-Trend der letzten Geschäftsjahre.
  - Dividenden-Historie (letzte 15 Jahre, Ausschüttung, Rendite & Steigerungsserie).

### 2.4 Einfluss auf den Brodel-Score
- Gemäß Refinement-Entscheidung: **Keine Auswirkung auf den Brodel-Score**.
- Die neuen Kennzahlen dienen rein der fundamentalen Tiefenrecherche und Bewertung in der Detail-Ansicht.

---

### 2.5 Unterstützung des PHLX Semiconductor Sector Index (SOX)
- **Motivation:** Der Philadelphia Semiconductor Index (SOX) ist die weltweite Benchmark für Halbleiteraktien (Chips & Equipment).
- **Index-Definition & Aliase:**
  - Name: `PHLX Semiconductor Sector`
  - Aliase: `{"PHLX SEMICONDUCTOR SECTOR", "PHLX SEMICONDUCTOR", "PHLX", "SOX", "^SOX", "SOXX", "INDEX:SOX", "INDEX:PHLX", "PHILADELPHIA SEMICONDUCTOR", "PHILADELPHIA SEMICONDUCTOR INDEX"}`
- **Konstituenten (30 führende Halbleiter-Unternehmen):**
  - Dynamisches Parsing via Wikipedia-URL (`https://en.wikipedia.org/wiki/PHLX_Semiconductor_Sector`) mit robuster Listen-Extraktion (`Regex` auf `Company, TICKER`).
  - Statischer Fallback-Satz aller 30 Standardwerte (NVDA, AMD, INTC, ASML, TSM, AVGO, QCOM, AMAT, LRCX, TXN, MU, ADI, MPWR, KLAC, NXPI, MRVL, MCHP, ON, QRVO, SWKS, TER, ENTG, GFS, LSCC, ACLS, ALGM, AMKR, COHR, RMBS, WOLF) bei Netzwerk-Timeouts.
- **Watchlist-Integration:**
  - Wird als Index-Kandidat in `_looks_like_index_candidate` und `_match_index_alias` erkannt.
  - Das Eintragen von `SOX` oder `PHLX Semiconductor Sector` in eine Watchlist expandiert automatisch auf die 30 Halbleiter-Werte.

---

### 2.6 Unterstützung des NASDAQ Biotechnology Index (NBI)
- **Motivation:** Der führende Benchmark-Index für Biotechnologie- und Pharma-Innovatoren an der NASDAQ (ca. 240+ Werte).
- **Index-Definition & Aliase:**
  - Name: `NASDAQ Biotechnology Index`
  - Aliase: `{"NASDAQ BIOTECHNOLOGY INDEX", "NASDAQ BIOTECHNOLOGY", "NBI", "^NBI", "IBB", "IBBQ", "INDEX:NBI", "INDEX:NASDAQ BIOTECHNOLOGY"}`
- **Datenquelle & Konstituenten:**
  - Offizieller NASDAQ-API-Endpunkt (`https://indexes.nasdaqomx.com/Index/WeightingData`) zur dynamischen Abfrage aller 245 Konstituenten inkl. Firmennamen.
  - Robuster Fallback-Satz der Top-Biotech-Schwergewichte (GILD, AMGN, VRTX, REGN, MRNA, BIIB, ILMN, ARGX, NTRA, RVMD etc.) für Offline- oder Timeout-Szenarien.

---

### 2.7 Behebung des Nikkei 225 Namensproblems ("Nur Nummern")
- **Problemursache:**
  - Japanische Aktien an der Tokyo Stock Exchange (TSE) haben standardmäßig 4-stellige numerische Ticker (z. B. `9983.T` für Fast Retailing / Uniqlo, `7203.T` für Toyota, `6758.T` für Sony).
  - Wenn `INDEX_CONSTITUENT_NAMES` nur flüchtig im Arbeitsspeicher gehalten wird oder Yahoo Finance bei einer 225-Aktien-Watchlist wegen zu vieler Anfragen rate-limited (HTTP 429), schlägt die Namensauflösung fehl und die App zeigt nur noch die Ziffern (z. B. `9983.T - 9983.T`) an.
- **Lösung:**
  - **1. Persistentes Constituent-Mapping:** Einbettung eines vollständigen, statisch abgesicherten Namens-Mappings aller 225 Nikkei-Werte (Ticker `.T` -> Klarnamen wie "Fast Retailing", "Toyota Motor", "Sony Group", "Nintendo", "Tokyo Electron").
  - **2. Intelligenter Name-Fallback:** `resolve_name_fallback` greift bei jedem numerischen `.T`-Ticker sofort auf dieses Mapping zu, bevor überhaupt ein blockierender externer API-Aufruf erfolgt.
  - **3. Watchlist-Kommentar-Unterstützung:** Bei automatischer Expansion von `Nikkei 225` in eine Watchlist werden die Klarnamen als Kommentar angehängt (z. B. `9983.T # Fast Retailing`), damit der Nutzer auch im Textfile sofort sieht, um welches Unternehmen es sich handelt.

---

### 2.8 Watchlist-Verwaltung im Hintergrund & UI-Bereinigung (IDEA-001)
- **Motivation:** Das Dashboard wird als Single-User-/Personal-Monitoring-System betrieben. Ein separater Tab zur Watchlist-Verwaltung mit Upload-Elementen ist nicht erforderlich und überfrachtet das UI.
- **UI-Bereinigung:**
  - Der Tab "Watchlist Verwaltung" wird vollständig aus `app.py` entfernt.
  - Das Streamlit-Interface besteht nun aus den 3 Tabs: `Signal Monitor V2`, `Backtest & ML`, `Hilfe & Methodik`.
  - Im Signal Monitor wird auf Dropdown-Auswahlen verzichtet; die App lädt fest die zentrale Hintergrund-Watchlist.
- **Hintergrund-Watchlist (`watchlists/meine_watchlist.txt`):**
  - Dient als alleinige Standardquelle für `app.py` und `daily_job.py`.
  - Enthält standardmäßig alle konfigurierten Indizes inklusive der neuen Zugänge:
    - `SOX` (PHLX Semiconductor Sector)
    - `NBI` (NASDAQ Biotechnology Index)
    - `Nikkei 225`
  - Sämtliche verwaiste temporäre Upload-Dateien (z. B. `1832802889664.txt` etc.) werden aus dem Ordner `watchlists/` bereinigt.

---

### 2.9 Automatisierte tägliche Snapshots & Fokus-Bereinigung des Signal Monitors
- **Motivation:** Der manuelle Button "Snapshot speichern" ist fehleranfällig und unkomfortabel. Zudem überfrachten kurzfristige Delta-Vergleiche zu gestern das Dashboard. Für aussagekräftige Backtests und Trendlinien über Monate hinweg ist eine kontinuierliche, saubere Zeitreihe essenziell.
- **Tagesbasierte Snapshots (Idempotenz):**
  - Jede Datenberechnung (im UI oder per `daily_job.py`) erzeugt automatisch einen Snapshot.
  - Pro Kalendertag existiert genau ein Snapshot in der Historie. Mehrmaliges Aktualisieren an einem Tag aktualisiert den Datensatz des aktuellen Tags, statt redundante Intraday-Snapshots anzuhäufen.
  - Der Historien-Horizont wird von 15 auf **3665 Tage (ca. 10 Jahre rollierend)** erweitert (`MAX_SIGNAL_HISTORY_SNAPSHOTS = 3665`).
- **Entfernung von Delta-Alerts:**
  - Der Schwellwert-Slider und der Alert-Block für Score-Deltas seit dem letzten Snapshot werden aus dem UI entfernt.
  - Der Signal Monitor konzentriert sich voll auf den aktuellen Brodel-Score, ML-Score, Strategie-Setups, Sektor-Rankings und den langfristigen Score-Verlauf.

---

### 2.10 Operative Kosten (OpEx) & Aufwandsaufschlüsselung (F&E vs. SG&A)
- **Motivation:** Zur ganzheitlichen Beurteilung der Ertragskraft reicht die Bruttomarge allein nicht aus. Die operativen Kosten (Operating Expenses / OpEx) und deren Verteilung auf Forschung & Entwicklung (F&E / R&D) sowie Vertrieb und Verwaltung (SG&A) zeigen, wie effizient ein Unternehmen skaliert, ob Skaleneffekte greifen oder Kosten ausufern.
- **Datenquellen:**
  - `ticker.income_stmt` (Jahresabschlüsse der letzten 4–5 Geschäftsjahre):
    - `Operating Expense` (Operative Gesamtkosten)
    - `Research And Development` (F&E-Kosten)
    - `Selling General And Administration` (Vertriebs- & Verwaltungskosten)
    - `Operating Income` / `EBIT` (Operativer Gewinn)
    - `Total Revenue` / `Operating Revenue` (Umsatz zur Quotenberechnung)
  - `ticker.info.get('operatingMargins')` für die aktuelle TTM-Operative-Marge.
- **Berechnete Kennzahlen & Quoten:**
  - Absoluter Betrag für OpEx, F&E und SG&A in Landeswährung (Mrd. / Mio.).
  - F&E-Quote (`R&D / Total Revenue * 100`).
  - SG&A-Quote (`SG&A / Total Revenue * 100`).
  - Operative Gesamtkostenquote (`OpEx / Total Revenue * 100`).
  - Historische operative Marge (`Operating Income / Total Revenue * 100`) sowie TTM-Operative-Marge.
- **UI-Darstellung (Reiter 2: 🏢 Unternehmenswerte):**
  - Eigener strukturierter Abschnitt **„⚙️ Operative Kosten & Aufwand (OpEx)“**.
  - 5 Metrik-Kacheln: Operative Marge (TTM), EBIT / Operativer Gewinn (letztes Jahr inkl. Margen-Delta), Gesamtkosten OpEx (letztes Jahr), F&E (R&D) und Verwaltung/Vertrieb (SG&A).
  - Gestapeltes Balkendiagramm für die jährliche Kostenentwicklung (F&E vs. SG&A).
  - Kombinierte Jahrestabelle mit Umsatz, EBIT (absolut), OpEx, F&E, SG&A, Operativer Marge (%) und OpEx-Quote (%).
- **Ausfallsicherheit & Sonderfälle:**
  - Banken, Versicherungen oder ETFs ohne OpEx-/F&E-Ausweis stürzen nicht ab, sondern zeigen transparente Fallbacks bzw. den Hinweis *"Keine klassischen OpEx/F&E ausgewiesen"*.
  - Fehlt die Zeile `"Operating Income"` in den Jahresabschlüssen, wird das EBIT automatisch über die Bilanzformel `Gross Profit - OpEx` berechnet.
- **Einfluss auf den Brodel-Score:**
  - Rein informativ für die fundamentale Tiefenanalyse (keine Veränderung des Brodel-Scores).

---

### 2.11 UI-Veredelung, Tabellen-Klick-Navigation & Trennung von Monitor und Pflege (Sprint 5)
- **Motivation:** Das Dashboard soll sich wie eine state-of-the-art Investment-Plattform anfühlen. Unnötige Versionsbezeichnungen ("V2"), störende Berechnungs-Buttons im Monitoring-View und statische Auswahllisten behindern den schnellen Workflow.
- **Interaktive Tabellen-Selektion:**
  - Die Haupttabelle (`st.dataframe`) unterstützt native Zeilenauswahl (`on_select="rerun"`, `selection_mode="single-row"`).
  - Ein Klick auf eine beliebige Aktienzeile in der Tabelle aktualisiert sofort die Detail-Box auf dieses Symbol und synchronisiert die Auswahlliste.
- **Hero-Bereich & klares Mission Statement:**
  - Aufgepeppter Header mit System-Badges (Snapshots, Symbole, Status).
  - Einklappbares Onboarding-Banner:
    - **Was der StockWatcher tut:** Systematische Suche nach positiven Brodel-Veränderungen, Akkumulation, EPS-Revisionen, Insider-Käufen und relativem Momentum.
    - **Was der StockWatcher NICHT tut:** Keine Anlageberatung, kein Hype-Trading, keine Glaskugel.
- **Entlastung des Signal Monitors:**
  - Der manuelle Button *"Signale aktualisieren"* wird aus dem Signal Monitor in den Tab *"Backtest & ML"* verlagert. Der Signal Monitor dient rein der schnellen, verzögerungsfreien Inspektion.
  - Der vorläufige Block *"Strategie-Signale & Handlungsempfehlungen"* wird aus dem Signal Monitor entfernt.
  - Tab-Name wird von `"Signal Monitor V2"` in `"🔥 Signal Monitor"` vereinfacht.
- **Bereinigung von PEG und EPS in Tab 2 (Unternehmenswerte):**
  - PEG-Ratio und EPS-Historie werden aus Tab 2 entfernt; Fokus liegt rein auf KGV (Trailing & Forward), Bruttomarge, EBIT und OpEx. In Tab 1 bleibt das Fruehsignal für EPS-Revisionen unberührt.
- **Korrektur Dividenden-Steigerungslogik:**
  - Die Serie der jährlichen Dividendenerhöhungen (Streak) bezieht das aktuelle Kalenderjahr / TTM mit ein. Liegt die Ausschüttung des laufenden Jahres unter dem Vorjahr, wird der Streak sofort auf `0` gesetzt.
- **Cache-Refresh:**
  - Bereitstellung einer Funktion zur gezielten Invalidierung und Neuabfrage von Einzelwerten in der Detailbox.

---

## 3. Architektur-Entscheidungen (ADR)
- **ADR-001: Tab-basierte Navigation statt monolithischer Expander:**
  - *Status:* Angenommen.
  - *Kontext:* Frühere Ansätze luden alle Profil-, KGV-, Dividenden- und Finanzdaten untereinander in die Detailbox, was zu Scroll-Überlastung führte.
  - *Entscheidung:* Einsatz von `st.tabs(["🔥 Brodel-Index Kalkulation", "🏢 Unternehmenswerte"])` sorgt für sofortige Übersicht und thematische Kapselung.
- **ADR-002: Yfinance-Jahresabschlüsse für Bruttogewinn-Historie:**
  - *Status:* Angenommen.
  - *Entscheidung:* Auswertung von `ticker.income_stmt` mit Fallback auf sichere Dataframe-Extraktion. Caching via `@st.cache_data(persist="disk")` verhindert API-Rate-Limits.
- **ADR-003: Erweiterung von INDEX_DEFINITIONS für List-Parser & Offizielle APIs:**
  - *Status:* Angenommen.
  - *Entscheidung:* Unterstützung von Indizes mit Listen-Parsing (Wikipedia SOX) sowie direkter Nasdaq-WeightingData-API (NBI) mit statischen Fallback-Sets.
- **ADR-004: Persistentes Klarnamen-Mapping für internationale/numerische Indizes (Nikkei 225):**
  - *Status:* Angenommen.
  - *Entscheidung:* Festes Wörterbuch aller 225 Nikkei-Titel verhindert unleserliche Zahlencodes bei Yahoo-Throttling oder Neustarts.
- **ADR-005: Headless/Background Watchlist Management:**
  - *Status:* Angenommen.
  - *Kontext:* Die manuelle Watchlist-Verwaltung im UI erzeugte unnötige Komplexität und temporäre Upload-Fragmente.
  - *Entscheidung:* Vollständige Verlagerung der Watchlist-Konfiguration in die Hintergrunddatei `watchlists/meine_watchlist.txt`. Entfernung des Watchlist-Tabs aus dem Streamlit-Interface.
- **ADR-006: Idempotente Tages-Snapshots & 10-Jahres-Rollierung (3665 Tage):**
  - *Status:* Angenommen.
  - *Kontext:* Manuelle Snapshots und kurzzeitige Limits verhinderten langfristig belastbare Backtests und führten bei häufigem Klicken zu Datenfragmentierung.
  - *Entscheidung:* Automatische Speicherung bei Signal-Aktualisierung mit Ersetzung des bestehenden Eintrags bei identischem Kalendertag (UTC `YYYY-MM-DD`). Erweiterung des Rollierungs-Limits auf 3665 Snapshots (ca. 10 Jahre Historie).
- **ADR-007: Detaillierte Extraktion operativer Kosten (OpEx, F&E, SG&A) aus Jahresabschlüssen:**
  - *Status:* Angenommen.
  - *Kontext:* Bruttomargen allein verdeutlichen nicht, wie viel Kapital in zukünftiges Wachstum (F&E) investiert wird oder für die Verwaltung aufgewendet werden muss.
  - *Entscheidung:* Extraktion von `Operating Expense`, `Research And Development`, `Selling General And Administration` und `Operating Income` aus `ticker.income_stmt`. Robuste Quotenberechnung relativ zum Umsatz und Visualisierung über gestapelte Säulen-Charts im Unternehmenswerte-Tab.
- **ADR-008: Read-Only Signal Monitor mit Event-basierter Zeilenselektion & strikter Trennung von Berechnungs-Jobs:**
  - *Status:* Angenommen.
  - *Kontext:* Das Triggern manueller Berechnungen direkt im Monitor verlangsamt die Nutzung und erzeugt Fehlbedienungen. Ebenso war die Auswahl von Detailaktien über eine separate Dropdown-Liste unkomfortabel.
  - *Entscheidung:* Der Signal Monitor lädt standardmäßig direkt den letzten Snapshot im Read-Only-Modus. Zeilenklicks steuern per Session-State direkt die Detail-Box. Manuelle Neuberechnungen werden in den Reiter `Backtest & ML` verschoben.
- **ADR-009: Maßgeschneidertes Tabellen-Widget ohne Checkboxen für nahtlose Zeilenauswahl (Option C):**
  - *Status:* Angenommen.
  - *Kontext:* Die native Streamlit-Funktion `st.dataframe(..., on_select="rerun")` rendert auf dem Canvas zwingend eine Checkbox-Spalte ganz links. Klicks auf Textzellen fokussieren lediglich die Zelle statt die Zeile auszuwählen; nur Klicks auf das Kästchen triggerten die Zeile, was unintuitiv wirkte.
  - *Entscheidung:* Bereitstellung einer maßgeschneiderten Streamlit-Komponente (`interactive_table`) via `streamlit.components.v1.declare_component`. Das Widget rendert eine professionelle Finanztabelle:
    - 100% frei von Checkboxen.
    - Klick auf jede beliebige Spalte/Zelle einer Zeile selektiert die Aktie sofort und meldet das Symbol an Python (`Streamlit.setComponentValue`).
    - Visuelles Feedback über Zeilen-Hover und aktive Zeilenhervorhebung.
    - Sticky-Header mit fixem Scrollbereich (450px) für maximale Übersicht auch bei Hunderten Werten.
    - Integriertes Live-Filter-/Suchfeld im Tabellenkopf.
    - Graceful Fallback auf `st.dataframe` ohne Selektion, falls die Komponente nicht verfügbar ist.


