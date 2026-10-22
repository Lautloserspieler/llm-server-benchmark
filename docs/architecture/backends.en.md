# Backends and runtimes

[🇩🇪 Deutsch](backends.md) | [Overview](README.en.md)

## Definition

A **runtime/backend** is the software that executes a model. It does not define the
high-level task solved by the model.

Examples:

- llama.cpp — text generation
- vLLM — text generation
- TGI — text generation
- Ollama — text generation and potentially other model types later
- faster-whisper — speech-to-text
- Piper — text-to-speech
- Diffusers — image/video pipelines

## Current contract

Text backends currently implement `BenchmarkBackend` with:

- `run_benchmark(...)`
- `start_server(...)`
- `stop_server(...)`
- `wait_health(...)`
- optional `begin_profile(...)` / `end_profile()`
- optional `collect_kv_cache_observations(...)`

This contract remains valid for existing text backends until a migration is explicitly
designed and regression-tested.

## Runtime responsibility

A runtime adapter is responsible for:

- runtime installation or detection,
- symmetrical uninstall/cleanup,
- start, health checking, and stop,
- model/volume mounting,
- translating generic request parameters to the runtime API,
- capturing runtime version, image tag, and digest where available,
- clear error classification for startup/capacity failures.

It is **not** responsible for:

- task-specific quality metrics,
- hardware recommendations,
- report layout,
- comparing results from unrelated tasks.

## Capabilities instead of backend-name checks

Starting with Phase 1, optional behavior is represented explicitly through `BackendCapabilities`:

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

Code checks a capability instead of branching on `backend == "..."` when the decision is
capability-based.

Current adapter state:

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

A missing check mark does not mean the upstream runtime can never perform that operation.
It means the current llmbench adapter does not yet expose a reproducible benchmark contract
for it.

## Containerized backends

In addition to the native llama.cpp backend, llmbench supports server-based backends as
Docker containers. Containers unify installation (image pull), removal (container, image,
volume), and behavior between Windows (Docker Desktop/WSL2) and Linux (native Docker).

### vLLM

`VllmBackend` runs the official image `vllm/vllm-openai`. The server listens on port 8000
inside the container and is published to the host port from `endpoint.base_url`. Measurements
use the OpenAI-compatible `/v1/completions` endpoint (`llmbench/http_bench.py`).

Relevant serve arguments:

- `--model` (model reference, local or HuggingFace repo)
- `--tensor-parallel-size` (via `profile.tensor_parallel_size`)
- `--quantization` (via `profile.quantization`)
- `--max-model-len` (via `endpoint.context_size`)
- `--gpu-memory-utilization`, `--dtype`, additional `profile.additional_args`

### TGI

`TgiBackend` runs the official image `ghcr.io/huggingface/text-generation-inference`.
The container listens internally on port 80 and is likewise published to the host port from
`endpoint.base_url`. Like vLLM, TGI is measured through the OpenAI-compatible
`/v1/completions` endpoint.

Relevant launcher arguments:

- `--model-id` (model reference, local or HuggingFace repo)
- `--num-shard` (via `profile.tensor_parallel_size`)
- `--quantize` (via `profile.quantization`)
- `--max-input-tokens` (via `profile.max_input_length`)
- `--max-total-tokens` (via `profile.max_total_tokens` or `endpoint.context_size`)
- `--dtype`, additional `profile.additional_args`

Currently the TGI adapter supports the base capabilities `endpoint`, `streaming`,
`concurrency`, and `long_context`, plus the HTTP context/OOM probe (see below). KV-cache
observation, local quantization comparison, and multi-model stress are not implemented.

### Ollama

`OllamaBackend` runs the official `ollama/ollama` image and uses the native
`/api/generate` API on port 11434. Ollama can run with CPU-only profiles or with an
NVIDIA GPU passed through by Docker.

Existing Ollama model names are stored in the persistent `/root/.ollama` backend volume.
A missing library model is pulled before the benchmark. Local GGUF files are imported via
Ollama's blob and create APIs; split GGUF sets are validated and uploaded shard by shard.

Relevant profile settings:

- `ollama_num_ctx` -> Ollama `num_ctx`
- `ollama_num_gpu` -> Ollama `num_gpu`
- `gpu_layers: 0` or `ollama_num_gpu: 0` keeps the container in CPU mode

**Note on the OOM/context probe:** per level the Ollama probe sets `num_ctx = level + 512`,
which may force Ollama to reload the model with the new context size. `cold_start_seconds`
in the OOM result therefore does not describe real load behaviour (container start plus a
forced reload). If Ollama reports no `prompt_eval_count`, the level counts as passed but
carries `actual_unverified: true` and does not contribute to `max_stable_prompt_tokens`. A
reported length close to `num_ctx` is only `context_truncated` when the target level was not
reached; a tokenizer deviation above 512 tokens does not fail the level (flag
`truncated_at_num_ctx`).

Benchmark requests use `raw: true` so an Ollama model template does not rewrite the
synthetic benchmark prompt. The current adapter exposes `endpoint`, `streaming`,
`concurrency`, `long_context`, and the HTTP context/OOM probe; KV-cache observation,
quantization comparison, and multi-model stress are not exposed.

## Generic context/OOM probe over HTTP

`oom_probe` is implemented for vLLM, TGI, and Ollama in `llmbench/backends/http_probe.py`.
`llmbench.stress.oom` starts a fresh server per context level (TGI/vLLM with
`--max-total-tokens` / `--max-model-len`, Ollama with `options.num_ctx`), sends one
non-streamed request with filler text, and stops the server afterwards, also after
errors, timeouts, and cancellation. The token count comes from the server response
(`usage.prompt_tokens` or `prompt_eval_count`), not from an estimate.

Failures are classified as `failure_category` (a heuristic over HTTP status and server
error text):

| Category | Meaning |
| --- | --- |
| `out_of_memory` | Server reports a CUDA/memory error (e.g. `requires more system memory`) |
| `context_exceeded` | Input exceeds the configured limit (e.g. TGI `Input validation error`) |
| `context_truncated` | Ollama silently truncated the prompt to `num_ctx`; does not count as passed |
| `timeout` | Request timeout (`endpoint.timeout_seconds`) |
| `connection_error` | Connection refused/dropped, typical after an OOM kill of the container |
| `model_not_found`, `server_error`, `client_error`, `invalid_response` | remaining cases, never `ok` |

The paths are tested without GPU/Docker against a local fake HTTP server
(`tests/test_http_probe.py`). Validation against real GPU containers is still pending; the
error-text heuristic may drift with newer upstream versions and then falls back to
`server_error`/`client_error`.

**Deliberately still unsupported** (`status: skipped`,
`reason: backend_capability_missing`, exit code 2):

- `quantization`: The comparison relies on local GGUF variants and llama-bench-shaped
  results. vLLM/TGI quantize HF weights at runtime (`--quantization`/`--quantize`), and
  Ollama only imports GGUF through its create API; no comparable, reproducible contract
  exists.
- `multi_model`: Backend instances manage exactly one container (fixed container name, one
  host port). Two concurrent servers would stop each other; Ollama's parallel model
  residency would need its own workload rather than two servers.

## Install/remove symmetry

No new managed runtime may be install-only. Installation and removal must cover the same
resource scope: containers, images, state files, and optional model volumes.
