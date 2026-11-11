# Insider-Daten außerhalb der USA

Dieser Ordner gehört zum Insider-Baustein des Rang-Scores (siehe `insider_sources.py` und `docs/sprints/SPRINT_12_SPEC.md`).

| Datei | Inhalt | Wer schreibt sie |
|---|---|---|
| `amf_cache.json` | Ausgelesene französische Meldungen (AMF), damit jedes PDF nur einmal geladen wird | Nachtlauf |
| `afm_cache.json` | Ausgelesene niederländische Meldungen (AFM-Register) | Nachtlauf |
| `bafin.csv` | Deutsche Directors' Dealings der BaFin, nur als Ersatz | **du, von Hand** (optional) |

Meldungen, die älter als 120 Tage sind, löscht der Nachtlauf selbst aus den Cache-Dateien.

## Deutschland

Die deutschen Meldungen kommen automatisch über die kostenlose API von [Tracefour](https://tracefour.com/de) (`/v1/eu/de`). Tracefour bereitet die BaFin-Meldungen auf und stellt sie unter CC BY 4.0 bereit. Wo die Daten angezeigt werden, muss deshalb ein Link auf Tracefour stehen. Der Nachtlauf ruft die API einmal pro Lauf ab, erlaubt sind 60 Abrufe pro Stunde.

## BaFin-Datei von Hand (nur Ersatz)

Antwortet Tracefour nicht, nutzt der Nachtlauf `bafin.csv`, falls vorhanden. Die BaFin verbietet in ihrer robots.txt jeden automatischen Zugriff, deshalb lädt der Nachtlauf diese Datei nicht selbst.

1. Die BaFin-Datenbank „Eigengeschäfte von Führungskräften“ (Directors' Dealings) im Browser öffnen.
2. Ohne Emittent suchen, mit dem Zeitraum der letzten 3 Monate.
3. Das Ergebnis als CSV exportieren und hier als `bafin.csv` speichern, dann committen.

Die wöchentliche Prüfung (`insider_check.py`) meldet, wenn die Datei älter als 3 Wochen ist.
