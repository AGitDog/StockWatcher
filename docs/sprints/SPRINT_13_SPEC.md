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
