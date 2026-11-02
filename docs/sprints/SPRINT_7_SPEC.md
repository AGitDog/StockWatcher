# Sprint 7 Spezifikation: Wahrheitsmaschine – ehrliche Messung gegen einen ETF

**Sprint-Status:** Abgeschlossen / Fertiggestellt (Phase 3: Implementation)
**Erstellt am:** 02.11.2026
**Abgeschlossen am:** 02.11.2026
**Freigabe:** Umsetzung im Chat freigegeben („OK dann setze das mal um“) nach Bewertung der Verbesserungsvorschläge. Sprint 6 bleibt unverändert im Refinement.
**Ziel:** Bevor weitere Signale gebaut werden, muss messbar sein, ob das System einen einfachen ETF nach Kosten und deutschen Steuern schlägt. Dazu kommen ein Fix im Makro-Overlay und eine Absicherung der ML-Gewichte gegen Overfitting.

## Testergebnisse & Verifikation
- **231 Tests erfolgreich bestanden** (0 Fehler, Ausgangsbasis 177). Stand nach Nachtrag Task 6.
- Neue Testsuiten: `tests/test_factor_lab.py` (35 Tests), `tests/test_truth_machine_app.py` (5 Tests).
- Erweitert: `tests/test_ml_weights.py` (+8 Tests), `tests/test_stock_agent.py` (+3 Tests).
- Manuelle Verifikation: Lauf über 503 S&P-500-Titel von 2005 bis 2026 per CLI und per Streamlit-AppTest mit Klick auf „Wahrheitsmaschine starten“.

---

## 1. Scope & Hintergrund
Die Analyse des Projekts ergab:
- Der Brodel-Score ist eine additive Punkteliste ohne Kalibrierung gegen spätere Renditen.
- Die Snapshot-Historie umfasst nur 16 Tage. Analystenziele, Insider- und Short-Daten aus Yahoo sind nicht rückwirkend abrufbar.
- Die ML-Gewichte wurden auf denselben wenigen Tagen trainiert und ohne Test außerhalb der Trainingsdaten angewendet.
- Das Makro-Overlay machte negative Scores im Bärenmarkt weniger negativ.

Entscheidung: Nur was mit kostenlosen Daten rückwirkend rekonstruierbar ist, wird über einen langen Zeitraum getestet. Der Makro-Filter steuert im Backtest die Investitionsquote statt eines Regime-Klassifikators. Steuern und der ETF-Vergleich sind fester Bestandteil jeder Auswertung.

---

## 2. Task-Liste

### Task 1: Bugfix Makro-Overlay (`stock_agent.py`)
- `_apply_macro_overlay` multipliziert positive Scores und dividiert negative Scores durch den Multiplikator.
- Ergebnis: Ein ungünstiges Regime dämpft positive Scores und verstärkt negative. Die Abbildung ist monoton.
- **Akzeptanz:** Score −20 bei Multiplikator 0,8 ergibt −25. Tests in `tests/test_stock_agent.py`.

### Task 2: Out-of-Sample-Schutz für ML-Gewichte (`ml_weights/trainer.py`)
- Neue Funktion `validate_out_of_sample`: zeitliche Trennung in 70 % Training und Testzeitraum, Embargo von `forward_days` Kalendertagen, Vergleich des mittleren Rank-IC gegen Gleichgewichtung.
- Mindestens 60 Snapshot-Tage, sonst keine Validierung.
- `ScoreWeightTrainer.validated` steuert `predict_score`. Nicht validierte Gewichte fallen auf Gleichgewichtung zurück. Alte Gewichtsdateien ohne Flag gelten als nicht validiert.
- UI zeigt nach dem Training, ob und warum Gewichte angewendet werden.

### Task 3: Paket `factor_lab` (Wahrheitsmaschine)
- `factors.py`: kursbasierte Faktoren ohne Zukunftswissen (`momentum_12_1`, `momentum_6_1`, `low_volatility`, `reversal_1m`, `trend_200d`), Perzentil-Ränge über eine gemeinsame Titelmenge, gleichgewichteter Composite-Score.
- `evaluation.py`: Rank-IC je Monat mit t-Wert und Trefferquote, Quintilsrenditen, Walk-forward-Lernen mit Embargo gegen Gleichgewichtung, Probabilistic und Deflated Sharpe Ratio, Messung gespeicherter Snapshot-Scores inklusive Auswertung nur nicht überlappender Fenster.
- `backtest.py`: monatliches Top-N-Portfolio, Ausführung am Folgetag, gleich oder invers zur Volatilität gewichtet, optionale Sektorgrenze, Transaktionskosten, Trendfilter auf die Investitionsquote, Abgeltungssteuer plus Soli mit Verlusttopf und Sparerpauschbetrag, ETF-Benchmark mit 30 % Teilfreistellung, Endliquidation beider Seiten.
- `report.py`: Zusammenführung und ein deutsches Urteil allein aus den gemessenen Zahlen, inklusive der Grenzen des Tests.
- `data.py`: Download mit Datei-Cache in `cache/factor_lab/`, Universum aus Index oder Watchlist, Beschränkung auf eine Währung, Yahoo-Schreibweise für Aktienklassen.
- `__main__.py`: CLI `python -m factor_lab` und `python -m factor_lab --brodel`.

