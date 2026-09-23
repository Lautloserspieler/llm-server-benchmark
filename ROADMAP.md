# Roadmap

Dieses Dokument beschreibt die geplante Weiterentwicklung von `llmbench` — was schon
funktioniert, was in Arbeit ist und was reine Idee ohne Zusage ist. Es ersetzt keine
Entscheidung im Einzelfall; Details zu einzelnen Schritten können sich noch ändern.

## Vision

`llmbench` heißt "LLM **Server** Benchmark", unterstützt aber aktuell ausschließlich
**llama.cpp** als Backend und **NVIDIA/NVML** als Telemetriequelle. Ziel dieser Roadmap ist,
den generischen Namen einzulösen: mehrere Server-Backends (über eine gemeinsame,
bereits vorhandene `BenchmarkBackend`-Abstraktion) und mehrere GPU-Hersteller (über die
vorhandene `TelemetryProvider`-Abstraktion) reproduzierbar vergleichbar zu machen — ohne
die bestehende Kernstärke des Projekts zu verwässern: nachvollziehbare, mit Beweismaterial
belegte Ergebnisse statt bloßer Tokens/s-Zahlen.

## Backend-Support-Matrix

| Backend | Status | Transportweg | Anmerkung |
| --- | --- | --- | --- |
| llama.cpp | ✅ fertig | lokales Binary (`llama-bench`/`llama-server`) | Referenz-Backend |
| vLLM | ✅ fertig (1.6.0) | Docker-Container (`vllm/vllm-openai`) | Phase A |
| TGI | 📋 geplant | Docker-Container (`ghcr.io/huggingface/text-generation-inference`) | Phase C, baut auf Phase A auf |
| Ollama | 📋 geplant | Docker-Container (`ollama/ollama`) | Phase B, eigene native API statt OpenAI-kompatibel |

Neue Backends (vLLM/Ollama/TGI) laufen bewusst **ausschließlich als Docker-Container** —
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
| Intel | 📋 geplant | `xpu-smi stats -d <id> -j` | Phase E, ein Subprozessaufruf pro GPU |

Bei mehreren gleichzeitig vorhandenen GPU-Herstellern nutzt der `CompositeProvider`
(seit 1.6.0) alle verfügbaren Provider parallel.

## Nächste Schritte (Stand: nach 1.6.0)

Für alles gilt: **Das Sprachsystem (de/en) muss überall funktionieren**, und alles läuft über
eine einheitliche, schöne Terminal-Oberfläche.

1. **Sprachsystem + Terminal-UI** ✅ *umgesetzt (unveröffentlicht)* — Sprachwahl ganz am Anfang,
   übersetzte Installer-Skripte (PowerShell/Bash), gemeinsame UI-Helfer, Test für
   Übersetzungsvollständigkeit.
2. **Setup/Installer fertigstellen** ✅ *umgesetzt (unveröffentlicht)* — NVIDIA-Treiberprüfung
   unter Windows, nach Neustart automatisch weitermachen, Backend-Auswahl im Setup, Tests der
   Installer in CI.
3. **Stresstests für alle Backends** — TTFT/Multi-Tenant/OOM/Quant sind heute fest an
   llama.cpp gebunden; künftig über `get_backend()`, nicht unterstützte Tests werden mit
   Begründung übersprungen.
4. **TGI-Backend** (Phase C), danach **Ollama-Backend** (Phase B, nutzt vorhandene GGUFs).

## Phasenplan (ursprünglich)

Die vollständige technische Planung (Architekturentscheidungen, betroffene Module, Tests)
lebt im internen Planungsdokument der Roadmap-Session; hier die grobe Reihenfolge, wie sie
dort unter "Empfohlene Reihenfolge" vorgeschlagen wurde:

1. **Phase F, Teil 1 — Projekt-Infrastruktur (dieses Dokument + CONTRIBUTING.md)**
   Risikoarm, kein Verhaltenscode, dient als Kompass für den Rest der Roadmap.
2. **Phase A — vLLM-Backend** ✅ *ausgeliefert in 1.6.0*
   Architektonischer Machbarkeitsnachweis: `BenchmarkBackend` bekommt optionale
   `begin_profile`/`end_profile`-Hooks, ein neues `docker_backend.py` orchestriert
   Container-Lifecycle, ein neues `http_bench.py` misst pp/tg/long-context über
   kalibrierte HTTP-Requests statt eines externen Kommandozeilenwerkzeugs.
3. **Phase C — TGI-Backend**
   Nahezu kostenlos direkt nach Phase A: OpenAI-kompatibel, nutzt `http_bench.py`
   unverändert, validiert die Abstraktion an einem zweiten Server.
4. **Phase B — Ollama-Backend**
   Bewusst zuletzt unter den Backends, da die native Ollama-API (`/api/generate`) am
   stärksten von der OpenAI-kompatiblen Norm abweicht.
5. **Phase D — AMD-GPU-Telemetrie** ✅ *ausgeliefert in 1.6.0*
   Unabhängiger Strang, kann parallel zu den Backend-Phasen laufen. Neuer
   `AmdProvider` gegen `rocm-smi`, plus Fix für die aktuell fehlerhafte
   Telemetriequellen-Erkennung bei Nicht-NVIDIA-Providern.
6. **Phase E — Intel-GPU-Telemetrie**
   Direkt im Anschluss an Phase D wegen gemeinsamer Infrastruktur
   (`TelemetryProvider`-ABC, `CompositeProvider`).
7. **Phase F, Rest — i18n-Sweep + Issue-/PR-Templates**
   Am Ende, da die Phasen A–E neue übersetzungspflichtige Strings einführen — ein
   einziger Audit-Durchgang danach ist effizienter als mehrere Zwischen-Durchgänge.

Die konkrete Reihenfolge ab Phase A ist eine Empfehlung, keine feste Zusage; sie kann sich
je nach Ressourcen und Rückmeldungen verschieben.

## Ideen, keine Zusagen

Die folgenden Punkte sind **unverbindliche Ideen** für eine fernere Zukunft — keine
geplanten Phasen, kein Zeitrahmen, keine Garantie, dass sie überhaupt umgesetzt werden:

- Weitere Backends: SGLang, TensorRT-LLM
- Weitere GPU-Hersteller/Telemetriequellen über AMD/Intel hinaus
- Cloud-/Remote-Inferencing-Ziele statt ausschließlich lokaler Server

Wer an einem dieser Punkte konkret interessiert ist: ein Issue mit dem
`backend_request`-Template (siehe [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/))
ist der richtige Ort, um Bedarf sichtbar zu machen.

## Verwandte Dokumente

- [`CONTRIBUTING.md`](CONTRIBUTING.md) — wie man an einer dieser Phasen mitarbeitet
- [`CHANGELOG.md`](CHANGELOG.md) — was bereits ausgeliefert wurde
- [`docs/DOCKER.md`](docs/DOCKER.md) — Docker-Betrieb von `llmbench` selbst
