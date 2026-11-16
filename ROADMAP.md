# Roadmap

🇩🇪 Deutsch | [🇬🇧 English](ROADMAP.en.md)

Dieses Dokument beschreibt die geplante Weiterentwicklung von `llmbench` — was schon
funktioniert, was in Arbeit ist und was reine Idee ohne Zusage ist. Es ersetzt keine
Entscheidung im Einzelfall; Details zu einzelnen Schritten können sich noch ändern.

## Vision

`llmbench` heißt "LLM **Server** Benchmark" und unterstützt inzwischen neben dem nativen
**llama.cpp** auch **vLLM** über Docker sowie Telemetrie für **NVIDIA/NVML** und
**AMD/rocm-smi**. Ziel dieser Roadmap ist, den generischen Ansatz weiter auszubauen:
mehrere Server-Backends über die gemeinsame `BenchmarkBackend`-Abstraktion und mehrere
GPU-Hersteller über die `TelemetryProvider`-Abstraktion reproduzierbar vergleichbar zu
machen — ohne die Kernstärke des Projekts zu verwässern: nachvollziehbare, mit
Beweismaterial belegte Ergebnisse statt bloßer Tokens/s-Zahlen.

## Backend-Support-Matrix

| Backend | Status | Transportweg | Anmerkung |
| --- | --- | --- | --- |
| llama.cpp | ✅ fertig | lokales Binary (`llama-bench`/`llama-server`) | Referenz-Backend |
| vLLM | ✅ fertig (1.6.0) | Docker-Container (`vllm/vllm-openai`) | Phase A |
| TGI | ⛔ wird eingestellt (Entscheidung in #167; Ersatz SGLang, geplant für 1.8.0) — bis zur Entfernung Beta ohne Validierung | Docker-Container (`ghcr.io/huggingface/text-generation-inference`) | Phase 2, OpenAI-kompatibles `/v1/completions`-Backend |
| Ollama | ✅ fertig (1.6.5) | Docker-Container (`ollama/ollama`) | Phase 3, native `/api/generate`-API; lokaler GGUF-Import über Blob/Create-APIs |
| SGLang | 📋 geplant (#167) | Docker-Container (geplant) | Beta fuer 1.8.0; vollstaendige Integration und Stabilitaetsvalidierung fuer 1.9.0 geplant; noch kein Adapter |

„Fertig“ bezeichnet die Implementierung, keine pauschale Hardwarefreigabe.
Der [v1.7.0-Qualifikationsstand](docs/validation/v1.7.0-qualification.md)
enthaelt die vorhandenen Messnachweise und noch offenen Kombinationen.

Die vorhandenen Server-Adapter (vLLM/Ollama sowie der noch enthaltene TGI-Adapter) laufen bewusst **ausschließlich als Docker-Container** —
kein natives/bare-metal-Setup wie bei llama.cpp. Docker (inklusive
`nvidia-container-toolkit` für GPU-Zugriff) wird damit zur Voraussetzung für diese drei
Backends. Das vereinfacht Installation/Deinstallation erheblich (siehe
[`CONTRIBUTING.md`](CONTRIBUTING.md#backend-laufzeiten-installierenentfernen)) und macht
Windows (Docker Desktop/WSL2) und Linux (natives Docker) technisch identisch, statt eine
weitere Plattform-Sonderbehandlung wie bei llama.cpp einzuführen.

## GPU-Telemetrie-Matrix

| Hersteller | Status | Quelle | Anmerkung |
| --- | --- | --- | --- |
| NVIDIA | ✅ fertig | NVML (`nvidia-ml-py`) | Auslastung, VRAM, Temperatur, Power, Compute-PIDs |
| AMD | ✅ fertig (1.6.0) | `rocm-smi --json` | Phase D, `compute_pids` bleibt vorerst leer |
| Intel | ✅ fertig | `xpu-smi stats -d <id> -j` | Phase E, ein Subprozessaufruf pro GPU; `compute_pids` bleibt leer |

Bei mehreren gleichzeitig vorhandenen GPU-Herstellern nutzt der `CompositeProvider`
(seit 1.6.0) alle verfügbaren Provider parallel.

NVIDIA-Messnachweise sind im Qualifikationsprotokoll dokumentiert; echte AMD- und
Intel-Traces fehlen dort weiterhin. Implementierte Provider gelten dadurch nicht
automatisch als auf jeder Hardware validiert.

## Phase 0 — Architekturverträge ✅ *umgesetzt/merged*

Bevor weitere Backends und spätere multimodale Workloads in den Core einziehen, sind die
Schichtgrenzen und Kompatibilitätsregeln verbindlich dokumentiert. Die Verträge trennen
**Task**, **Runtime/Backend**, **Workload**, **Metrik**, **Telemetrie** und **Resultat** und
schreiben ausdrücklich fest, dass der funktionierende Textpfad nicht per Big-Bang-Rewrite
ersetzt wird.

Siehe [docs/architecture/](docs/architecture/README.md) für Core, Backends/Runtimes,
Tasks/Workloads, Telemetrie, Resultate und Kompatibilität.

## Phase 1 — Backend-Capabilities und backend-unabhängige Stresstests ✅ *umgesetzt/merged*

`BenchmarkBackend` besitzt jetzt eine explizite `BackendCapabilities`-Beschreibung.
TTFT, OOM/Kontext, Quantisierung und Multi-Tenant instanziieren kein llama.cpp-Backend
mehr direkt, sondern verwenden `get_backend()` und prüfen benötigte Fähigkeiten.

Ein nicht unterstützter Workload ist kein Benchmarkfehler: Er schreibt ein strukturiertes
`status: skipped` mit `reason: backend_capability_missing` und liefert Exitcode 2.
llama.cpp unterstützt die vorhandenen vier Stresspfade. vLLM, TGI und Ollama führen den
generischen TTFT/Concurrency-Stresstest und den HTTP-Kontext-/OOM-Probe aus
(`llmbench/backends/http_probe.py`, inkl. Fehlerklassifikation `out_of_memory`,
`context_exceeded`, `context_truncated`, `timeout`, `connection_error`; per Fake-HTTP-Server
getestet; vorhandene Ollama-GPU-Kontextnachweise und deren Grenzen stehen im
[Qualifikationsprotokoll](docs/validation/v1.7.0-qualification.md)). Lokaler Quantisierungsvergleich
und Multi-Model-Stress bleiben dort explizit unsupported, weil kein reproduzierbarer
Adaptervertrag existiert (siehe docs/architecture/backends.md).

Die llama.cpp-spezifischen HTTP-Endpunkte für den Kontext-/OOM-Probe liegen nun im
llama.cpp-Backend statt im generischen Stress-Runner.

## Multimodal Groundwork 🚧 *in Arbeit (unveröffentlicht)*

Additive Vorarbeit für spätere multimodale Tasks, ohne den Textpfad zu verändern:
Paket `llmbench/tasks/` mit `TaskAdapter`/`RuntimeAdapter`, Task-ID-Enum, Workload-Registry und
`TextGenerationTask`; validiertes Dataset-Manifest (Quelle, Version, Lizenz, SHA-256,
Sample-Auswahl); optionale Felder `task`/`workload`/`dataset` in Schema v3 (bewusst kein v4,
alte Resultate bleiben unverändert lesbar). Es gibt keinen universellen Score, und fehlende
Werte werden nie als 0 gespeichert. Noch **nicht** enthalten: multimodale Backends, Workloads
oder Runner-Integration. Siehe [docs/architecture/](docs/architecture/README.md).

## Aktueller Entwicklungspfad: 1.7.0 bis 2.0.0

Die Projektversion ist weiterhin **1.6.5**. Arbeiten fuer 1.7.0 sind auf `main`
integriert; die Release-Abnahme ist noch offen. Release-Nummern beschreiben
geplanten Umfang und keine zugesagten Termine.

| Release | Schwerpunkt | Tracking |
| --- | --- | --- |
| 1.7.0 | llama.cpp, vLLM und Ollama stabilisieren; HTTP-Probes, Telemetrie, Plattformen und Hardwareabnahme | [#116](https://github.com/Lautloserspieler/llm-server-benchmark/issues/116), #121–#124; TGI-Validierung #120 entfaellt durch #167 |
| 1.8.0 | Tokenkalibrierung, Lastprofile, SLO/Goodput und Reports; TGI entfernen und SGLang-Beta einfuehren | [#117](https://github.com/Lautloserspieler/llm-server-benchmark/issues/117), #125–#128, [#167](https://github.com/Lautloserspieler/llm-server-benchmark/issues/167) |
| 1.9.0 | Adaptive Kapazitaet, Engine-Vergleich, Multi-Turn und Statistik; SGLang-Integration und Stabilitaet vervollstaendigen | [#118](https://github.com/Lautloserspieler/llm-server-benchmark/issues/118), #129–#132, #167 |
| 2.0.0 | Multimodale Orchestrierung, STT, TTS, Bild, OCR, Embeddings und Abnahme | [#119](https://github.com/Lautloserspieler/llm-server-benchmark/issues/119), #133–#139 |

Fuer 1.7.0 bleiben insbesondere CUDA und Windows auf echter Hardware, eine zweite
Ollama-Version, die geforderten Kontextstufen, wiederholte Referenzmessungen und
nachpruefbare Langzeit-Soak-Artefakte offen. AMD/Intel werden bei verfuegbarer
Hardware geprueft und andernfalls als nicht getestet ausgewiesen. Details und
der Abgleich der weiterhin offenen Issues stehen im
[Qualifikationsprotokoll](docs/validation/v1.7.0-qualification.md).

## Bereits integrierte Grundlagen

Für alles gilt: **Das Sprachsystem (de/en) muss überall funktionieren**, und alles läuft über
eine einheitliche, schöne Terminal-Oberfläche.

1. **Sprachsystem + Terminal-UI** ✅ *umgesetzt (unveröffentlicht)* — Sprachwahl ganz am Anfang,
   übersetzte Installer-Skripte (PowerShell/Bash), gemeinsame UI-Helfer, Test für
   Übersetzungsvollständigkeit.
2. **Setup/Installer fertigstellen** ✅ *umgesetzt (unveröffentlicht)* — NVIDIA-Treiberprüfung
   unter Windows, nach Neustart automatisch weitermachen, Backend-Auswahl im Setup, Tests der
   Installer in CI.
3. **Stresstests über Backend-Capabilities** ✅ *umgesetzt/merged* — die Stress-Pfade laufen über `get_backend()`; nicht unterstützte Workloads werden strukturiert mit Begründung übersprungen.
4. **TGI-Backend** (Phase C) — wird eingestellt (#167), keine weitere Validierung für 1.7.0; bis zur Entfernung bleibt es Beta; `TgiBackend` ist in der Backend-Factory, der Konfiguration, dem Setup und dem Runner neben `VllmBackend` als containerisiertes, OpenAI-kompatibles HTTP-Backend registriert. **Ollama-Backend** (Phase B, nutzt vorhandene GGUFs) ist in 1.6.5 als stabil ausgeliefert (CPU und GPU).

## Phasenplan (ursprünglich)

Der folgende urspruengliche Phasenplan dokumentiert die Entstehung der Adapter.
Fuer neue Arbeiten gelten der Entwicklungspfad oben und Entscheidung #167.

1. **Phase F, Teil 1 — Projekt-Infrastruktur (dieses Dokument + CONTRIBUTING.md)**
   Risikoarm, kein Verhaltenscode, dient als Kompass für den Rest der Roadmap.
2. **Phase A — vLLM-Backend** ✅ *ausgeliefert in 1.6.0*
   Architektonischer Machbarkeitsnachweis: `BenchmarkBackend` bekommt optionale
   `begin_profile`/`end_profile`-Hooks, ein neues `docker_backend.py` orchestriert
   Container-Lifecycle, ein neues `http_bench.py` misst pp/tg/long-context über
   kalibrierte HTTP-Requests statt eines externen Kommandozeilenwerkzeugs.
3. **Phase C — TGI-Backend** ⛔ *durch #167 abgeloest*
   Der Adapter wurde umgesetzt, wird aber nicht weiter qualifiziert oder als
   Legacy-Backend gepflegt. Entfernung und Ersatz durch SGLang sind geplant.
4. **Phase B — Ollama-Backend**
   Bewusst zuletzt unter den Backends, da die native Ollama-API (`/api/generate`) am
   stärksten von der OpenAI-kompatiblen Norm abweicht.
5. **Phase D — AMD-GPU-Telemetrie** ✅ *ausgeliefert in 1.6.0*
   Unabhängiger Strang, kann parallel zu den Backend-Phasen laufen. Neuer
   `AmdProvider` gegen `rocm-smi`, plus Fix für die aktuell fehlerhafte
   Telemetriequellen-Erkennung bei Nicht-NVIDIA-Providern.
6. **Phase E — Intel-GPU-Telemetrie** ✅ *umgesetzt (unveröffentlicht)*
   Direkt im Anschluss an Phase D wegen gemeinsamer Infrastruktur
   (`TelemetryProvider`-ABC, `CompositeProvider`).
7. **Phase F, Rest — i18n-Sweep + Issue-/PR-Templates**
   Am Ende, da die Phasen A–E neue übersetzungspflichtige Strings einführen — ein
   einziger Audit-Durchgang danach ist effizienter als mehrere Zwischen-Durchgänge.

Die historische Reihenfolge ist keine aktuelle Aufgabenliste.

## Ideen, keine Zusagen

Die folgenden Punkte sind **unverbindliche Ideen** für eine fernere Zukunft — keine
geplanten Phasen, kein Zeitrahmen, keine Garantie, dass sie überhaupt umgesetzt werden:

- Weitere Backends ueber das bereits geplante SGLang hinaus: TensorRT-LLM
- Weitere GPU-Hersteller/Telemetriequellen über AMD/Intel hinaus
- Cloud-/Remote-Inferencing-Ziele statt ausschließlich lokaler Server

Wer an einem dieser Punkte konkret interessiert ist: ein Issue mit dem
`backend_request`-Template (siehe [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/))
ist der richtige Ort, um Bedarf sichtbar zu machen.

## Verwandte Dokumente

- [`CONTRIBUTING.md`](CONTRIBUTING.md) — wie man an einer dieser Phasen mitarbeitet
- [`CHANGELOG.md`](CHANGELOG.md) — was bereits ausgeliefert wurde
- [`docs/DOCKER.md`](docs/DOCKER.md) — Docker-Betrieb von `llmbench` selbst
- [`docs/architecture/README.md`](docs/architecture/README.md) — Architekturverträge für v1.7+