### Task 4: UI-Integration (`app.py`, Reiter „Backtest & ML“)
- Abschnitt „🧪 Wahrheitsmaschine“ mit Universum, Benchmark, Startjahr, Faktoren, Anzahl Aktien, Trendfilter, Steuer und Anzahl getesteter Varianten.
- Ausgabe: Urteil, Vergleichstabelle Strategie gegen ETF, Vermögenskurve, Faktorstatistik, Walk-forward-Ergebnis und Grenzen.
- Abschnitt „🔬 Brodel-Score auf dem Prüfstand“ mit Rank-IC und Zahl unabhängiger Messpunkte.

### Task 5 (Nachtrag): Ausführliche Hilfe im Reiter „Hilfe & Methodik“
- Neue Funktion `render_truth_machine_help()` in `app.py` mit elf Abschnitten in einfacher Sprache: Grundidee, ETF-Auswahl, genaue Behandlung des ETF inklusive Steuerformel und Rechenbeispiel, Strategie-Ablauf, Faktoren, alle Einstellungen, Ergebnistabelle, Statistik, Grenzen, Brodel-Prüfstand und Bedeutung für Anleger.
- Korrigiert: Hilfetext zum Makro-Overlay (negative Scores werden geteilt) und zur ML-Gewichtung (Out-of-Sample-Schutz, 60 Snapshot-Tage).
- Hinweis im Abschnitt Wahrheitsmaschine auf die Hilfe.
- Tests: 2 neue AppTests in `tests/test_truth_machine_app.py`.

### Task 6 (Nachtrag): Hilfe entschlackt
- Entfernt: Anleitung zur Watchlist-Datei im Schnellstart und Headless-Hinweis, Abschnitt „Empfohlener Einstiegsplan“, Abschnitt „Der menschliche Faktor“ samt Verhaltensfallen und Regeln, allgemeiner Schlussabsatz.
- Schnellstart auf vier Schritte gekürzt, mit Verweis auf Wahrheitsmaschine und Brodel-Prüfstand.
- Test: `test_help_tab_omits_removed_sections`.

---

## 3. Ergebnisse des ersten Laufs (S&P 500, 2005–2026, SPY)

| Variante | Rendite p. a. nach Steuer | ETF | Max. Verlust | Deflated Sharpe |
|---|---|---|---|---|
| Momentum + Low-Vol, Top 20, Trendfilter | 7,5 % | 10,0 % | −24 % | 0,09 |
| Momentum allein, Top 20, Trendfilter | 19,7 % | 10,0 % | −36 % | nicht belastbar |

- Der Composite-Score sortiert nicht signifikant. Low-Volatility zeigt einen negativen Effekt.
- Die hohe Momentum-Rendite ist durch Survivorship Bias verzerrt. Die meistgehaltenen Titel sind Rückblick-Gewinner wie NFLX, NVDA, TPL, CVNA und AXON, die teils erst 2023 bis 2025 in den Index aufgenommen wurden.
- Eine vereinfachte Gegenrechnung ohne Kosten und Steuer ergibt 28 % pro Jahr. Die Simulation rechnet also korrekt, und die monatlich einbehaltene Steuer kostet rund ein Viertel der Rendite.
- Brodel-Score: 16 Snapshot-Tage. Bei 5 Tagen Horizont ergibt sich ein Rank-IC von +0,077 auf nur 4 unabhängigen Messpunkten. Das ist ermutigend, aber nicht belastbar.

---

## 4. Offene Punkte für spätere Sprints
- Point-in-time-Indexzusammensetzung und Kurse delisteter Titel, um den Survivorship Bias zu beseitigen.
- Insider-Käufe aus SEC EDGAR als erster rekonstruierbarer Zusatzfaktor.
- Kern-Satellit-Ansicht mit Ziel- und Entnahmerechner.
