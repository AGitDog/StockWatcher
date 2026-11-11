# Insider-Daten außerhalb der USA

Dieser Ordner gehört zum Insider-Baustein des Rang-Scores (siehe `insider_sources.py` und `docs/sprints/SPRINT_12_SPEC.md`).

| Datei | Inhalt | Wer schreibt sie |
|---|---|---|
| `amf_cache.json` | Ausgelesene französische Meldungen (AMF), damit jedes PDF nur einmal geladen wird | Nachtlauf |
| `afm_cache.json` | Ausgelesene niederländische Meldungen (AFM-Register) | Nachtlauf |
| `bafin.csv` | Deutsche Directors' Dealings der BaFin | **du, von Hand** (optional) |

Meldungen, die älter als 120 Tage sind, löscht der Nachtlauf selbst aus den Cache-Dateien.

## BaFin-Datei von Hand laden

Die BaFin verbietet in ihrer robots.txt jeden automatischen Zugriff. Deshalb lädt der Nachtlauf diese Datei nicht selbst.

1. Die BaFin-Datenbank „Eigengeschäfte von Führungskräften“ (Directors' Dealings) im Browser öffnen.
2. Ohne Emittent suchen, mit dem Zeitraum der letzten 3 Monate.
3. Das Ergebnis als CSV exportieren und hier als `bafin.csv` speichern, dann committen.

Wöchentlich zu aktualisieren reicht, weil das Fenster 90 Tage umfasst. Die wöchentliche Prüfung (`insider_check.py`) meldet, wenn die Datei älter als 3 Wochen ist.
