# Sprint 9 Spezifikation: Paper-Trading-Bot (Brodel 2.0 mit Trailing-Stop)

**Sprint-Status:** Abgeschlossen / Fertiggestellt (Phase 3: Implementation)
**Erstellt am:** 05.11.2026
**Abgeschlossen am:** 05.11.2026
**Freigabe:** Die Regeln hat der Nutzer im Chat vorgegeben. Offene Punkte wurden per Rückfrage entschieden: 100.000 € bei 5.000 € je Aktie, Kaufgrenze 60, eigener Simulator, 20 Handelstage Rückkaufsperre.
**Ziel:** Ein ehrlicher Test mit Blick nach vorn. Ab jetzt handelt ein Bot täglich nach Brodel 2.0 und den Stop-Loss-Regeln des Nutzers. Zwei Vergleichsdepots zeigen, ob Auswahl und Stop-Loss etwas bringen.

## Testergebnisse & Verifikation
- **317 Tests erfolgreich bestanden** (0 Fehler). Neu ist `tests/test_paper_bot.py` mit 15 Tests.
- Probelauf mit echten Daten: Kurse und Wechselkurse werden geladen, auch GBp (London) und JPY. Am 05.11. gab es 5 Kandidaten ab 60 Punkten (JKHY 67, ABNB, CDW, CPAY und GEN je 62). Der Reiter rendert ohne Fehler.

## 1. Regeln

| Regel | Umsetzung |
|---|---|
| Takt | einmal täglich nach dem letzten Regionslauf (america-2) |
| Kauf | frische Einträge des Tagessnapshots mit Brodel 2.0 ab 60, höchster Score zuerst |
| Ausführung | Eröffnungskurs des nächsten Handelstags an der Heimatbörse, 1 € Gebühr, ganze Stück |
| Größe | 5.000 € je Aktie, höchstens 20 Positionen, Startkapital 100.000 € |
| Stop-Loss | 15 % unter dem Kaufkurs. Er wird täglich zum höchsten Schlusskurs nachgezogen und sinkt nie. Ab +25 % (höchster Schlusskurs gegenüber Kaufkurs) beträgt der Abstand 10 %. |
| Auslösung | Der Tagestiefstkurs berührt den Stop: Verkauf zum Stop minus 0,5 % Slippage, nie unter dem Tagestief (Nachtrag 05.11., vom Nutzer gewünscht). Eröffnet die Aktie unter dem Stop: Verkauf zur Eröffnung. |
| Sperre | Eine verkaufte Aktie wird frühestens nach 28 Kalendertagen (etwa 20 Handelstage) wieder gekauft. |
| Währung | Depot in Euro, Umrechnung mit dem Tageskurs EUR/xxx von Yahoo |

Kein Blick in die Zukunft: Entscheidungen nutzen nur den Snapshot des Tages. Ausgeführt wird erst am Folgetag. Kursbalken zählen nur, wenn sie abgeschlossen sind (`decision_cutoff`).

## 2. Umsetzung
- `paper_bot.py`: Regeln (`step`, `process_position`, `fill_pending`, `place_orders`, `buy_candidates`), Zustand in `bot_depot/state.json` und Kursdaten über ein einziges `yf.download` für Bestände, offene Orders, ETF und Wechselkurse. Befehle: `run`, `status`, `reset`.
- Vergleichsdepots: „Gleiche Käufe ohne Stop-Loss“ mit derselben Logik, aber ohne Verkauf, und ein MSCI-World-ETF (EUNL.DE), gekauft zur ersten Eröffnung nach dem Start.
- Workflow `update_signals.yml`: Der Schritt „Run paper bot“ läuft nach america-2 oder bei manuellem Start mit `run_bot`. `continue-on-error`, damit der Snapshot in jedem Fall gespeichert wird. `bot_depot/` wird mit committet.
- App: neuer Reiter „🤖 Bot-Depot“ mit drei Kennzahlen (Bot, ohne Stop, ETF), Wertverlauf, Bestand mit Stop-Loss und Abstand, offenen Orders sowie Käufen und Verkäufen.

## 3. Grenzen
- Tageskurse: Kursbewegungen innerhalb eines Tages sind unbekannt. Liegt der Stop zwischen Tief und Schluss, wird zum Stop verkauft, auch wenn ein echter Broker leicht anders ausgeführt hätte.
- Keine Steuern im Bot. Ausgewiesen werden nur Werte vor Steuern.
- Belastbar wird der Vergleich erst nach etwa 6 bis 12 Monaten.
- Bei einer Kaufgrenze von 60 gibt es derzeit nur wenige Kandidaten pro Tag, das Depot füllt sich deshalb langsam.
