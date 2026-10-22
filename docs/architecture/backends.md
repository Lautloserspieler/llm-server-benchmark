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

| Capability | llama.cpp | vLLM | TGI | Ollama |
| --- | --- | --- | --- | --- |
| endpoint | ✅ | ✅ | ✅ | ✅ |
| streaming | ✅ | ✅ | ✅ | ✅ |
| concurrency | ✅ | ✅ | ✅ | ✅ |
| long_context | ✅ | ✅ | ✅ | ✅ |
| kv_cache_observation | ✅ | ✅ | — | — |
| oom_probe | ✅ | ✅ | ✅ | ✅ |
| quantization | ✅ | — | — | — |
| multi_model | ✅ | — | — | — |

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
- `--max-input-tokens` (über `profile.max_input_length`)
- `--max-total-tokens` (über `profile.max_total_tokens` oder `endpoint.context_size`)
- `--dtype`, zusätzliche `profile.additional_args`

Aktuell unterstützt der TGI-Adapter die Basiscapabilities `endpoint`, `streaming`,
`concurrency` und `long_context` sowie den HTTP-Kontext-/OOM-Probe (siehe unten).
KV-Cache-Beobachtung, lokaler Quantisierungsvergleich und Multi-Model-Stress sind nicht
implementiert.

### Ollama

`OllamaBackend` startet das offizielle Image `ollama/ollama` und verwendet die native
`/api/generate`-API auf Port 11434. Ollama kann mit reinen CPU-Profilen oder mit einer
durch Docker bereitgestellten NVIDIA-GPU laufen.

Vorhandene Ollama-Modellnamen liegen im persistenten Backend-Volume unter
`/root/.ollama`. Fehlt ein Library-Modell, wird es vor dem Benchmark geladen. Lokale
GGUF-Dateien werden über Ollamas Blob- und Create-APIs importiert; gesplittete GGUF-Sätze
werden geprüft und Shard für Shard hochgeladen.

Relevante Profileinstellungen:

- `ollama_num_ctx` -> Ollama `num_ctx`
- `ollama_num_gpu` -> Ollama `num_gpu`
- `gpu_layers: 0` oder `ollama_num_gpu: 0` hält den Container im CPU-Modus

**Hinweis zum OOM-/Kontext-Probe:** Der Ollama-Probe setzt pro Stufe `num_ctx = level + 512`
und zwingt Ollama damit gegebenenfalls, das Modell mit neuer KontextgrÃ¶ÃŸe neu zu laden.
`cold_start_seconds` im OOM-Ergebnis beschreibt dann nicht das reale Ladeverhalten
(Containerstart plus erzwungenes Neuladen). Meldet Ollama kein `prompt_eval_count`, gilt die
Stufe als bestanden, aber mit `actual_unverified: true`; sie zÃ¤hlt nicht in
`max_stable_prompt_tokens`. Eine gemeldete LÃ¤nge nahe `num_ctx` ist nur dann
`context_truncated`, wenn die Zielstufe nicht erreicht wurde; eine Tokenizer-Abweichung Ã¼ber
512 Tokens fÃ¼hrt nicht zum Fehlschlag (Flag `truncated_at_num_ctx`).

Benchmark-Anfragen verwenden `raw: true`, damit ein Ollama-Modelltemplate den synthetischen
Benchmark-Prompt nicht verändert. Der aktuelle Adapter stellt `endpoint`, `streaming`,
`concurrency`, `long_context` und den HTTP-Kontext-/OOM-Probe bereit;
KV-Cache-Beobachtung, Quantisierungsvergleich und Multi-Model-Stress sind nicht angebunden.

## Generischer Kontext-/OOM-Probe über HTTP

`oom_probe` ist für vLLM, TGI und Ollama über `llmbench/backends/http_probe.py` umgesetzt.
`llmbench.stress.oom` startet pro Kontextstufe einen frischen Server (bei TGI/vLLM mit
`--max-total-tokens` bzw. `--max-model-len`, bei Ollama mit `options.num_ctx`), sendet einen
einzelnen nicht gestreamten Request mit Fülltext und stoppt den Server danach wieder, auch
nach Fehlern, Timeouts und Abbruch. Die Tokenzahl stammt aus der Serverantwort
(`usage.prompt_tokens` bzw. `prompt_eval_count`), nicht aus einer Schätzung.

Fehlschläge werden als `failure_category` klassifiziert (Heuristik auf HTTP-Status und
Fehlertext des Servers):

| Kategorie | Bedeutung |
| --- | --- |
| `out_of_memory` | Server meldet CUDA-/Speicherfehler (z. B. `requires more system memory`) |
| `context_exceeded` | Eingabe überschreitet das konfigurierte Limit (z. B. TGI `Input validation error`) |
| `context_truncated` | Ollama hat den Prompt still auf `num_ctx` gekürzt; zählt nicht als bestanden |
| `timeout` | Request-Timeout (`endpoint.timeout_seconds`) |
| `connection_error` | Verbindung verweigert/gekappt, typisch nach OOM-Kill des Containers |
| `model_not_found`, `server_error`, `client_error`, `invalid_response` | übrige Fälle, nie `ok` |

Die Pfade sind ohne GPU/Docker gegen einen lokalen Fake-HTTP-Server getestet
(`tests/test_http_probe.py`). Eine Validierung gegen echte GPU-Container steht aus; die
Fehlertext-Heuristik kann bei neueren Upstream-Versionen abweichen und fällt dann in
`server_error`/`client_error` zurück.

**Bewusst weiter unsupported** (`status: skipped`, `reason: backend_capability_missing`,
Exitcode 2):

- `quantization`: Der Vergleich basiert auf lokalen GGUF-Varianten und llama-bench-förmigen
  Ergebnissen. vLLM/TGI quantisieren HF-Gewichte zur Laufzeit (`--quantization`/`--quantize`),
  Ollama importiert GGUF nur über die Create-API; ein vergleichbarer, reproduzierbarer Vertrag
  existiert nicht.
- `multi_model`: Die Backend-Instanzen verwalten genau einen Container (fester
  Containername, ein Host-Port). Zwei gleichzeitige Server würden sich gegenseitig stoppen;
  Ollamas parallele Modellresidenz bräuchte einen eigenen Workload statt zweier Server.

## Install/Remove-Symmetrie

Kein neues Runtime-Backend darf install-only sein. Für verwaltete Laufzeiten müssen
Installation und Entfernung denselben Ressourcenbereich abdecken: Container, Images,
Zustandsdateien und optional Modell-Volumes.
