# Sprint 10 Spezifikation: Datenqualität, Brodel 3.0 und Rang-Depot

**Sprint-Status:** Abgeschlossen / Fertiggestellt (Phase 3: Implementation)
**Erstellt am:** 06.11.2026
**Abgeschlossen am:** 06.11.2026
**Freigabe:** Im Chat: „Bei 3 führe bitte ein neues Depot ein, dass nach dieser Regel kauft. Gleiches Startkapital. Setze Schritt 1 bis 3 gleich um.“ Die Regeln des bestehenden Depots bleiben, das Einfrieren (Schritt 4) ist noch nicht beschlossen.
**Ziel:** Vergleichbare Scores und vollständige Daten, dazu ein zweiter Bot-Ansatz mit Brodel 3.0, der gegen Brodel 2.0 und den ETF antritt.

## Testergebnisse & Verifikation
- Alle Tests grün. Neu: `tests/test_brodel_v3.py`, Erweiterungen in `tests/test_paper_bot.py`, `tests/test_run_groups.py` und `tests/test_brodel_v2.py`.
- Stichprobe mit echten Daten (12 Aktien aus USA, Europa, Asien, Kanada): Rohwerte für 3.0 kommen an, rund 4 Sekunden pro Aktie.

---

## 1. Anlass
Die Prüfung des Nachtlaufs vom 05.11. zeigte zwei Fehler:
- Der Makro-Faktor wurde je Gruppenlauf neu berechnet (0,72 in USA 1, 1,00 in den übrigen Gruppen). Zwei zufällig geteilte Gruppen lagen deshalb bei 23 und 35 Punkten im Mittel. Die feste Grenze 60 hing damit am Lauf und nicht an der Aktie.
- In USA 2 fehlten 127 von 404 Aktien. Gesamtabdeckung 90 %.

## 2. Task-Liste

### Task 1: Fehler beheben
- Brodel 2.0 ohne Makro-Overlay. `primary_score` und `ensure_brodel_v2` rechnen auch ältere Werte aus den Bausteinen nach, Verlauf und Prüfstand sind damit einheitlich. Brodel 1.0 bleibt unverändert.
- USA und Kanada laufen in drei statt zwei Gruppen (`america-1` bis `america-3`, 21:30, 22:30, 23:30 UTC). Der Bot läuft nach `america-3`.
- Asien läuft um 10:30 UTC (nach Börsenschluss Indien). Läufe bis 09:00 UTC zählen zum Vortag (`SNAPSHOT_DAY_SHIFT_HOURS = 9`), weil GitHub bis zu 8 Stunden verspätet startet.
- `started` ist der Entscheidungstag, ETF und erste Orders starten damit zur selben Eröffnung.
- Datenprüfung: Neue Orders nur bei mindestens 90 % frischen Einträgen (`min_coverage`). Das Rang-Depot verlangt zusätzlich 90 % Brodel-3.0-Werte. Bestände und Stops laufen immer weiter.
- London: 0,5 % Stempelsteuer beim Kauf. Tokio: Kauf in 100er-Stückelung. Passt die kleinste Menge nicht ins Budget, wird die Order storniert und die Aktie 28 Tage gesperrt.

### Task 2: Brodel 3.0 (`brodel_v3.py`)

| Baustein | Punkte | Messung |
|---|---|---|
| Qualität | 25 | Marge, Eigenkapitalrendite, Verschuldung, Rang in Region und Sektor |
| Momentum | 20 | Rendite über 12 Monate ohne den letzten Monat, Rang in der Region |
| EPS-Revisionen | 20 | Anteil der Hochstufungen, Rang in der Region |
| Bewertung | 15 | Gewinnrendite und Free-Cashflow-Rendite, Rang in Region und Sektor |
| Aktienrückkauf | 10 | Veränderung der Aktienzahl, Rang in der Region |
| Insider | 10 | nur USA, Käufe am offenen Markt der letzten 90 Tage (Yahoo, ersatzweise Finnhub): keine 5, unter 100.000 $ 7,5, ab 100.000 $ 10 Punkte |

- Fehlt ein Baustein, wird über die vorhandenen gerechnet. Unter 4 Bausteinen gibt es keinen Score.
- Sektoren mit weniger als 8 Aktien werden innerhalb der Region verglichen.
- Die Gewichte sind fachlich begründete Startwerte, kein Messergebnis. Die Kurshistorie pro Aktie wurde dafür von 6 auf 12 Monate verlängert (weiterhin eine Abfrage).
- Rohwerte stehen in `factors_v3`, der nächste Quartalstermin in `next_earnings`. News und Gewinnüberraschung fließen nicht ein.

