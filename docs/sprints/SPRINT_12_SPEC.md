# Sprint 12 Spezifikation: Insider-Daten außerhalb der USA

**Sprint-Status:** Abgeschlossen (Phase 3: Implementation)
**Erstellt am:** 11.11.2026
**Freigabe:** Im Chat: „Setze den Plan von vorhin um und prüfe für alle anderen Länder, welche Optionen es gibt, um kostenlos an Insider-Daten zu kommen.“
**Ziel:** Der Insider-Baustein des Rang-Scores soll keine Region bevorzugen, und es sollen alle erlaubten kostenlosen Quellen genutzt werden.

## 1. Befund
- **Verzerrung:** US-Aktien ohne Insider-Käufe bekamen beim Insider-Baustein neutral 5 von 10 Punkten. Bei Aktien ohne Datenquelle (Europa, Asien) fiel der Baustein dagegen ganz weg. Starke Aktien ohne Daten behielten so ihren hohen Schnitt, gleich starke US-Aktien wurden zur Mitte gezogen. Unter den besten 2 % (27 Aktien) waren am 10.11. 4 europäische, ohne die Verzerrung wäre es 1.
- **London:** Yahoo liefert für .L echte Insider-Meldungen („Bought at price …“). Der Code las Insider-Daten aber nur für US-Symbole und erkannte nur den US-Wortlaut „Purchase …“.
- **Punkte-Score:** Der Yahoo-Fallback zählte „Buy Back“ (Rückkauf der Firma) als Insider-Kauf. UK-Verkäufe („Sold at price“) zählte er gar nicht. Die Finnhub-Zeile „0 Käufe, 4 Verkäufe“ nannte Stufen statt Anzahlen.
- **Deutschland:** Die BaFin-Datenbank „Directors' Dealings“ hat einen CSV-Export. Ihre robots.txt verbietet aber jeden automatischen Zugriff (`Disallow: /`). EQS News und das Unternehmensregister sperren Scraper ebenfalls.

## 2. Änderungen
- **Neutral-Regel** (`brodel_v3._insider_rank`): Fehlende Insider-Daten zählen wie „keine Käufe“, also 0,5 bzw. 5 von 10 Punkten. Für die Mindestzahl von 4 Bausteinen zählen nur echte Daten, der neutrale Insider-Wert zählt nicht mit.
- **Neues Modul `insider_sources.py`:**
  - `is_open_market_buy`: US- und UK-Wortlaut, ohne Rückkäufe, Optionen, Zuteilungen und Verkäufe.
  - `yahoo_buy_value`: Käufe der letzten 90 Tage.
  - `to_usd`: Umrechnung in Dollar über Yahoo-Devisenkurse, weil die Schwelle bei 100.000 $ liegt.
  - `bafin_buy_value_eur`: liest die von Hand gespeicherte Datei `insider_data/bafin.csv` (nur Aktien, Art „Kauf“, in EUR). Die Zuordnung läuft über den normalisierten Firmennamen. Findet sich die Firma nicht, gilt „keine Käufe“ und damit neutral. Eine falsche Zuordnung kann also nur einen Bonus verlieren, nie Punkte kosten.
- **`collect_v3_factors`:** USA wie bisher. Für .L kommen die Werte aus Yahoo, für .DE aus der BaFin-Datei, falls vorhanden. Neues Feld `insider_source`.
- **Punkte-Score:** Rückkäufe zählen nicht mehr als Insider-Kauf, „Sold“ zählt als Verkauf. Finnhub-Text: „3 Monate netto: keine Käufe, Verkäufe über 100 Aktien“.
- **App:** Die Detailzeile nennt Quelle bzw. „keine Daten für dieses Land = neutral“. Hilfe, Rechenbeispiel und Tooltip sind angepasst.

## 3. BaFin-Datei von Hand (optional)
1. Im Browser die BaFin-Datenbank „Directors' Dealings“ öffnen und ohne Emittent mit dem Zeitraum „letzte 3 Monate“ suchen.
2. Das Ergebnis als CSV exportieren und als `insider_data/bafin.csv` ins Repository legen (committen).
3. Der Nachtlauf nutzt die Datei für die deutschen Aktien. Wöchentlich zu aktualisieren reicht, weil das Fenster 90 Tage umfasst.

