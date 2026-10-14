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
- `--max-input-length` (via `profile.max_input_length` or `endpoint.context_size`)
- `--max-total-tokens` (via `profile.max_total_tokens`)
- `--dtype`, additional `profile.additional_args`

Currently the TGI adapter supports the base capabilities `endpoint`, `streaming`,
`concurrency`, and `long_context`. KV-cache observation, OOM probing, and local
quantization comparison are not yet implemented.

## Install/remove symmetry

No new managed runtime may be install-only. Installation and removal must cover the same
resource scope: containers, images, state files, and optional model volumes.
