# 📈 StockWatcher – Aktien-Score und Spieldepots

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
- **🏠 Start:** erklärt das System und zeigt Datenstand, Spieldepots und die besten Aktien.
- **📊 Marktbeobachtung:** Rangliste nach Rang-Score und Punkte-Score, Detailansicht je Aktie, Score-Verlauf.
- **💼 Trades:** drei Spieldepots (Paper-Trading mit Stop-Loss) gegen einen MSCI-World-ETF.
- **❓ Hilfe:** Berechnung der Scores im Detail.
- **🔬 Forschung:** Historische Rebalancing-Simulation, Score-Range-Backtest, ML-Gewichtungstraining und Datenpflege.
- **Hilfe & Methodik:** Dokumentation der 10 Signalkomponenten, Schwellwerte und Handlungslogik.

## 📊 Marktbeobachtung

Die Marktbeobachtung die Watchlist nach Frühsignalen priorisiert.

Bewertet werden aktuell:

1. EPS-Revisionen
2. Kursziel-Potenzial relativ zum aktuellen Kurs
3. Preis- und Volumen-Auffaelligkeiten
4. News-Dichte der letzten Tage
5. Naehe zum naechsten relevanten Termin

Aus diesen Bausteinen wird der `Punkte-Score` berechnet (dazu der `Rang-Score` aus 6 Bausteinen), damit interessante Aktien schneller oben landen.

Zusätzlich unterstützt das System:

1. Automatische, idempotente Tages-Snapshot-Speicherung im Ordner `signal_history/` (bis zu 3665 Tage / ca. 10 Jahre Historie)
2. Peer- und Sektor-Vergleiche innerhalb der geladenen Watchlist
3. Score-Verlauf pro Symbol auf Basis der gespeicherten Snapshots
4. Automatische Strategie-Erkennung (Pullback, Breakout, Value, Momentum)

## Hilfe in der App

Die Seite `Hilfe & Methodik` enthaelt eine eingebaute Hilfe-Sektion, die erklaert:

1. Wie der Aktien-Score gelesen wird
2. Was die einzelnen Signal-Bausteine bedeuten
3. Wie Peer-Vergleiche und Strategie-Setups zu interpretieren sind

# Hinweise

Die Daten fuer den Aktien-Agenten kommen aus frei verfuegbaren Yahoo-Finance-Endpunkten via `yfinance`. Nicht jeder Datenpunkt ist fuer jeden Ticker verfuegbar. Fuer ETFs sind Insiderdaten in der Regel nicht relevant.

## Wahrheitsmaschine: Schlägt das System einen ETF?

Das Paket `factor_lab/` testet kursbasierte Faktoren über bis zu 20 Jahre gegen einen ETF. Es rechnet mit Transaktionskosten, deutscher Abgeltungssteuer samt Verlusttopf und Sparerpauschbetrag sowie einem Trendfilter für die Investitionsquote. Der ETF wird mit 30 Prozent Teilfreistellung erst beim Verkauf besteuert.

Zugang über die Seite **Forschung** in der App oder per Kommandozeile:

```powershell
# Momentum und Low-Volatility, Top 20, S&P 500 gegen SPY ab 2005
.\.venv\Scripts\python.exe -m factor_lab --universe "S&P 500" --benchmark SPY --start 2004-01-01

# Andere Faktoren; jede getestete Variante in --n-trials mitzählen
.\.venv\Scripts\python.exe -m factor_lab --factors momentum_12_1 --n-trials 3

# Gespeicherte Aktien-Scores gegen die Folgerenditen messen
.\.venv\Scripts\python.exe -m factor_lab --brodel --horizon-days 21
```

Berichte und Kurs-Cache landen in `cache/factor_lab/`. Wichtigste Grenze: Das Universum besteht aus heutigen Indexmitgliedern, was rückblickend die Gewinner bevorzugt.

ML-Gewichte für den Punkte-Score werden nur noch angewendet, wenn sie auf einem zeitlich getrennten Testzeitraum die Gleichgewichtung schlagen. Dafür sind mindestens 60 Snapshot-Tage nötig.

## Wochencheck (Sonntag)

Der Workflow `weekly_check.yml` läuft jeden Sonntag um 10:00 UTC, wenn kein Nachtlauf ansteht:

1. alle Unit-Tests mit frisch installierten Bibliotheken (wie im Nachtlauf, also neueste yfinance-Version),
2. `python system_check.py`: jede externe Verbindung einmal echt abgefragt und mit dem Code des Nachtlaufs gelesen (Yahoo, Finnhub, Gemini, Index-Listen, Insider-Quellen), drei Aktien komplett durch den Nachtlauf, die App-Adresse, alle App-Seiten mit den Daten im Repository, die Snapshots und Bot-Werte der Woche.

Schlägt eine Pflichtprüfung fehl, schlägt der Lauf fehl, und der Workflow legt ein Issue mit Label `wochencheck` und dem Bericht an (oder ergänzt das offene). GitHub schickt für beides eine E-Mail. Lokal: `python system_check.py` oder `python -m pytest tests/live --live -q`. Ein normales `pytest` überspringt die Live-Tests.
