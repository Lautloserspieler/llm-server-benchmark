# Beitragen zu llmbench

🇩🇪 Deutsch | [🇬🇧 English](CONTRIBUTING.en.md)

Danke, dass du an `llmbench` mitarbeiten willst. Dieses Dokument beschreibt Architektur,
Entwicklungs-Setup, Code-Konventionen und den Ablauf für Pull Requests.

## Projektzweck

`llmbench` ist ein Python-CLI-Tool zum **reproduzierbaren** Benchmarking von lokalem
LLM-Server-Inferencing. Statt nur einer Tokens/s-Zahl erfasst es die komplette Umgebung
(GPU, Treiber, Backend-Build, Modell-Hashes, Benchmark-Konfiguration, Energiezustand), damit
zwei Systeme unter nachweisbar vergleichbaren Bedingungen gegenübergestellt werden können.

Das Projekt unterstützt **llama.cpp** nativ und **vLLM** als Docker-Backend. Für
GPU-Telemetrie sind **NVIDIA/NVML** und **AMD/rocm-smi** implementiert. Weitere Backends
und Telemetriequellen sind über die vorhandenen Plugin-Schnittstellen vorgesehen — siehe
[`ROADMAP.md`](ROADMAP.md). Neue Implementierungen sollen den Kern nicht unnötig
spezialisieren.

## Architektur im Überblick

Zwei abstrakte Basisklassen bilden die zentralen Erweiterungspunkte:

| Abstraktion | Datei | Zweck |
| --- | --- | --- |
| `BenchmarkBackend` | `llmbench/backends/base.py` | Kapselt, *wie* ein Inferenz-Server gestartet, benchmarkt und gestoppt wird |
| `TelemetryProvider` | `llmbench/telemetry.py` | Kapselt, *woher* GPU-Auslastung/VRAM/Temperatur/Power kommen |

Bei den Backends dienen `LlamaCppBackend` (`llmbench/backends/llama_cpp.py`) und
`VllmBackend` (`llmbench/backends/vllm.py`) als Referenzimplementierungen. Bei der
Telemetrie existieren unter anderem `NvidiaProvider`, `AmdProvider`,
`CompositeProvider` und `DefaultProvider` als Fallback ohne Hardwarezugriff.

Weitere zentrale Module:

- `runner.py` — orchestriert einen kompletten Lauf (Profile, Modelle, Stress-Suiten)
- `hardware.py` — einmalige Hardware-Erkennung (CPU/GPU/Treiber), unabhängig von `telemetry.py`s
  laufender Sample-Erfassung
- `endpoint.py` — HTTP-Lastest gegen einen laufenden Server (TTFT, TPS, Concurrency)
- `config.py` — Konfigurationsmodell (Pydantic) inkl. `FINGERPRINT_KEYS` für Vergleichbarkeit
- `compare.py` — Vergleich zweier Ergebnisse, inkl. `--strict`-Konsistenzprüfung
- `i18n.py` / `locales/en.json` — Übersetzungsschicht (siehe Abschnitt "Sprache & i18n")

## Entwicklungs-Setup

