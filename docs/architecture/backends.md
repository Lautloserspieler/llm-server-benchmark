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

Seit Phase 1 werden optionale Fähigkeiten über `BackendCapabilities` explizit beschrieben:

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

Code prüft eine Fähigkeit und verzweigt nicht auf `backend == "..."`, wenn die
fachliche Entscheidung capability-basiert ist.

Aktueller Adapterstand:

| Capability | llama.cpp | vLLM | Ollama |
| --- | --- | --- | --- |
| endpoint | ✅ | ✅ | ✅ |
| streaming | ✅ | ✅ | ✅ |
| concurrency | ✅ | ✅ | ✅ |
| long_context | ✅ | ✅ | ✅ |
| kv_cache_observation | ✅ | ✅ | — |
| oom_probe | ✅ | — | — |
| quantization | ✅ | — | — |
| multi_model | ✅ | — | — |

Ein fehlendes Häkchen bedeutet nicht, dass die Upstream-Runtime diese Funktion grundsätzlich
nicht besitzt. Es bedeutet, dass der aktuelle llmbench-Adapter dafür noch keinen
reproduzierbaren Benchmarkvertrag anbietet.

## Ollama-Backend

Ollama läuft ausschließlich als Docker-Container (`ollama/ollama`) und verwendet die
eigene, nicht OpenAI-kompatible API auf Port `11434`. Prompt-, Generation- und
Long-Context-Messungen werden über `POST /api/generate` abgewickelt.

Bei einem lokalen GGUF-Modell mountet der Adapter das Verzeichnis der Datei schreibgeschützt
nach `/models`, generiert ein minimales `Modelfile` und registriert das Modell vor dem
Health-Check über `POST /api/create`. Alternativ kann ein bereits im Ollama-Image oder
lokal gepullter Modellname verwendet werden.

Die nativ andersartige API wird im gemeinsamen HTTP-Benchmark-Layer durch den Stil
`ollama_native` gekapselt, sodass Terminal-, HTML-, PDF- und CSV-Berichte dieselben
vergleichbaren Metriken wie bei llama.cpp und vLLM liefern.

## Install/Remove-Symmetrie

Kein neues Runtime-Backend darf install-only sein. Für verwaltete Laufzeiten müssen
Installation und Entfernung denselben Ressourcenbereich abdecken: Container, Images,
Zustandsdateien und optional Modell-Volumes.
