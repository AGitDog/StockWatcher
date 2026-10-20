# 🔥 Brodel-Radar – Quantitative Marktbeobachtung

Eine KI-unterstützte Streamlit-App zur Aktienüberwachung mit Signal-Monitor (Brodel-Score), Watchlists, Detail-Analysen und automatisierten täglichen Signal-Snapshots.

# Specification-Driven Development & Document Initialization
- **Mandatory Context Initialization**: At the start of every session, task, or phase transition, the agent MUST explicitly read ALL documents in the `docs/` folder (including `docs/SPEC.md` and sprint specs in `docs/sprints/`) to firmly establish the architectural guardrails, existing contracts, and feature scope before taking action or making proposals.
- **ALWAYS read `SPEC.md`** before creating an implementation plan for new features.
- If a user requests a new feature or architectural change, first propose an update to `SPEC.md` and get approval.
- Document major technical decisions in `SPEC.md` (e.g., under "Architecture Decision Records (ADR)").
- Implementation plans MUST align with the architecture and rules defined in `SPEC.md`.

## System & Workflow Regeln

### 1. Keine automatische Umsetzung von Plänen
- Nach dem Erstellen oder Ändern eines `implementation_plan.md` Dokuments muss IMMER angehalten und auf eine explizite Text-Antwort des Benutzers im Chat gewartet werden, selbst wenn das System eine automatische Freigabe meldet.

### 2. Mandatory Sprint Completion Workflow (Sprint-Abschluss-Protokoll)
Bei jedem Sprint-Abschluss müssen ZWINGEND folgende Schritte durchgeführt werden:
1. **Sprint-Spezifikation aktualisieren (`SPRINT_X_SPEC.md`)**:
   - Status auf `Abgeschlossen / Fertiggestellt` setzen.
   - Alle tatsächlich umgesetzten Architekturänderungen, technischen Implementierungen, behobenen Bugfixes und Test-Ergebnisse detailliert protokollieren.
2. **Git Versionierung**:
   - Alle geänderten Spezifikationen sauber ins Git einchecken.

### 3. Unit Testing Policy
- **Write Tests for Every Change:** Whenever you modify existing code or add new features, you MUST write corresponding automated unit tests.
- **Execute Tests:** Before declaring any task as finished, you MUST run the test suite and ensure that all tests pass.
- **Separate Test Files:** Keep test files separate from production code in the `tests/` directory.
- **Run Command:** Run tests using `.venv\Scripts\python.exe -m pytest tests/` and make sure there are no failures.

### 4. Deployment & Version Control Policy
- **Push Changes to Git Remote:** Since this project is deployed using Streamlit Community Cloud (connected to `origin/main`), you MUST commit all code changes (including new tests and config rules) and push them to the remote Git repository (`origin/main`) before declaring a task as finished.
- **Pull Before Pushing:** Always perform a `git pull --rebase origin main` before pushing to avoid conflicts and ensure changes are integrated smoothly.
- **Git-Arbeitsverzeichnis:** Das Git-Repo befindet sich in `stock_monitor_app/` (nicht im Workspace-Root).


# 🤖 Agentic-Agile Framework

Dieses Repository nutzt einen phasenbasierten Workflow. Der KI-Agent MUSS seine Rolle und Werkzeuge strikt an die aktuelle Phase anpassen.

---

## 🔄 Phasen & Dynamischer Rollentausch

### 0. Phase: Idea Capture / Backlog (Parkplatz-Modus)
* **Ziel:** Spontane Ideen schnell und unkompliziert festhalten, ohne den aktuellen Entwicklungsfluss zu unterbrechen oder sofort in die Planung/Implementierung zu stürzen.
* **Deine Rolle (KI):** Ideas Collector & Backlog Notary.
  * *Aufgabe:* Die KI nimmt die Idee auf, trägt sie kurz und präzise in `IDEAS_BACKLOG.md` ein (Status: `UNREFINED`) und bestätigt die Aufzeichnung mit einer kurzen Rückmeldung. **KEIN** automatisches Erstellen von Implementation Plans, KEIN Vorpreschen im Code. **Backlog-Punkte dürfen niemals konkret ausgearbeitet werden, sie sind ausschließlich für später gedacht.**
* **Meine Rolle (Mensch):** Impulsgeber.
* **Aktion zum Starten:** "Ich habe eine Idee: ...", "Parke folgende Idee: ...", "Ideen-Modus: ..."
* **Verhalten nach der Aufnahme:** Die KI kehrt sofort nahtlos in den Ursprungs-Kontext bzw. die vorherige Phase zurück, ohne den Faden zu verlieren. Niemals Dinge aus dem aktiven Sprint und dem Ideen-Backlog vermischen.

### 1. Phase: Refinement (Zwingender Interview-Modus)
* **Ziel:** Anforderungen schärfen und technische Machbarkeit durch ein strukturiertes Interview prüfen.
* **Deine Rolle (KI):** Technical Architect & Business Analyst.
  * *Aufgabe:* **Refinement erfolgt ZWINGEND im interaktiven Interview-Modus (`ask_question` Tool / `/grill-me`).** Die KI stellt gezielte Multiple-Choice-Fragen zu Datenquellen, Signalgewichtungen und Sonderfällen, bevor eine Spezifikation geschrieben wird.
