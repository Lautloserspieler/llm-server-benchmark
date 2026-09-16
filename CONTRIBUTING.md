# Beitragen zu llmbench

Danke, dass du an `llmbench` mitarbeiten willst. Dieses Dokument beschreibt Architektur,
Entwicklungs-Setup, Code-Konventionen und den Ablauf für Pull Requests.

## Projektzweck

`llmbench` ist ein Python-CLI-Tool zum **reproduzierbaren** Benchmarking von lokalem
LLM-Server-Inferencing. Statt nur einer Tokens/s-Zahl erfasst es die komplette Umgebung
(GPU, Treiber, Backend-Build, Modell-Hashes, Benchmark-Konfiguration, Energiezustand), damit
zwei Systeme unter nachweisbar vergleichbaren Bedingungen gegenübergestellt werden können.

Trotz des generischen Namens "LLM **Server** Benchmark" unterstützt das Projekt aktuell
ausschließlich **llama.cpp** als Backend und **NVIDIA/NVML** als Telemetriequelle. Das ist
kein Designziel, sondern der aktuelle Stand — siehe [`ROADMAP.md`](ROADMAP.md) für geplante
Erweiterungen. Beides ist im Code bereits als Plugin-Punkt vorgesehen (siehe unten), damit
neue Backends/Telemetriequellen ohne Eingriffe in den Kern ergänzt werden können.

## Architektur im Überblick

Zwei abstrakte Basisklassen bilden die zentralen Erweiterungspunkte:

| Abstraktion | Datei | Zweck |
| --- | --- | --- |
| `BenchmarkBackend` | `llmbench/backends/base.py` | Kapselt, *wie* ein Inferenz-Server gestartet, benchmarkt und gestoppt wird |
| `TelemetryProvider` | `llmbench/telemetry.py` | Kapselt, *woher* GPU-Auslastung/VRAM/Temperatur/Power kommen |

Aktuell existiert je Abstraktion eine konkrete Implementierung: `LlamaCppBackend`
(`llmbench/backends/llama_cpp.py`) und `NvidiaProvider` (`llmbench/telemetry.py`, NVML-basiert),
daneben ein `DefaultProvider` als Telemetrie-Fallback ohne Hardwarezugriff.

Weitere zentrale Module:

- `runner.py` — orchestriert einen kompletten Lauf (Profile, Modelle, Stress-Suiten)
- `hardware.py` — einmalige Hardware-Erkennung (CPU/GPU/Treiber), unabhängig von `telemetry.py`s
  laufender Sample-Erfassung
- `endpoint.py` — HTTP-Lastest gegen einen laufenden Server (TTFT, TPS, Concurrency)
- `config.py` — Konfigurationsmodell (Pydantic) inkl. `FINGERPRINT_KEYS` für Vergleichbarkeit
- `compare.py` — Vergleich zweier Ergebnisse, inkl. `--strict`-Konsistenzprüfung
- `i18n.py` / `locales/en.json` — Übersetzungsschicht (siehe Abschnitt "Sprache & i18n")

> **In Arbeit (parallele Branches, noch nicht gemerged):** Ein vLLM-Backend über Docker
> (`llmbench/backends/vllm.py`, siehe Phase A der Roadmap) und ein AMD-GPU-Telemetrie-Provider
> über `rocm-smi` (Phase D) werden aktuell in separaten Branches entwickelt. Bis zum Merge
> gelten die Beispiele unten als Referenz auf den geplanten, noch nicht finalen Code.

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

Beide müssen grün sein — CI läuft dieselben Prüfungen auf Ubuntu und Windows mit
Python 3.10 und 3.12.

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
  über `_()` laufen.
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
2. Zusätzlich existieren (Stand Phase A der Roadmap) zwei **optionale, nicht-abstrakte**
   Hooks `begin_profile(...)` / `end_profile()` mit No-op-Default auf der Basisklasse —
   gedacht für HTTP-only-Backends, die den Server einmal pro Profil starten wollen statt
   einmal pro Testart. Bestehende Backends müssen sie nicht überschreiben; nur relevant,
   wenn dein Backend davon profitiert. Die genaue Signatur richtet sich nach dem Stand von
   `backends/base.py` zum Zeitpunkt deines PRs.
3. Referenzimplementierung: `LlamaCppBackend` (`llmbench/backends/llama_cpp.py`) für den
   Subprocess-Fall. Sobald gemergt, ist `VllmBackend` (Phase A, Docker-Container-basiert)
   die Referenz für HTTP-only-Backends.
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
   Bei mehreren gleichzeitig verfügbaren Herstellern ist eine `CompositeProvider`-Lösung
   geplant (siehe ROADMAP.md, Phase D) statt "erster gewinnt".
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

## Pull-Request-Checkliste

Vor dem Öffnen eines PRs:

- [ ] `pytest -q` und `ruff check .` laufen lokal grün durch.
- [ ] `CHANGELOG.md` wurde aktualisiert — deutschsprachig, unter einer versionierten
  `##`-Überschrift, mit thematischer `###`-Unterüberschrift, passend zum bestehenden Stil
  (siehe vorhandene Einträge).
- [ ] Neue/geänderte Funktionalität hat Tests, die die HTTP-/Subprocess-Grenzen mocken
  (siehe "Code-Konventionen").
- [ ] Für jeden neuen `_()`-umschlossenen String wurde ein passender Eintrag in
  `llmbench/locales/en.json` ergänzt.
- [ ] Neue Backends/Telemetrie-Provider haben einen dokumentierten Install-/
  Uninstall-Pfad bzw. fallen sauber auf `DefaultProvider`-Verhalten zurück.

## Weitere Referenzen

- [`README.md`](README.md) — Nutzersicht, Quick Start, Ergebnisstruktur
- [`ROADMAP.md`](ROADMAP.md) — geplante Backends/Telemetrie-Quellen und Reihenfolge
- [`docs/DOCKER.md`](docs/DOCKER.md) — Docker-Betrieb von `llmbench` selbst
- [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md) — Abnahme vor einem Release
