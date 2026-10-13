# Backends und Runtimes

[🇬🇧 English](backends.en.md) | [Übersicht](README.md)

## Definition

Ein **Runtime/Backend** beschreibt die Software, die ein Modell ausführt. Es beschreibt
nicht, welche fachliche Aufgabe das Modell löst.

Beispiele:

- llama.cpp — Textgenerierung
- vLLM — Textgenerierung
- TGI — Textgenerierung
- Ollama — Textgenerierung und zukünftig ggf. weitere Modellarten
- faster-whisper — Speech-to-Text
- Piper — Text-to-Speech
- Diffusers — Bild-/Video-Pipelines

## Aktueller Vertrag

Text-Backends implementieren heute `BenchmarkBackend` mit:

- `run_benchmark(...)`
- `start_server(...)`
- `stop_server(...)`
- `wait_health(...)`
- optional `begin_profile(...)` / `end_profile()`
- optional `collect_kv_cache_observations(...)`

Dieser Vertrag bleibt für bestehende Text-Backends gültig, bis eine Migration ausdrücklich
beschlossen und getestet ist.

## Runtime-Verantwortung

Ein Runtime-Adapter ist verantwortlich für:

- Runtime-Installation bzw. Erkennung.
- symmetrische Deinstallation/Cleanup.
- Start, Healthcheck und Stop.
- Modell-/Volume-Mounting.
- Übersetzung generischer Request-Parameter in die Runtime-API.
- Erfassung von Runtime-Version, Image-Tag und Digest, soweit verfügbar.
- verständliche Fehlerklassifikation bei Start-/Kapazitätsfehlern.

Er ist **nicht** verantwortlich für:

- task-spezifische Qualitätsmetriken.
- Hardware-Empfehlungen.
- Report-Layout.
- Vergleich von Resultaten anderer Tasks.

## Capabilities statt Backend-Namensprüfungen

Ab Phase 1 sollen optionale Fähigkeiten explizit beschrieben werden, z. B.:

```text
endpoint
streaming
concurrency
long_context
kv_cache_observation
oom_probe
quantization
multi_model
```

Code soll eine Fähigkeit prüfen und nicht auf `backend == "..." ` verzweigen, wenn die
fachliche Entscheidung eigentlich capability-basiert ist.

## Install/Remove-Symmetrie

Kein neues Runtime-Backend darf install-only sein. Für verwaltete Laufzeiten müssen
Installation und Entfernung denselben Ressourcenbereich abdecken: Container, Images,
Zustandsdateien und optional Modell-Volumes.