### Task 3: Neues Depot „Brodel 3.0 beste 2 %“
- Eigenes Depot mit 100.000 €, 5.000 € je Aktie, höchstens 20 Positionen, gleiche Stop-Regeln wie das bestehende Depot.
- Kauf: beste 2 % des Tages nach Brodel 3.0, höchstens 5 Käufe pro Tag, höchstens 25 % des Depots je Sektor (5 Aktien), kein Neukauf in den 7 Kalendertagen vor Quartalszahlen.
- Das bestehende Depot (Brodel 2.0 ab 60) und sein Vergleich ohne Stop-Loss bleiben mit ihren Regeln bestehen.
- `bot_depot/state.json` wurde neu angelegt, damit alle Depots und der ETF vom selben Tag an laufen. Vorher lag nur eine offene Order vor, es gab keinen ausgeführten Kauf.

### Task 4: Detailansicht
- Kopf mit vier Kennzahlen: Brodel 2.0, Brodel 3.0, Rang im Sektor, Abstand zum Sektor. Sektor, Branche, stärkster Peer und Brodel 1.0 in einer Zeile darunter.
- Gemeinsame Tabelle „Bausteine“ mit den Spalten 3.0, 2.0, 1.0 und Detail, ohne Max-Spalten, nach Punkten sortiert, Punkte farbig. Die drei Bausteine, die nur 3.0 hat, stehen mit ihren Rohwerten darin. Die doppelte Liste „Signal-Zusammenfassung“ entfällt.
- Haupttabelle: neue Spalte „Brodel 3.0“.

### Task 5 (Nachtrag 07.11.2026)
- Hilfe: neue Abschnitte zu Brodel 3.0 und zu den Bot-Depots.
- Biotech-Index: Die Nasdaq-Abfrage nutzte das heutige Datum und lieferte am Wochenende nichts. Die Watchlist fiel dann von 1375 auf 1152 Aktien. `load_index_constituents` geht jetzt bis zu 6 Tage zurück.
- Insider: Finnhub lieferte auf GitHub in keinem Snapshot Daten (Einträge alle „[YF]“). Brodel 3.0 liest den Kaufwert deshalb zuerst aus Yahoos Insider-Tabelle (`insider_buy_value`).

### Task 6 (Nachtrag 08.11.2026): Prüfung nach dem ersten Wochenende
- Alle Läufe seit dem 06.11. erfolgreich, 98 % frische Daten, 1352 Aktien mit Brodel 3.0, Insider-Werte für 747 von 821 US-Aktien.
- **Aktiensplits:** Die Aktienzahl ist bei Yahoo nicht um Splits bereinigt (NFLX +866 %, KLAC +891 %, NOW +399 %). 58 Aktien bekamen so falsche Rückkauf-Punkte, ein Reverse-Split hätte volle Punkte gebracht. Veränderungen über 50 % werden nicht mehr bewertet (`SHARE_CHANGE_PLAUSIBLE`). Das gilt auch für Brodel 2.0.
- **Wochenende:** Die Läufe liefen auch samstags und sonntags und speicherten Freitagskurse als neuen Tag. Die Läufe sind jetzt auf Montag bis Freitag begrenzt.
- **Abgebrochene Aktien:** 11 Aktien fehlten in einem US-Lauf. Lokal liefen sie fehlerfrei. Abgestürzte Aktien werden jetzt am Ende einzeln ein zweites Mal geladen, und der Fehlertyp steht im Log.
- **Finnhub:** Der Schlüssel ist jetzt als Secret eingetragen. Eine Bremse begrenzt die Abfragen auf 55 pro Minute (`wait_for_rate_limit`), sonst bekäme ein Teil der Aktien Finnhub- und ein Teil Yahoo-Daten. Zeitlimit des Workflows auf 45 Minuten erhöht.
- Folge: Brodel 2.0 (Kursziele, Insider) bezieht ab dem 09.11. Daten von Finnhub statt Yahoo, die Werte können sich dadurch verschieben.

## 3. Bewusst nicht umgesetzt
- Einfrieren für 12 Monate und Stoppregel (Schritt 4): Stehen noch zur Entscheidung aus.
- EDGAR-Pipeline, Gewinnüberraschung, Investitionsquote nach Marktlage.

## 4. Offen
- Brodel 3.0 liegt erst vor, wenn alle Gruppen einmal mit neuem Code gelaufen sind. Das Rang-Depot kauft frühestens danach.
- Finnhub liefert auf GitHub keine Daten. Der Schlüssel in den Repository-Secrets sollte geprüft werden.
