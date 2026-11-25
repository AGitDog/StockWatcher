# Sprint 13 Spezifikation: Wochencheck am Sonntag

**Sprint-Status:** Abgeschlossen (Phase 3: Implementation)
**Erstellt am:** 11.11.2026
**Freigabe:** Im Chat: Plan „Wochencheck“ mit 1. Sonntag 10:00 UTC, 2. App-Prüfung mit der Streamlit-Adresse, 3. Issue mit Fehlerbericht, 4. FRED entfernen. „Bitte alles wie geplant umsetzen.“
**Ziel:** Einmal pro Woche, wenn keine Daten abgefragt werden, prüfen, dass jede Verbindung und jeder Teil des Systems im Betrieb funktioniert. Bei Fehlern kommt eine E-Mail.

## 1. Ausgangslage
- Nachtlauf Mo–Fr 21:35 UTC, Ersatzlauf Di–Sa 03:35 UTC. Die Insider-Prüfung lief montags.
- Kein Workflow ließ die Unit-Tests laufen. Der Nachtlauf installiert die Bibliotheken ohne feste Version neu, Änderungen bei yfinance fielen erst im Nachtlauf auf.

## 2. Umsetzung
- **`system_check.py`:** Proben mit Bereich, Name, Ergebnis und Detail. Jede Live-Probe bekommt nach 20 s einen zweiten Versuch. Pflicht-Proben lassen den Lauf fehlschlagen, Neben-Proben warnen nur.

| Bereich | Probe | Pflicht |
|---|---|---|
| Yahoo | Kurse je Region (USA, DE, London, Tokio, Indien, Kanada, Schweiz), Tageskerzen des Paper-Bots, Stammdaten-Felder, Analysten (Revisionen, Kursziele, Empfehlungen, Hoch-/Herabstufungen), News/Termine/Aktienanzahl/GuV/Dividenden, Insider-Tabellen, Symbolsuche, Wechselkurse (EUR, GBP, CHF, CAD, JPY, INR) | ja |
| Finnhub | Empfehlungen, Insider-Geschäfte, Insider-Stimmung | ja |
| Alpha Vantage | Fundamentaldaten | Warnung |
| Gemini | News-Stimmung mit `gemini-flash-latest` | Warnung |
| Indizes | alle 15 Index-Listen mit mindestens 80 % der Mitglieder | ja |
| Insider | Tracefour, SIX, AMF, AFM | ja |
| Nachtlauf | AAPL, SAP.DE, 7203.T komplett: frische Kurse, mindestens 4 Rang-Score-Bausteine, Punkte-Score | ja |
| App | Adresse antwortet (Streamlit-Login-Weiterleitung gilt als erreichbar, die App ist privat), alle 5 Seiten rendern mit den Repository-Daten und zeigen ihren Inhalt | ja |
| Woche | Snapshots: mindestens 4 von 5 Handelstagen mit 90 % frischen Daten und allen 5 Gruppen; Paper-Bot: Depotwert an mindestens 4 von 5 Tagen; Insider-Abdeckung | ja |
| Woche | BaFin-Ersatzdatei, Größe der Datenordner | Warnung |

- **Workflow `weekly_check.yml`:** Sonntag 10:00 UTC und von Hand. Installation wie im Nachtlauf, alle Unit-Tests, dann `system_check.py`. Bei einem Fehler legt er ein Issue mit Label `wochencheck` und dem Bericht an oder kommentiert das offene, danach schlägt der Lauf fehl. GitHub mailt für beides.
- **`insider_sources_check.yml` entfernt:** Die Insider-Proben laufen im Wochencheck.
- **pytest:** `tests/live/` enthält jede Probe als Testfall. Er läuft nur mit `--live`, ein normales `pytest` überspringt ihn. `tests/live/conftest.py` hebt dort die Netzsperre auf.
- **FRED entfernt:** `fred_cache.py`, der Test dazu, der Zinskurven-Faktor im Makro-Overlay der alten Punkte-Version und `FRED_API_KEY` in den Workflows. Das Overlay wirkt nur noch auf den nicht angezeigten `brodel_score`.
- **Texte:** Hilfe (Datenquellen, Insider) und README nennen den Wochencheck.

