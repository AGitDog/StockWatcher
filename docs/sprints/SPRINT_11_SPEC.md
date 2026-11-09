# Sprint 11 Spezifikation: Umbenennung und neue Seitenstruktur

**Sprint-Status:** Abgeschlossen / Fertiggestellt (Phase 3: Implementation)
**Erstellt am:** 08.11.2026
**Abgeschlossen am:** 08.11.2026
**Freigabe:** Im Chat: „Bitte auch den Titel umbenennen. Bitte auch Brodel Radar entfernen. Signal Monitor kann raus. Bitte die Seite logisch neu gestalten.“ Dazu: eine Startseite, die erklärt, was die Seite macht, mit einer Checkbox zum Überspringen.
**Ziel:** Ein Name, der erklärt, was das System tut, und eine Seitenstruktur, die neue Besucher abholt.

## Testergebnisse & Verifikation
- **348 Tests grün.** Neu: Navigation, Startseiten-Logik, Browser-Speicher-Komponente, kein „Brodel“ in sichtbaren Texten.
- AppTest mit echten Daten: Alle fünf Seiten rendern ohne Fehler, und die Buttons der Startseite wechseln die Seite.
- Nicht geprüft: das Aussehen im Browser und das Speichern im Browser. Beides geht nur im echten Browser.

## 1. Namen

| Bisher | Neu |
|---|---|
| Brodel-Radar | StockWatcher |
| Brodel 3.0 | Rang-Score (0–100) |
| Brodel 2.0 | Punkte-Score (bis 90) |
| Brodel 1.0 | Punkte-Score alt (nur in der Detailansicht) |
| Signal Monitor | Marktbeobachtung |
| Bot-Depot | Trades |
| Backtest & ML | Forschung |

Die internen Feldnamen (`brodel_score_v2`, `brodel_score_v3`, …) bleiben unverändert, damit gespeicherte Snapshots und der Depot-Zustand nicht umgeschrieben werden müssen.

## 2. Seitenstruktur
- Navigation oben: 🏠 Start · 📊 Marktbeobachtung · 💼 Trades · 🔬 Forschung · ❓ Hilfe. Umgesetzt mit einem Auswahlfeld, weil Streamlit 1.29 noch keine Seitennavigation kennt.
- **Startseite:** Sie erklärt in drei Schritten, was die Seite tut: Daten sammeln, Aktien vergleichen, ehrlich prüfen. Darunter stehen Datenstand, Abdeckung, Depotwerte und die 5 Aktien mit dem höchsten Rang-Score, außerdem Buttons zu allen Seiten und ein Hinweis „Keine Anlageberatung“.
- **Checkbox:** „Diese Startseite beim nächsten Besuch überspringen“. Gespeichert wird nur im Browser (`localStorage`) über die Komponente `components/visitor_prefs`. Es gibt kein Konto und keine Speicherung auf dem Server. Ohne Haken oder bei gesperrtem Speicher erscheint immer die Startseite. Der gespeicherte Wunsch gilt einmal pro Sitzung, danach bleibt „Start“ jederzeit erreichbar.
- Die Marktbeobachtung sortiert die Haupttabelle jetzt standardmäßig nach dem Rang-Score. Aktien ohne Wert stehen am Ende. Der Punkte-Score steht daneben.
- Der Kasten „Mission & Prinzipien“ in der Marktbeobachtung ist entfallen. Sein Inhalt steht jetzt auf der Startseite.

## 3. Nachtrag 09.11.2026: Nachtlauf als Kette
- **Befund:** Seit Sonntag 02:42 UTC lief nichts mehr. Sonntag war gewollt (nur werktags). Der Asien-Lauf vom Montag (geplant 10:30 UTC) war um 17:10 UTC noch nicht gestartet, weil GitHub geplante Läufe bisher 7 bis 8½ Stunden zu spät oder gar nicht startet. Bei fünf einzelnen Startzeiten reicht ein ausgefallener Lauf für einen unvollständigen Tag. Gekauft wird erst beim Bot-Lauf nach dem letzten US-Lauf.
- **Bot geprüft:** Die Simulation auf einer Kopie des Depots mit den Eröffnungskursen vom 09.11. führt alle 14 offenen Orders und den ETF-Kauf korrekt aus (Pence, CAD, Stempelsteuer, Stops).
- **Neu:** ein Start pro Werktag um 21:35 UTC, nach US-Börsenschluss. Die fünf Gruppen laufen als Matrix-Jobs nacheinander (`max-parallel: 1`), jeweils auf einem neuen Runner und damit mit neuer IP. Danach läuft der Job `paper-bot`, auch wenn eine Gruppe fehlschlägt.
- **Ersatzstart** um 03:35 UTC am Folgetag. `run_check.py` lässt ihn nur laufen, wenn der Bot für den Handelstag noch nicht entschieden hat, und nie zwischen 09:00 und 21:00 UTC (sonst halbe Tageskurse).
- Ein manueller Start („Run workflow“) startet die ganze Kette.
- **App:** Die Marktbeobachtung lädt einen neuen Snapshot nach, auch wenn die Seite offen geblieben ist, und zeigt den Datenstand an.

## 4. Nachtrag 09.11.2026: Sektor-Vergleich nach Rang-Score
- **Befund:** „Rang“ und „Vs. Sektor“ rechneten noch mit dem Punkte-Score und über alle Regionen. BGEO.L stand deshalb bei 50/159, obwohl die Aktie den höchsten Rang-Score aller europäischen Finanzwerte hat.
- **Neu:** Aktien mit Rang-Score werden nach Rang-Score mit derselben Region und demselben Sektor verglichen. Das ist dieselbe Gruppe, in der der Rang-Score selbst gebildet wird. BGEO.L steht damit bei 1/43 und +37,3. Aktien ohne Rang-Score (ETFs, dünne Daten) behalten den Vergleich nach Punkte-Score über den ganzen Sektor.
- Die App berechnet den Vergleich beim Laden neu, deshalb gilt die Änderung auch für schon gespeicherte Tage. Die Tooltips der Tabelle und der Detailansicht nennen die Vergleichsgruppe.
- **Test:** `test_peer_context_ranks_by_rank_score_within_region_and_sector`. 355 Tests grün.