## 4. Recherche weitere Länder (11.11.2026)

| Markt | Aktien | Quelle | Automatisierbar | Bewertung |
|---|---|---|---|---|
| Kanada .TO | 59 | Yahoo („Acquisition in the public market“) | ja | lohnend, geringer Aufwand |
| Indien .NS | 50 | NSE-JSON `corporates-pit` | robots erlaubt; NSE sperrt oft Cloud-IPs | lohnend, Risiko auf GitHub |
| Schweiz .SW | 20 | SIX `management_transactions` JSON | robots erlaubt | lohnend, ISIN-Zuordnung |
| Frankreich .PA | 39 | AMF BDIF | erlaubt, Details nur als PDF | aufwendig |
| Spanien .MC, Australien .AX | 5 | Yahoo | ja | gleicher Code wie UK |
| Niederlande .AS | 6 | AFM-Register | erlaubt | optional |
| Japan .T | 224 | – | – | kein öffentliches Register für Vorstandskäufe |
| Italien, Finnland, Belgien | 9 | nur PDF/HTML bzw. gesperrt | – | lohnt nicht |

Kommerzielle Dienste (EODHD, FMP, Twelve Data, Alpha Vantage) bieten kostenlos nur US-Daten. Insiderscreener und Marketscreener sperren automatischen Zugriff.

## 5. Auswirkung auf das Rang-Depot
Die gekauften Positionen bleiben. Neue Käufe folgen ab dem Nachtlauf vom 11.11.2026 der neuen Regel.

## 6. Tests
372 grün. Neu: `tests/test_insider_sources.py` (Wortlaut, Rückkäufe, Namensabgleich, BaFin-Datei, Dollar-Umrechnung, Quelle je Land). Dazu Neutral-Regel und Mindestbausteine in `test_brodel_v3.py` und die Detailzeile ohne Daten in `test_brodel_v2.py`. Live geprüft: HSBA.L mit 654.000 $ Insider-Käufen (Quelle Yahoo).

## 7. Nachtrag 11.11.2026: alle freien Quellen und eine wöchentliche Prüfung
Freigabe im Chat: „Ja, dann gehe alle an, die möglich sind. Mehr Daten heißt auch bessere Daten. Und ganz wichtig: Implementiere für alles Tests, die das Ganze regelmäßig überprüfen.“

| Markt | Aktien | Quelle | Ergebnis |
|---|---|---|---|
| Schweiz | 20 | SIX `management_transactions` (JSON, ein Abruf pro Lauf) | ✅ Käufe von Aktien durch natürliche Personen, ohne Optionen, Vesting, Mitarbeiterpläne; Korrekturen ersetzen die Erstmeldung, Doppelmeldungen zählen einmal |
| Frankreich | 39 | AMF BDIF: Liste (JSON) + PDF je Meldung (`pypdf`) | ✅ „Acquisition“ von „Action“ ohne Options- und Gratisaktien-Programm; ausgelesene PDFs in `insider_data/amf_cache.json` |
| Niederlande | 6 | AFM-Register MAR 19: Suche + Detailseite | ✅ „Koop“ von „Gewoon aandeel“ ohne Optionsprogramm; Cache `insider_data/afm_cache.json`. Das Register enthält z. B. keine ASML-Meldungen |
| Kanada, Spanien, Australien, Italien u. a. | ~70 | Yahoo | ✅ zusätzlich der SEDI-Wortlaut „Acquisition in the public market“ |
| Indien | 50 | NSE | ❌ ohne Browser-Sitzung nur veraltete Daten (2021–2024, Wert 0). Die Bot-Sperre zu umgehen, kommt nicht in Frage. Neutral |
| Japan | 224 | – | ❌ kein öffentliches Register für Vorstandskäufe. Neutral |