## 3. Befunde beim ersten Lauf (11.11.2026, lokal)
- **Finnhub Kursziele:** `stock/price-target` antwortet mit dem kostenlosen Schlüssel immer mit 403 (nur im Bezahl-Abo). Die App nimmt die Kursziele von Yahoo, der Abruf kostet aber pro Aktie einen Platz im Limit von 55 Abrufen je Minute. Nicht Teil der Probe.
- **Alpha Vantage:** `OVERVIEW` ist inzwischen ein Premium-Endpunkt. Es kommen keine Daten, die App nutzt Yahoo. Die Probe warnt deshalb jede Woche.
- **yfinance 0.2.65 (lokal):** `get_news` meldet „Yahoo is down“. Mit 1.8.0, die der Nachtlauf installiert, funktioniert es.
- **Woche 02.–06.11.:** An 3 Tagen nur 22–25 % frische Daten (Yahoo-Drosselung, bekannt) und Bot-Werte erst ab dem Start am 05.11. Die Probe hätte das gemeldet.
- Alle anderen Proben ✅.

## 4. Tests
`tests/test_system_check.py`: zweiter Versuch, Absturz als Fehler, letzte Woche, Snapshots mit einem schlechten Tag, Bot-Werte, Probleme im Nachtlauf, App-Weiterleitung, Bericht und Exit-Code, jede Quelle hat eine Probe, der Workflow ersetzt die Montags-Prüfung, FRED ist aus allen Workflows entfernt. 431 grün, 24 Live-Tests übersprungen.

## 5. Tote Abrufe entfernt
- **Finnhub-Kursziele:** `finnhub_cache.get_analyst_data` heißt jetzt `get_recommendations` und holt nur noch die Empfehlungen. Der Endpunkt `price-target` antwortet im kostenlosen Plan immer mit 403 und kostete pro Aktie einen Platz im Limit. Kursziele kommen nur noch von Yahoo, wie bisher im Ergebnis.
- **Alpha Vantage:** `alpha_vantage_cache.py`, die Tests, die Probe im Wochencheck, `ALPHAVANTAGE_API_KEY` in den Workflows und in `config_loader` entfernt. `OVERVIEW` ist nur noch im Bezahl-Abo; im Snapshot vom 10.11. stammte kein Wert von Alpha Vantage. Die Fundamentaldaten kommen aus Yahoo.

## 6. Tabelle „Bausteine“ in der Score-Berechnung
- Spalten heißen wie die Scores: **Rang-Score** und **Punkte-Score** (intern vorher „Punkte 3.0“/„Punkte 2.0“). Der Zusatz „(neu in 3.0)“ an Qualität, Bewertung und Momentum entfällt; ihr Punkte-Score ist „–“.
- Detail-Spalte ohne Datenquelle: Kennungen `[YF]`, `[YFinance]`, `[Finnhub]`, `[AV]` werden entfernt (`clean_detail`, gilt auch für alte Snapshots), ebenso der Quellen-Hinweis beim Insider-Baustein. Der Nachtlauf schreibt die Kennungen nicht mehr.
- Umlaute in den Detail-Texten (Rückkauf, Käufe, über, bärisch …) über eine feste Wortliste.
- Hinweis am Ende einheitlich: „Rang-Score 9.3 von 20: besser als 46 % der Vergleichsaktien“, beim Insider „Rang-Score 5.0 von 10: keine Käufe = neutral, nur Käufe zählen, Verkäufe nicht“.
- Bei Aktien mit Insider-Daten von Tracefour steht unter der Tabelle eine Zeile mit Link, weil die Lizenz CC BY 4.0 die Nennung verlangt.
- Tests: `test_breakdown_detail_has_no_source_and_no_version_names`, angepasste Tests in `test_brodel_v2.py` und `test_finnhub_cache.py`.
- Nachtrag: Spieldepot-Diagramm „Punkte-Score ohne Stop-Loss“ statt „2.0 ohne Stop-Loss“, Hilfe zu Kurszielen nennt Yahoo (Kursziele) und Finnhub (Empfehlungen).

