# 🔥 Brodel-Radar – Quantitative Marktbeobachtung

Dieses Repository enthaelt eine Streamlit-Anwendung fuer einen Aktien-Agenten, der Watchlists aus Textdateien einliest und pro Aktie oder ETF Kurzlagen, Alerts und Fruehsignale erzeugt.

# Getting Started

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## App starten

```powershell
streamlit run app.py
```

## Watchlist-Format fuer den Aktien-Agenten

Die erste Agenten-Funktion erwartet eine Textdatei oder Freitext mit Tickern, zum Beispiel:

```text
MSFT
AAPL
SPY
QQQ
# Kommentare sind erlaubt
SAP.DE, VUSA.DE
```

Der Agent erstellt pro Symbol eine Zusammenfassung mit Fokus auf:

1. Aktuelle News-Lage
2. Insiderkaeufe oder Insidertransaktionen, falls verfuegbar
3. Analysten-Upgrades und Downgrades
4. Naechste Termine wie Earnings oder Dividenden

Bekannte Indexnamen koennen direkt in die Watchlist geschrieben werden. Beispiel:

```text
DAX
NVDA
HON
```

Dann erweitert die App `DAX` automatisch auf alle DAX-Mitglieder und analysiert sie zusammen mit den anderen Eintraegen.

## Manuelle Symbol-Zuordnung

Wenn die Watchlist Namen statt Ticker enthaelt oder ein Name mehrdeutig ist, kann er in `stock_mappings.txt` hinterlegt werden:

```text
Palantir Technologies=PLTR
Appen=APX.AX
# L&G Hydrogen Economy (Acc)=TICKER_HIER_EINTRAGEN
```

Die Datei wird beim Erstellen der Zusammenfassung automatisch beruecksichtigt.

## Watchlists und Hintergrundverwaltung

Die Watchlist-Verwaltung erfolgt headless im Hintergrund über Textdateien im Projektordner `watchlists/`. Standardmäßig lädt und überwacht das System automatisch die Datei `watchlists/meine_watchlist.txt`.

Unterstützte Index-Aliase (werden automatisch in Einzelwerte aufgelöst):

1. **DAX**
2. **S&P 500**
3. **Dow Jones**
4. **NASDAQ-100**
5. **MDAX**
6. **CAC 40**
7. **EURO STOXX 50**
8. **FTSE 100**
9. **SMI**
10. **NIFTY 50**
11. **TSX 60**
12. **TECDAX**
13. **PHLX Semiconductor Sector (SOX)**
14. **NASDAQ Biotechnology Index (NBI)**
15. **Nikkei 225**

Die App bietet zusätzlich eine Alert-Funktion für:

1. Neue Analysten-Upgrades oder Downgrades
2. Insiderkäufe oder Insidertransaktionen
3. Anstehende Termine innerhalb eines einstellbaren Zeitfensters

## Aufbau der Anwendung

Die Anwendung gliedert sich in 3 fokussierte Tabs:
- **🔥 Signal Monitor:** Frühwarnsignale, Sektor-Rankings, ML-Scores, automatisierte Tages-Snapshots und zweigeteilte Detailansicht (Brodel-Index & Unternehmenswerte).
- **Backtest & ML:** Historische Rebalancing-Simulation, Score-Range-Backtest, ML-Gewichtungstraining und Datenpflege.
- **Hilfe & Methodik:** Dokumentation der 10 Signalkomponenten, Schwellwerte und Handlungslogik.

## 🔥 Signal Monitor

Die App enthält einen `Signal Monitor`, der die Watchlist nach Frühsignalen priorisiert.

Bewertet werden aktuell:

1. EPS-Revisionen
2. Kursziel-Potenzial relativ zum aktuellen Kurs
3. Preis- und Volumen-Auffaelligkeiten
4. News-Dichte der letzten Tage
5. Naehe zum naechsten relevanten Termin

Aus diesen Bausteinen wird ein `Brodel-Score` berechnet, damit interessante Aktien schneller oben landen.

Zusätzlich unterstützt das System:

1. Automatische, idempotente Tages-Snapshot-Speicherung im Ordner `signal_history/` (bis zu 3665 Tage / ca. 10 Jahre Historie)
2. Peer- und Sektor-Vergleiche innerhalb der geladenen Watchlist
3. Score-Verlauf pro Symbol auf Basis der gespeicherten Snapshots
4. Automatische Strategie-Erkennung (Pullback, Breakout, Value, Momentum)

## Hilfe in der App

Die Seite `Hilfe & Methodik` enthaelt eine eingebaute Hilfe-Sektion, die erklaert:

1. Wie der Brodel-Score gelesen wird
2. Was die einzelnen Signal-Bausteine bedeuten
3. Wie Peer-Vergleiche und Strategie-Setups zu interpretieren sind

# Hinweise

Die Daten fuer den Aktien-Agenten kommen aus frei verfuegbaren Yahoo-Finance-Endpunkten via `yfinance`. Nicht jeder Datenpunkt ist fuer jeden Ticker verfuegbar. Fuer ETFs sind Insiderdaten in der Regel nicht relevant.