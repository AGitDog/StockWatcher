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