## 7. Rang-Score: EPS-Shrinkage und Qualität ohne Eigenkapital (11.11.2026)
- **EPS-Revisionen:** `brodel_v3.eps_up_ratio(up, down) = (up+1)/(up+down+2)`. 2:0 wird 75 %, 18:1 wird 90 %, 18:0 (95 %) liegt vor 4:0 (83 %). Im Snapshot vom 10.11. standen 113 Aktien bei exakt 100 %, die vorher alle denselben Rang hatten. Die Zähler `eps_up`/`eps_down` stehen jetzt in `factors_v3`; für ältere Tage nimmt `_eps_ratio` die Zähler aus `signal_breakdown`, so gilt die Formel im ganzen Verlauf.
- **Qualität:** operative Marge (`operatingMargins`), Gesamtkapitalrendite (`returnOnAssets`) und Free Cashflow zu Gesamtschulden (`fcf_to_debt`, Yahoo `totalDebt`). Grund: Rückkauf-Champions mit negativem Eigenkapital (McDonald's, AutoZone, Booking) lieferten gar kein ROE und D/E und wurden nur über die Marge bewertet; Home Depot mit kleinem Eigenkapital wurde bei der Verschuldung bestraft (380 %) und beim ROE belohnt (104 %). 23 Aktien hatten ein ROE über 100 %. Tage vor dem 11.11. haben nur die alten Kennzahlen; `_quality_inputs` rangiert sie weiter mit Marge, ROE und niedrigem D/E, jeder Tag in sich. Hinweis im Score-Verlauf und in der Hilfe (`QUALITY_CHANGE_DAY`).
- **Momentum / Volatilität geprüft, nicht übernommen:** S&P-500-Kurse 2005–2026 (heutige Mitglieder, Survivorship gilt für beide Varianten gleich). Rang-IC rohes 12-1-Momentum 0,002 (t 0,1), skaliert −0,002 (t −0,1); 2016–2026 beide −0,005. Top-Quintil roh 1,50 %/Monat bei 17,6 % Vol, skaliert 1,35 % bei 16,0 %; Monate unter −15 % im Top-Quintil 3,8 % statt 2,9 %. Die beiden Rangfolgen sind zu 98 % korreliert (84 von 101 Top-20-%-Aktien identisch). Weniger Rendite, etwas weniger Ausreißer, kein Vorhersagevorteil: bleibt beim rohen Momentum. Skript: Scratchpad `sharpe_momentum.py`, nicht im Repository.

## 8. Wahrheitsmaschine ohne Gebühren und Steuern (11.11.2026)
- `factor_lab/backtest.py`: `GermanTaxAccount`, Steuer-Konstanten, `transaction_cost_pct`, `apply_tax`, Endverkauf und ETF-Besteuerung entfernt. Kennzahlen `final_value` und `cagr` für beide Seiten; `taxes_paid`, `costs_paid`, `*_after_tax` gibt es nicht mehr. `excess_cagr` statt `excess_cagr_after_tax`.
- Urteil (`report.py`), Kommandozeile (`--cost`, `--no-tax`, `--tax-allowance` entfernt), Forschungsseite (Checkbox „Deutsche Steuer“ weg, Ergebnistabelle mit 5 Zeilen) und die Hilfe „Wahrheitsmaschine einfach erklärt“ (Abschnitte 1, 3, 4, 6, 7, 11) angepasst. `backtest_engine` rechnet ebenfalls mit 0 Kosten.
- Grund: Erst muss die Auswahl selbst den ETF schlagen. Gebühren und Steuern lassen sich auf ein bestandenes Ergebnis draufrechnen, retten aber kein durchgefallenes. Der Paper-Bot behält seine 1 € Gebühr, 0,5 % Stop-Slippage und die Londoner Stempelsteuer, weil er einen laufenden Forward-Test abbildet.
- Tests: 5 Steuer-Tests entfernt, neu `test_backtest_has_no_costs_and_no_taxes` (Buy-and-hold endet exakt bei der Kursbewegung), Hilfe-Test prüft, dass Teilfreistellung, Sparerpauschbetrag, 26,375 und Verlusttopf nicht mehr vorkommen.

## 9. Zwei weitere Rang-Score-Spieldepots (11.11.2026)
Die Vorschläge „Regime-Schalter“ und „Thesis-Exit“ laufen als eigene Depots mit frischen 100.000 €, damit der Vergleich Rang-Score gegen Punkte-Score sauber bleibt. Beide nutzen die Regeln des Rang-Score-Depots (beste 2 %, 5 Käufe/Tag, 25 % je Sektor, Stop-Loss).
- **`rank_regime` „Rang-Score mit Kaufpause“:** keine neuen Orders, solange EUNL.DE unter seinem 200-Tage-Durchschnitt schließt (`market_above_average`, Stand `state["regime"]`). Gehaltene Positionen bleiben mit Stop. Fehlt die ETF-Historie (unter 200 Schlusskurse), gilt keine Pause. `run` lädt die Kurse deshalb mindestens 320 Kalendertage zurück.
- **`rank_exit` „Rang-Score mit Score-Ausstieg“:** `update_weak_days` zählt Entscheidungstage in Folge mit Rang-Score unter 40 (`exit_score`); Tage ohne frischen Score ändern den Zähler nicht, ein Tag ab 40 setzt ihn auf 0. Beim 5. Tag (`exit_days`) wird `exit_day` gesetzt und die Aktie zur nächsten Eröffnung verkauft (Grund „Rang-Score 5 Tage unter 40“), vor der Stop-Prüfung des Tages.
- **Bestand:** `ensure_portfolios` ergänzt fehlende Depots und neue Config-Schlüssel beim nächsten Lauf; die drei alten Depots laufen unverändert weiter. Die neuen Depots haben `started` = 11.11.2026, die Verlaufslinien beginnen dort.
- **App:** sechs Kennzahlen in zwei Reihen, Marktlage-Zeile unter den Kennzahlen, beim Ausstiegs-Depot die Spalten „Rang-Score heute“, „Tage unter 40“, „Verkauf“; Regeln, Hilfe-Tabelle, Startseite („Fünf Spieldepots … vier davon per Stop-Loss“) und README angepasst. `DEPOT_LABELS` leitet sich aus `BOT_SERIES` ab.
- **Nicht umgesetzt:** ATR-Stop, bis Positionen +25 % erreichen; Steuer-Cockpit (Finanzplaner, nicht Aufgabe der App).
- **Tests:** `market_above_average`, Pause unter/über der Linie, keine Pause ohne Historie, Ausstieg nach 5 Tagen zur Eröffnung, Zähler-Reset und Halten ohne Daten, Migration alter Zustände, Ladezeitraum. 434 grün.

## 10. Trades-Seite neu gegliedert (25.11.2026)
Wunsch: Regeln und Aufgaben der Depots waren auf der Seite nicht zu durchschauen (ein langer Regelblock, sechs Kennzahlen ohne Zeitbezug, „Score“ ohne Angabe welcher).
- **Reihenfolge:** Einleitung → „Was macht welches Depot?“ (Tabelle Depot · Kauft · Verkauft · Wozu, `build_depot_rule_rows`) → aufklappbar „Regeln, die für alle Depots gelten“ (`build_common_rule_rows`: Wann, Datenprüfung, Betrag, Kauf, Stop-Loss, Verkauf am Stop, Sperre, Bewertung) → „Stand“ → Verlauf → „Was die Depots bisher zeigen“ → „Ein Depot im Detail“.
- **Stand** (`build_depot_status_rows`): jedes Depot ab seinem eigenen Start, daneben der ETF über genau dieselben Tage und der Vorsprung in Prozentpunkten. Die später gestarteten Depots werden so nicht mehr mit dem Startkapital der anderen verglichen.
- **Vergleiche** (`build_depot_comparison_rows`, `DEPOT_COMPARISONS`): sechs Fragen (Rang- gegen Punkte-Score, Stop-Loss, Kaufpause, Score-Ausstieg, je Score gegen ETF), gemessen ab dem späteren Start beider Seiten. Hat die Sonderregel eines Depots noch nie gegriffen (`paused_days` = 0 bzw. kein Verkauf mit Grund „Rang-Score …“), steht das dort statt eines Siegers. Hinweis, dass nach wenigen Wochen jeder Unterschied Zufall ist.
- **Detail:** Regel des gewählten Depots in drei Zeilen, Status der Sonderregel (`depot_status_line`: Marktlage und Zahl der Pausentage, schwache Aktien mit „x von 5 Tagen“), Kennzahlen Wert / Aktien / Bargeld. Spalten mit dem richtigen Score-Namen („Rang-Score beim Kauf“, offene Orders, Kaufgrund „Rang-Score 85,6“ statt „Score 85.6“), Stop-Spalten umbenannt: „Stop-Kurs“, „Luft bis Stop %“, „Stop-Regel: 15 % unter Hoch“.
- **Bot:** `paused_days` zählt Entscheidungstage mit Kaufpause.
- **Hilfe:** Die Depot-Tabelle im Reiter Spieldepots kommt aus derselben Funktion wie auf der Trades-Seite.
- **Tests:** Depotregeln, Stand ab eigenem Start mit ETF über dieselben Tage, Vergleiche ab gemeinsamem Zeitraum und „Regel hat nie gegriffen“, Score-Namen in Kaufgründen, Statuszeile, Zählung der Pausentage, Seite rendert mit der Depot-Tabelle zuerst. 441 grün.

## 11. Zu teure Tokio-Pakete nicht mehr scannen (25.11.2026)
Befund: Die Rang-Score-Depots orderten Tokio-Aktien, deren 100er-Paket mehr als 5.000 € kostet (Tokyo Electron, Advantest, Keyence), und stornierten sie am nächsten Tag: 9 Stornos, jedes Mal ein verlorener Kaufplatz von 5. Wunsch: Solche Aktien gar nicht erst scannen.
- **`lot_filter.py`:** Liste `signal_history/zu_teure_pakete.json` (wird mit den Snapshots committet). Der Asien-Lauf (und `all`) baut sie jede Nacht neu: Kurs aus dem letzten Snapshot (`last_close`, für ältere Snapshots aus dem Preis/Volumen-Text), Kurs der bereits ausgelassenen Aktien per kleinem Sammelabruf, EUR/JPY von Yahoo. Ausgelassen wird, wessen Paket mehr als 4.999 € kostet (Budget minus 1 € Gebühr). Ohne Wechselkurs bleibt die alte Liste, ohne neuen Kurs bleibt eine Aktie mit ihren letzten Paketkosten drauf. Nach einem Split kommt sie zurück.
- **`update_signals.run_update` und `daily_job`:** alle Gruppen lassen die Aktien aus. Weil sie nicht mehr in `allowed_symbols` stehen, verschwinden sie auch aus dem zusammengeführten Snapshot.
- **Erste Liste (25.11.):** 14 von 224 Tokio-Aktien, EUR/JPY 174,77: 1801, 4004, 4578, 6098, 6273 (32.220 €), 6367, 6504, 6857, 6861, 6920, 7741, 7974 (5.149 €), 9766, 9983 (49.346 €). 1.360 von 1.374 Aktien bleiben im Scan.
- **Zweite Sicherung im Bot:** `place_orders` überspringt mit `lot_too_expensive` ein Paket, das am Entscheidungstag über dem Budget liegt (Kurs kann zwischen zwei Nächten steigen), und nimmt den nächsten Kandidaten. EURJPY wird dafür immer mitgeladen. Ohne Kurs oder Kurs-Rate wird wie bisher geordert.
- **Snapshot:** neues Feld `last_close` je Eintrag.
- **Texte:** gemeinsame Depotregel „Kauf“ und Hilfe Datenquellen.
- **Tests:** `tests/test_lot_filter.py` (Paketkosten, Liste nur über Budget, Rückkehr nach Split, Ausfall von Abruf und Kurs, Nachtlauf scannt ausgelassene nicht, Kurs aus altem Text, Bot überspringt und kauft den nächsten). Unit-Tests arbeiten mit einer temporären Liste ohne Netz (`_offline_lot_filter` in `tests/conftest.py`).
