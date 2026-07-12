# PCS NEO Dashboard

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

## Gespeicherte Watchlists und Alerts

Gespeicherte Watchlists liegen im Projektordner `watchlists/` und koennen direkt in der App geladen oder ueberschrieben werden.

Beim Start wird automatisch `meine_watchlist.txt` geladen, sofern die Datei im Ordner `watchlists/` vorhanden ist.

Aktuell unterstuetzte Index-Aliase:

1. DAX
2. S&P 500
3. Dow Jones

Die App bietet zusaetzlich eine Alert-Funktion fuer:

1. Neue Analysten-Upgrades oder Downgrades
2. Insiderkaeufe oder Insidertransaktionen
3. Anstehende Termine innerhalb eines einstellbaren Zeitfensters

Watchlists koennen in der App als `.txt`-Dateien gespeichert und spaeter wiederverwendet werden.

## Signal Monitor V2

Die App enthaelt zusaetzlich einen `Signal Monitor V2`, der die Watchlist nach Fruehsignalen priorisiert.

Bewertet werden aktuell:

1. EPS-Revisionen
2. Kursziel-Potenzial relativ zum aktuellen Kurs
3. Preis- und Volumen-Auffaelligkeiten
4. News-Dichte der letzten Tage
5. Naehe zum naechsten relevanten Termin

Aus diesen Bausteinen wird ein `Brodel-Score` berechnet, damit interessante Aktien schneller oben landen.

Zusaetzlich unterstuetzt V2 jetzt:

1. Snapshot-Speicherung des Signal Monitors im Ordner `signal_history/`
2. Delta-Alerts seit dem letzten Snapshot
3. Peer- und Sektor-Vergleiche innerhalb der geladenen Watchlist
4. Score-Verlauf pro Symbol auf Basis der gespeicherten Snapshots
5. Harte Delta-Alerts ab konfigurierbarem Schwellwert

## Hilfe in der App

Die Seite `Signal Monitor V2` enthaelt eine eingebaute Hilfe-Sektion, die erklaert:

1. Wie der Brodel-Score gelesen wird
2. Was die einzelnen Signal-Bausteine bedeuten
3. Wie Delta-Alerts und Peer-Vergleiche zu interpretieren sind

# Hinweise

Die Daten fuer den Aktien-Agenten kommen aus frei verfuegbaren Yahoo-Finance-Endpunkten via `yfinance`. Nicht jeder Datenpunkt ist fuer jeden Ticker verfuegbar. Fuer ETFs sind Insiderdaten in der Regel nicht relevant.