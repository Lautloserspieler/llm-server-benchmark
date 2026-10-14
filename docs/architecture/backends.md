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

| Capability | llama.cpp | vLLM | TGI |
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

## Containerisierte Backends

Neben dem nativen llama.cpp-Backend unterstützt llmbench serverbasierte Backends als
Docker-Container. Container vereinheitlichen Installation (Image-Pull), Deinstallation
(Container, Image, Volume) und das Verhalten zwischen Windows (Docker Desktop/WSL2) und
Linux (natives Docker).

### vLLM

`VllmBackend` startet das offizielle Image `vllm/vllm-openai`. Der Server lauscht im
Container auf Port 8000 und wird auf den Host-Port aus `endpoint.base_url` veröffentlicht.
Messungen laufen über die OpenAI-kompatible `/v1/completions`-Schnittstelle
(`llmbench/http_bench.py`).

Relevante Serve-Argumente:

- `--model` (Modellreferenz, lokal oder HuggingFace-Repo)
- `--tensor-parallel-size` (über `profile.tensor_parallel_size`)
- `--quantization` (über `profile.quantization`)
- `--max-model-len` (über `endpoint.context_size`)
- `--gpu-memory-utilization`, `--dtype`, zusätzliche `profile.additional_args`

### TGI

`TgiBackend` startet das offizielle Image `ghcr.io/huggingface/text-generation-inference`.
Der Container lauscht intern auf Port 80 und wird ebenfalls auf den Host-Port aus
`endpoint.base_url` veröffentlicht. Wie vLLM wird TGI über die OpenAI-kompatible
`/v1/completions`-Schnittstelle gemessen.

Relevante Launcher-Argumente:

- `--model-id` (Modellreferenz, lokal oder HuggingFace-Repo)
- `--num-shard` (über `profile.tensor_parallel_size`)
- `--quantize` (über `profile.quantization`)
- `--max-input-length` (über `profile.max_input_length` oder `endpoint.context_size`)
- `--max-total-tokens` (über `profile.max_total_tokens`)
- `--dtype`, zusätzliche `profile.additional_args`

Aktuell unterstützt der TGI-Adapter die Basiscapabilities `endpoint`, `streaming`,
`concurrency` und `long_context`. KV-Cache-Beobachtung, OOM-Probe und der lokale
Quantisierungsvergleich sind noch nicht implementiert.

## Install/Remove-Symmetrie

Kein neues Runtime-Backend darf install-only sein. Für verwaltete Laufzeiten müssen
Installation und Entfernung denselben Ressourcenbereich abdecken: Container, Images,
Zustandsdateien und optional Modell-Volumes.
