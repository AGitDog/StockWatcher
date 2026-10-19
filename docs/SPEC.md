# PCS NEO – StockWatcher: System-Spezifikation (SPEC.md)

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