- **Ein Einstieg:** `insider_sources.insider_value_usd(symbol, info, yahoo_value)` wählt die Quelle je Markt. Fällt die Behördenquelle aus, springt Yahoo ein, sonst gilt neutral. Ein Fehler in einer Quelle führt nie zum Abbruch des Laufs.
- **Höflich und threadsicher:** 0,3 s Pause je Abruf. SIX- und AMF-Liste werden einmal pro Lauf geladen (Lock), die Caches sind mit einem Lock geschützt. Meldungen älter als 120 Tage fallen aus den Caches.
- **Nachtlauf:** committet zusätzlich `insider_data/`. Neue Abhängigkeit `pypdf`.
- **BRK.B** gilt als US-Aktie (Aktienklasse, keine Börse).

### Regelmäßige Prüfung
- **Unit-Tests** (`tests/test_insider_sources.py`, `tests/test_insider_check.py`): jede Quelle mit Beispieldaten im echten Format (`tests/fixtures/insider/`), Filter für Rückkäufe, Optionen, Korrekturen, Doppelmeldungen, Zeitfenster, Namensabgleich, Währungen, Cache, Ausfall einer Quelle. `tests/conftest.py` sperrt in allen Tests Netzabrufe und Live-Wechselkurse.
- **Wöchentlicher Live-Check** (`insider_check.py`, Workflow `insider_sources_check.yml`, montags 07:00 UTC und von Hand): fragt jede Quelle echt ab und liest die Antwort mit dem Code des Nachtlaufs. Geprüft werden SIX, AMF (PDF lesbar), AFM (Detail lesbar), Yahoo, Finnhub und die Wechselkurse. Dazu kommt die Abdeckung im letzten Snapshot: Jeder Markt mit Quelle braucht Daten. Fällt eine Quelle aus oder ändert ihr Format, schlägt der Lauf fehl, und GitHub schickt eine E-Mail. Ist die BaFin-Datei älter als 3 Wochen, gibt es nur eine Warnung.
- Erster Live-Lauf am 11.11.2026: alle Quellen ✅.

**Tests:** 401 grün.

## 8. Nachtrag 11.11.2026: „Punkte alt“ entfernt
Freigabe im Chat: „Punkte alt ist nur noch aus historischen Gründen drin, wird aber nicht benutzt. Wenn das korrekt ist, bitte entfernen.“
- Geprüft: Die erste Punkte-Version wurde nur noch angezeigt (Spalte „Punkte alt“ in der Detailtabelle, Zeile „Punkte-Score alt“ im Score-Prüfstand). Rang-Score, Punkte-Score, Paper-Bot und Rang-Depot nutzen sie nicht.
- Entfernt: beide Anzeigen. Die gespeicherten Rohwerte (`signal_breakdown`, `brodel_score`) bleiben, weil der Punkte-Score älterer Snapshots daraus nachgerechnet wird.
- Tests: `test_brodel_v2.py` prüft, dass die Spalte fehlt und der Prüfstand nur den Punkte-Score misst. 401 grün.

## 9. Nachtrag 11.11.2026: Deutschland über Tracefour
Freigabe im Chat: „Was ist mit Tracefour? Hier kann man auch Daten holen in Deutschland.“
- **Prüfung:** Tracefour bietet eine dokumentierte, kostenlose API ohne Schlüssel (`https://tracefour.com/v1/eu/de`, 60 Abrufe pro Stunde je IP). Die robots.txt sperrt nur `/api/` und `/embed/`, nicht `/v1/`. Die Daten stehen unter CC BY 4.0: Wo sie angezeigt werden, steht ein Link auf Tracefour. Tracefour gibt an, die Nutzungsbedingungen der BaFin selbst nicht geprüft zu haben.
- **Inhalt:** BaFin-Meldungen der letzten rund 90 Tage mit Emittent, ISIN, Art (Buy/Sell), Wert und Währung. Am 11.11. waren es 202 Meldungen, darunter 23 unserer 99 deutschen Aktien (z. B. SAP, adidas, Fresenius).
- **Code:** `parse_tracefour_filings` (nur „Buy“ in EUR mit positivem Wert, doppelte Meldungen einmal), `tracefour_purchases` (ein Abruf pro Lauf), `germany_buy_value_eur` (Tracefour zuerst, die BaFin-Datei nur als Ersatz). Ein leerer Feed gilt als Ausfall, nicht als „keine Käufe“.
- **Live-Check:** neue Prüfung „Tracefour Deutschland“. In der Abdeckung erwartet der Check für .DE jetzt Daten.
- **Tests:** `tests/fixtures/insider/tracefour_de.json` (echte Meldungen, Personennamen anonymisiert), Filter, ein Abruf pro Lauf, 90-Tage-Fenster, Ausfall (429, leer), Ersatz durch die BaFin-Datei, Probe des Live-Checks.