```bash
git clone https://github.com/Lautloserspieler/llm-server-benchmark.git
cd llm-server-benchmark
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Tests und Linter vor jedem Commit/PR:

```bash
pytest -q
ruff check .
```

Beide müssen grün sein — CI prüft das Projekt unter Ubuntu und Windows über die
unterstützten Python-Versionen 3.10 bis 3.14.

## Code-Konventionen

- **`from __future__ import annotations`** steht am Kopf jeder Python-Datei — auch neue
  Module beginnen damit.
- **Typannotationen** sind Pflicht für öffentliche Funktionssignaturen (Parameter und
  Rückgabewert), analog zum bestehenden Code in `backends/base.py`/`telemetry.py`.
- **Plugin-Schnittstellen** werden als `abc.ABC` mit `@abc.abstractmethod` modelliert
  (siehe `BenchmarkBackend`, `TelemetryProvider`) — nicht als lose Duck-Typing-Konvention.
- **Sprache der Nutzeroberfläche:** Deutsch ist die Quellsprache für alle
  benutzersichtbaren Zeichenketten (Terminal-Ausgaben, Berichte, Warnungen). Englische
  Übersetzungen liegen als Wörterbuch in `llmbench/locales/en.json`. Neue
  benutzersichtbare Strings werden über `llmbench/i18n.py::_()` geroutet:

  ```python
  from llmbench.i18n import _

  print(_("Server nicht erreichbar"))
  ```

  `_()` gibt den deutschen Text unverändert zurück, wenn `_current_lang == "de"` (Default),
  sonst wird der passende Eintrag aus `en.json` nachgeschlagen (Fallback: deutscher Text,
  falls kein Eintrag existiert). Interne Log-/Debug-Ausgaben ohne Nutzerbezug müssen nicht
  über `_()` laufen. Werte kommen als Platzhalter in den Text und werden danach gefüllt –
  `_(f"...")` ist nicht übersetzbar:

  ```python
  print(_("Modell: {name}").format(name=model["name"]))
  ```

  Die Sprache wird **einmal ganz am Anfang** von `setup.bat`/`setup.sh` (bzw. den
  Start-Skripten) gewählt, in `.runtime/language` gespeichert und als `LLMBENCH_LANG` an
  Python und den Docker-Container weitergereicht; ein ausdrückliches `project.language` in
  `benchmark.yaml` hat Vorrang.
- **Installer-Skripte** (PowerShell/Bash) schreiben keine Texte direkt, sondern holen sie
  per Schlüssel: `T 'docker.check'` (PowerShell, Texte in `scripts/locales/de.psd1` +
  `en.psd1`, Platzhalter `{0}`) bzw. `ui_step docker.gpu_check` (Bash, Texte in
  `scripts/locales/de.sh` + `en.sh`, Platzhalter `%s`). Ausgabe immer über die gemeinsamen
  UI-Helfer (`scripts/lib/UI.psm1` bzw. `scripts/lib/ui.sh`: Kopfzeile, Abschnitte,
  `[+]`/`[OK]`/`[!]`/`[X]`, Menüs, Ja/Nein-Fragen, Download-Fortschritt), damit alles
  einheitlich aussieht. Vor jeder Installation wird gefragt (`Confirm-Install` /
  `ui_confirm_install`, `LLMBENCH_AUTO_INSTALL=1/0` überspringt die Frage).
- **`tests/test_i18n_coverage.py`** schlägt fehl, sobald ein `_()`-Text keinen Eintrag in
  `en.json` hat, ein Schlüssel nur in einer Sprache der Skript-Texte existiert oder ein
  Skript einen unbekannten Schlüssel benutzt.
- **Tests mocken Subprocess-/HTTP-Grenzen**, statt echte GPUs, Binaries oder Docker zu
  benötigen. Zwei kanonische Beispiele:
  - `tests/test_backends.py`: `LlamaCppBackend`-Methoden werden getestet, indem die
    darunterliegenden Funktionen (`run_llama_bench`, `start_llama_server`, ...) per
    `monkeypatch.setattr` durch Fakes ersetzt werden — kein echter `llama-bench`-Aufruf.
  - `tests/test_endpoint.py`: HTTP-Lastests werden gegen `httpx.MockTransport` gefahren,
    z. B. `httpx.MockTransport(_sse_response_handler(...))`, kombiniert mit einer
    `_PatchedAsyncClient`-Unterklasse, die den Mock-Transport statt echter Netzwerk-I/O
    verwendet. Kein echter Server nötig.

  Neue Backends/Telemetrie-Provider folgen demselben Muster: Subprocess-Aufrufe
  (`docker`, `rocm-smi`, `xpu-smi`, ...) und HTTP-Aufrufe werden gemockt, nicht gegen
  echte Hardware/Binaries getestet.

## Neues Backend hinzufügen

1. Neue Datei `llmbench/backends/<name>.py` mit einer Klasse, die `BenchmarkBackend`
   (`llmbench/backends/base.py`) implementiert. Pflicht sind die vier abstrakten Methoden:
   - `run_benchmark(model_path, profile, kind, out_dir, bench_cfg, on_progress=None)`
   - `start_server(model_path, profile, endpoint_cfg, bench_cfg, log_path)`
   - `stop_server(proc)`
   - `wait_health(base_url, timeout_s, headers=None)`
2. Zusätzlich existieren zwei **optionale, nicht-abstrakte** Hooks
   `begin_profile(...)` / `end_profile()` mit No-op-Default auf der Basisklasse. Sie
   sind für HTTP-only-Backends gedacht, die den Server einmal pro Profil statt einmal pro
   Testart starten. Die genaue Signatur richtet sich nach dem aktuellen
   `backends/base.py` zum Zeitpunkt des PRs.
3. Referenzimplementierungen: `LlamaCppBackend` (`llmbench/backends/llama_cpp.py`) für
   den Subprocess-Fall und `VllmBackend` für Docker-/HTTP-only-Backends.
4. Backend in der Factory registrieren (`backends/__init__.py`, bzw. wo `get_backend(cfg)`
   liegt) und ein Konfigurationsfeld ergänzen, das das Backend auswählt.
5. **Tests**: eigene Datei `tests/test_backends_<name>.py`, die jede Methode gegen gemockte
   Subprocess-/Docker-/HTTP-Aufrufe prüft (siehe "Code-Konventionen" oben) — kein Test darf
   einen echten Server, Container oder Download voraussetzen.
6. Siehe auch den Abschnitt "Backend-Laufzeiten installieren/entfernen" unten — jedes neue
   Backend braucht einen symmetrischen Install-/Uninstall-Pfad.

## Neuen Telemetry-Provider hinzufügen

1. Neue Klasse in `llmbench/telemetry.py` (oder einem neuen Modul, sofern die Datei zu groß
   wird), die `TelemetryProvider` implementiert. Pflicht sind:
   - `initialize() -> bool` — Verfügbarkeit prüfen (z. B. ist `rocm-smi`/`xpu-smi`
     installierbar und liefert es Daten?), `True` nur bei Erfolg zurückgeben.
   - `sample_gpus() -> list[GpuSample]` — ein `GpuSample` pro erkannter GPU.
   - `shutdown() -> None` — Ressourcen sauber freigeben.
2. `GpuSample` (Dataclass in `telemetry.py`) hat feste Felder: `index`, `util_gpu_percent`,
   `util_memory_percent`, `memory_used_bytes`, `memory_total_bytes`, `temperature_c`,
   `power_w` (optional), `compute_pids`. Liefert die Quelle ein Feld nicht (z. B.
   `compute_pids` bei AMD/ROCm), wird dokumentiert ein leerer/`None`-Wert gesetzt statt das
   Feld wegzulassen.
3. Referenz: `NvidiaProvider` (NVML-basiert, Singleton-Pattern für einmalige
   Initialisierung) und `DefaultProvider` (Fallback ohne Hardwarezugriff) in
   `llmbench/telemetry.py`.
4. `get_telemetry_provider()` (Factory in `telemetry.py`) um den neuen Provider erweitern.
   Bei mehreren gleichzeitig verfügbaren Herstellern kombiniert `CompositeProvider` die
   verfügbaren Quellen, statt nach dem Prinzip "erster gewinnt" zu arbeiten.
5. **Tests**: `tests/test_telemetry.py` um Fälle mit gemockter Provider-Ausgabe (z. B.
   gefaktes `rocm-smi --json`/`xpu-smi -j`-Output) erweitern — kein Test darf echte
   Hardware voraussetzen; ohne die jeweilige GPU muss `initialize()` sauber `False`
   zurückgeben und der Aufrufer auf `DefaultProvider`-Verhalten zurückfallen.

## Backend-Laufzeiten installieren/entfernen

Jede Laufzeit, die ein Backend benötigt (Binary, Docker-Image, Volume, ...), muss **beide**
Richtungen unterstützen:

- **Installieren**: automatisiert über `llmbench install-backend --backend <name>` bzw.
  das bestehende `llmbench install-llama-cpp` als Referenz.
- **Entfernen**: ein Gegenstück, das alles restlos zurückbaut — Container stoppen und
  entfernen, Image entfernen, ggf. Volume entfernen (Modell-Blobs standardmäßig erhalten,
  außer bei explizitem Purge-Flag) sowie das lokale State-File löschen.

Kein Backend darf **Install-only** sein. Ziel: nach der Deinstallation sind `docker ps -a`,
`docker images` und `docker volume ls` wieder so wie vor der Installation. Details zum
geplanten Mechanismus (`docker_backend.py`, `install-backend`/`uninstall-backend`) stehen in
[`ROADMAP.md`](ROADMAP.md).

## Autorenschaft, Credits und Attribution

Beiträge sollen klar der Person zugerechnet bleiben, die sie tatsächlich erstellt hat.

- **PR-Autor bleibt sichtbar:** Externe Beiträge werden regulär über Fork/Branch und Pull Request
  eingereicht. Der Maintainer übernimmt den Beitrag nicht unter seinem eigenen Namen.
- **Commit-Autorenschaft erhalten:** Commits sollen mit der Git-Identität des ursprünglichen
  Autors erstellt werden. Maintainer sollen Autor-/Co-Autor-Angaben nicht entfernen oder
  durch die eigene Identität ersetzen.
- **Gemeinsame Arbeit:** Wenn mehrere Personen substanziell an demselben Commit gearbeitet
  haben, kann Git mit `Co-authored-by: Name <email>` verwendet werden.
- **Changelog-Credit:** Relevante externe Beiträge werden im `CHANGELOG.md` mit dem
  GitHub-Handle genannt, z. B.:
  
  ```markdown
  - KV-Cache-Erkennung und verifizierte Context-Limits ergänzt — @username
  ```
- **Release Notes:** Bei einem Release werden externe Contributors mit `@username` bei den
  jeweiligen Änderungen oder in einem eigenen Contributors-Abschnitt genannt.
- **Maintainer-Änderungen an einem fremden PR:** Kleine Integrations-, Review- oder
  Konfliktlösungsänderungen ändern nicht die ursprüngliche Zuordnung des Features. Falls
  mehrere Personen wesentliche Teile beigetragen haben, werden alle Beteiligten genannt.
- **Kein Credit-Shifting:** Review, Merge oder Release durch den Maintainer macht den
  Maintainer nicht automatisch zum Autor des beigetragenen Codes.

### Merge- und Review-Modell

`main` ist geschützt. Änderungen werden über Pull Requests eingebracht und müssen die
konfigurierten Branch-Regeln und Status-Checks erfüllen. Für geschützte Bereiche ist ein
Code-Owner-Review erforderlich. Die Datei `.github/CODEOWNERS` legt den Maintainer als
Code Owner fest.

Externe Contributors benötigen dafür **keinen direkten Schreibzugriff auf `main`**. Der
übliche Ablauf ist:

```text
Fork/Branch -> Commits -> Pull Request -> CI/Review -> Maintainer-Freigabe -> Merge
```


## Externer Contribution-Workflow: Fork bis Merge

Externe Contributors benötigen keinen direkten Schreibzugriff auf dieses Repository. Der
übliche Weg ist ein eigener Fork, ein Feature-Branch und anschließend ein Pull Request
gegen `Lautloserspieler/llm-server-benchmark:main`.

### 1. Repository forken und klonen

Erstelle über GitHubs **Fork**-Button einen eigenen Fork des Repositories und klone diesen:

```bash
git clone https://github.com/<dein-username>/llm-server-benchmark.git
cd llm-server-benchmark
```

Füge anschließend das Original-Repository als `upstream` hinzu:

```bash
git remote add upstream https://github.com/Lautloserspieler/llm-server-benchmark.git
git remote -v
```

`origin` zeigt dabei auf deinen Fork, `upstream` auf das Original-Repository.

### 2. Eigenen Fork vor neuer Arbeit aktualisieren

Vor einem neuen Beitrag sollte der lokale `main` auf dem aktuellen Stand von
`upstream/main` sein:

```bash
git checkout main
git fetch upstream
git merge --ff-only upstream/main
git push origin main
```

Wenn `--ff-only` nicht möglich ist, nicht blind einen Merge erzwingen. Prüfe zuerst,
warum dein Fork von `upstream/main` abweicht.

### 3. Für jede Änderung einen eigenen Branch erstellen

Arbeite nicht direkt auf `main`. Erstelle stattdessen einen aussagekräftigen Branch:

```bash
git checkout -b feat/capability-provenance
```

Empfohlene Präfixe:

- `feat/` — neue Funktion
- `fix/` — Fehlerbehebung
- `docs/` — Dokumentation
- `test/` — Tests
- `refactor/` — interne Umstrukturierung
- `chore/` — Wartung ohne direkte Funktionsänderung

Ein Branch sollte möglichst ein klar abgegrenztes Thema behandeln.

### 4. Änderungen umsetzen und lokal prüfen

Vor dem Öffnen eines Pull Requests mindestens ausführen:

```bash
ruff check .
mypy llmbench
pytest -q
```

Für nutzersichtbare Änderungen müssen bei Bedarf beide Changelogs aktualisiert werden:

```text
CHANGELOG.md
CHANGELOG.en.md
```

Bei externen Beiträgen wird der Contributor mit dem GitHub-Handle genannt, zum Beispiel:

```markdown
- Capability-Provenance-Schema ergänzt — @username
```

Dokumentationsänderungen müssen die deutsche und englische Gegenstelle synchron halten.

### 5. Mit der eigenen Git-Identität committen

Commits sollen die Identität des tatsächlichen Autors enthalten. Prüfe bei Bedarf:

```bash
git config user.name
git config user.email
```

Es kann eine verifizierte GitHub-E-Mail oder die von GitHub bereitgestellte
`noreply`-Adresse verwendet werden; eine private persönliche E-Mail muss nicht
veröffentlicht werden.

Dann Änderungen committen und in den eigenen Fork pushen:

```bash
git add .
git commit -m "feat: add capability provenance schema"
git push -u origin feat/capability-provenance
```

### 6. Pull Request öffnen

Öffne auf GitHub einen Pull Request von:

```text
<dein-username>:feat/capability-provenance
```

nach:

```text
Lautloserspieler/llm-server-benchmark:main
```

Fülle das Pull-Request-Template vollständig aus. Wenn der PR ein Issue abschließt, kann
die Beschreibung zum Beispiel enthalten:

```text
Closes #123
```

Wenn nur ein Bezug besteht:

```text
Related to #123
```

Große Änderungen sollten nach Möglichkeit vorher in einem Issue abgestimmt werden.

### 7. CI und Review

Nach dem Öffnen des PRs:

1. GitHub Actions führt die erforderlichen Checks aus.
2. Der Maintainer kann Review-Kommentare oder Änderungswünsche hinterlassen.
3. Änderungen für das Review werden als weitere Commits auf **denselben Branch** gepusht;
   der bestehende PR aktualisiert sich automatisch.
4. Neue Commits können eine frühere Freigabe ungültig machen und ein erneutes Review
   erforderlich machen.
5. Offene Review-Diskussionen müssen vor dem Merge geklärt bzw. aufgelöst sein.
6. Die finale Freigabe erfolgt durch den Maintainer/Code Owner.

Für Review-Fixes wird kein neuer Pull Request erstellt.

### 8. Merge und Attribution

Externe Contributors mergen nicht direkt nach `main`. Sobald alle erforderlichen Checks
und Reviews erfolgreich sind, führt der Maintainer den Merge durch.

Der ursprüngliche Contributor bleibt als Autor seiner Commits sichtbar. Relevante externe
Beiträge werden zusätzlich im Changelog und in den Release Notes mit `@username`
genannt. Review, Merge oder Release durch den Maintainer übertragen die Autorenschaft
nicht auf den Maintainer.


## Pull-Request-Checkliste

Vor dem Öffnen eines PRs:

- [ ] `pytest -q` und `ruff check .` laufen lokal grün durch.
- [ ] Beide Changelogs wurden bei nutzersichtbaren Änderungen aktualisiert: `CHANGELOG.md`
  (Deutsch) und `CHANGELOG.en.md` (Englisch). Bei externen Beiträgen wird der Contributor
  mit `@username` genannt.
- [ ] Neue/geänderte Funktionalität hat Tests, die die HTTP-/Subprocess-Grenzen mocken
  (siehe "Code-Konventionen").
- [ ] Für jeden neuen `_()`-umschlossenen String wurde ein passender Eintrag in
  `llmbench/locales/en.json` ergänzt.
- [ ] Neue Backends/Telemetrie-Provider haben einen dokumentierten Install-/
  Uninstall-Pfad bzw. fallen sauber auf `DefaultProvider`-Verhalten zurück.
- [ ] Markdown-Dokumentation bleibt in Deutsch und Englisch synchron.

## Weitere Referenzen

- [`README.md`](README.md) / [`README.de.md`](README.de.md) — Nutzersicht, Quick Start, Ergebnisstruktur
- [`ROADMAP.md`](ROADMAP.md) — geplante Backends/Telemetrie-Quellen und Reihenfolge
- [`docs/DOCKER.md`](docs/DOCKER.md) — Docker-Betrieb von `llmbench` selbst
- [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md) — Abnahme vor einem Release