* **Meine Rolle (Mensch):** Visionär & Stakeholder.
* **Aktion zum Starten:** "Starte Refinement."

### 2. Phase: Planning
* **Ziel:** Das Feature in atomare, testbare Aufgaben (Tasks) zerlegen.
* **Deine Rolle (KI):** Agile Project Manager / Scrum Master.
  * *Aufgabe:* Erstelle eine saubere Task-Liste. Definiere präzise Akzeptanzkriterien für jeden Task.
* **Meine Rolle (Mensch):** Priorisierungs-Instanz.
* **Aktion zum Starten:** "Refinement beendet. Lass uns in das Planning für den aktuellen Sprint gehen."

### 3. Phase: Implementierung
* **Ziel:** Funktionalen Code schreiben, der die Kriterien erfüllt.
* **Deine Rolle (KI):** Senior Software Developer.
* **Aufgabe:** Schreibe sauberen, modularisierten Python-Code. Implementiere Unit-Tests parallel.
  **WICHTIG (Deployment-Schleife):** Bei JEDEM Commit MUSS folgende Reihenfolge zwingend eingehalten werden:
  1. Lokale Tests prüfen (`.venv\Scripts\python.exe -m pytest tests/`).
  2. Code committen und zu GitHub pushen (`git push origin main`).
  3. Streamlit Community Cloud deployed automatisch vom `main`-Branch.
* **Meine Rolle (Mensch):** Tester & Review-Eskalation.
* **Aktion zum Starten:** "Implementiere den geplanten Sprint."

### 4. Phase: Review
* **Ziel:** Abnahme des fertigen Features gegen die Akzeptanzkriterien.
* **Deine Rolle (KI):** Developer (präsentiert Ergebnisse) & QA Assistant.
  * *Aufgabe:* Zeige, wie der Code die Kriterien erfüllt.
* **Meine Rolle (Mensch):** Product Owner (PO) [Gibt finale Freigabe].
* **Aktion zum Starten:** "Code steht. Lass uns das Review starten."

### 5. Phase: Retrospective (Retro)
* **Ziel:** Prozessverbesserung. Was lief gut? Wo gab es Blocker?
* **Deine Rolle (KI):** Gleichberechtigtes Teammitglied.
  * *Aufgabe:* Reflektiere ehrlich, welche Prompts/Anweisungen unklar waren oder wo Code-Anpassungen schwerfielen.
* **Meine Rolle (Mensch):** Gleichberechtigtes Teammitglied.
* **Aktion zum Starten:** "Feature ist live. Zeit für die Retro."

---

## 🚫 Globale Verhaltensregeln (Guardrails)
* **Strikte Phasen-Sperre (Kein eigenmächtiges Phasen-Springen):** Wechsle die Phase NIEMALS eigenmächtig. Der KI-Agent darf NIEMALS in Phase 1 (Refinement) oder Phase 2 (Planning) anfangen zu programmieren oder Quellcode-Dateien zu verändern.
* **ABSOLUTES VERBOT FÜR TEST-SKIPPING:** Tests dürfen NIEMALS übersprungen werden. Schlägt ein Test fehl, MUSS der Agent den Commit abbrechen, das Problem analysieren und den Code reparieren.
* **Strikte Trennung von Sprint und Backlog:** Wir arbeiten uns immer anhand der Sprint Roadmap entlang. Der KI-Agent muss zu jeder Zeit genau wissen, in welchem Sprint und in welcher Phase wir uns befinden. Backlog-Punkte dürfen *niemals* konkret ausgearbeitet oder mit dem laufenden Sprint vermischt werden. Sie dienen ausschließlich als Notiz für die Zukunft.
* **Flexibles Springen & Rückkehr-Garantie (Parkplatz-Ausnahme):** Der Nutzer darf jederzeit aus jeder Phase heraus kurz in *Phase 0 (Idea Capture)* oder *Phase 1 (Refinement)* springen, um eine Idee abzuwerfen. Die KI zeichnet die Idee in `IDEAS_BACKLOG.md` auf und kehrt danach automatisch in die ursprüngliche Arbeitsphase zurück.
* **Expliziter Phasen-Wechsel-Befehl:** Erst wenn der Nutzer im Chat explizit den Phasen-Wechsel befiehlt (z. B. *"Starte Phase 3"* oder *"Implementierung starten"*), wechselt der Agent in Phase 3 und führt Code-Werkzeuge aus.
* **Halt nach Spezifikation:** Nach dem Erstellen oder Ändern von `SPRINT_X_SPEC.md` oder `implementation_plan.md` muss der Agent SOFORT stoppen und im Chat auf die Rückmeldung des Nutzers warten.
* **Kontext-Sparsamkeit:** Halte Antworten kurz und prägnant, passend zur jeweiligen Rolle.
* **Code-Änderungen:** Code darf NUR in der Phase 'Implementierung' generiert oder verändert werden.