## 10. Nachtrag 11.11.2026: Hilfe und Startseite
Freigabe im Chat: „Bitte auch die gesamte Hilfe anpassen wegen den Punkten alt. Es soll nur einen Punkte-Score geben.“ Dazu: „Datenquellen und Caching auch sauber aktualisieren. Insgesamt könnte man die Hilfe besser lesbar machen. Bitte auch nochmals die Einstiegsseite überprüfen.“
- **Hilfe in sechs Reitern:** Überblick, Rang-Score, Punkte-Score, Spieldepots, Forschung, Datenquellen. Vorne stehen Übersichtstabellen, Details sind aufklappbar.
- **Nur noch ein Punkte-Score:** Abschnitt „was sich geändert hat“, alle „alt/neu“-Angaben und die alten Regeln sind entfernt. Die Übersicht der 11 Bausteine kommt aus `BRODEL_V2_MAX_POINTS`.
- **Entfernt, weil nicht mehr sichtbar oder falsch:** Makro-Overlay (galt nur für die alte Version), FRED als Quelle, Strategie-Setups (nirgends angezeigt), „Die drei Tabs“ (die App hat fünf Seiten), Skala „−30 bis 100“ (Maximum ist 90).
- **Datenquellen:** Tabelle mit Quelle, Zweck und Aktualität, darunter alle Insider-Quellen und Tracefour mit Lizenzhinweis.
- **Startseite:** Aktienzahl aus dem Snapshot statt fest „1.375“. Der Nachtlauf startet nach US-Börsenschluss, nicht nach jeder Region. Punkte-Score „−30 bis 90“ ohne „ältere Methode“. „Zwei davon verkaufen per Stop-Loss“. Das beste Spieldepot nennt seinen Namen. Rang-Scores auf eine Nachkommastelle.
- **Tests:** neu `tests/test_help_page.py`, angepasst `test_brodel_v2.py` und `test_truth_machine_app.py`. 413 grün.

## 11. Nachtrag 11.11.2026: Sitz der Firma statt Börsenplatz
Freigabe im Chat: „Ja bitte“ (PTX.F beheben, niederländische Firmen an der Pariser Börse über die AFM).
- **Befund:** Airbus, Stellantis, STMicro und Euronext (Paris), Qiagen und Redcare (Xetra) und Ferrari (Mailand) sind niederländische Gesellschaften und melden bei der AFM, nicht bei AMF oder BaFin. PTX.F ist Palantir, eine US-Firma mit Frankfurter Zweitnotierung.
- **Regeln in `insider_value_usd`:** US-Firma an einer ausländischen Börse → Yahoo (zeigt die SEC-Meldungen, Werte in USD). Niederländische Gesellschaft (Sitz Niederlande oder Rechtsform N.V.) → AFM, bei Ausfall die Quelle des Börsenplatzes. Frankfurt und die deutschen Regionalbörsen gelten wie Xetra.
- **Prüfung Frankreich:** 13 von 39 Aktien mit Käufen in 90 Tagen. 17 haben nur Meldungen ohne echte Käufe (Mitarbeiterfonds, Gratisaktien, Schenkungen, Verkäufe), 9 keine AMF-Meldung. Der Namensabgleich fand jede Firma mit Meldungen.
- **Tests:** Erkennung niederländischer Firmen, Airbus über AFM mit Ersatz AMF, Frankfurt-Notierungen (deutsch und US). 421 grün.
