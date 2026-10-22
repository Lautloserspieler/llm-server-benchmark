# Core-Architektur

[🇬🇧 English](core.en.md) | [Übersicht](README.md)

## Verantwortung des Core

Der Core orchestriert einen Benchmarklauf, ohne die fachliche Messmethode einer Task oder
die Details eines konkreten Runtime-Backends zu besitzen.

Langfristige Schichtgrenze:

```text
CLI / Terminal UI
       |
       v
Benchmark Engine
       |
       +---- Task / Workload
       |
       +---- Runtime / Backend
       |
       +---- Dataset
       |
       +---- Telemetry
       |
       v
Normalized Result
       |
       v
Reports / Compare / Export
```

Heute übernimmt `llmbench/runner.py` einen großen Teil dieser Orchestrierung für
Textgenerierung. Das bleibt bis zu einer gezielten Migration gültig.

## Core darf

- Konfiguration laden und validieren.
- Modelle/Profile auswählen.
- Lebenszyklen starten und beenden.
- Workloads planen.
- Telemetrie starten/stoppen.
- Resultate und Warnungen zusammenführen.
- Fehler, Abbruch und Cleanup koordinieren.
- Reports/Exports mit normalisierten Ergebnissen anstoßen.

## Core darf nicht

- Backend-spezifische HTTP-Pfade kennen.
- TGI-, Ollama- oder llama.cpp-Sonderfälle über verstreute Namensprüfungen enthalten.
- WER, RTF, mAP oder andere task-spezifische Qualitätsmetriken selbst berechnen.
- einen universellen Score aus nicht vergleichbaren Tasks erzeugen.
- fehlende Messwerte erfinden oder als 0 interpretieren.

## Aktuelle Referenz

Für Textgenerierung sind heute insbesondere relevant:

- `BenchmarkBackend` in `llmbench/backends/base.py`
- `get_backend()` in `llmbench/backends/`
- `run_suite()` in `llmbench/runner.py`
- `TelemetryProvider` in `llmbench/telemetry.py`

Diese APIs sind der Ausgangspunkt, nicht zwangsläufig die endgültige Multimodal-API.

## Zukünftige Erweiterung

Wenn Phase 4 (Multimodal Core) beginnt, sollen Task- und Runtime-Verantwortung explizit
getrennt werden. Vorgesehene Begriffe sind `TaskAdapter` und `RuntimeAdapter`; Phase 0
legt nur deren Verantwortungsgrenze fest und implementiert sie noch nicht.

### Groundwork (Paket `llmbench/tasks/`)

Als rein additive Vorarbeit existiert das Paket `llmbench/tasks/`:

- `TaskAdapter` (ABC): beschreibt eine Task, ihre Workloads und bildet bestehende
  Benchmark-Arten (`prompt`, `generation`, `long_context`, ...) auf Workload-IDs ab.
- `RuntimeAdapter` (ABC): deklariert, welche Tasks eine Runtime ausführen kann.
  `BackendRuntimeAdapter` ist nur eine lesende Hülle um ein bestehendes `BenchmarkBackend`
  (Textgenerierung, Capabilities); Start/Stop/Health bleiben im Backend.
- `TextGenerationTask` beschreibt den bestehenden Textpfad. Er führt nichts aus;
  `run_suite()` bleibt der Executor. `runner.py` wurde nicht verändert.

Die Adapter sind noch nicht in den Core-Ablauf eingehängt. Die Migration nach den Regeln aus
[Kompatibilität](compatibility.md) steht weiterhin aus.
