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

Starting in Phase 1, optional behavior should be represented explicitly, for example:

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

Code should check a capability instead of branching on `backend == "..."` when the
decision is really capability-based.

## Install/remove symmetry

No new managed runtime may be install-only. Installation and removal must cover the same
resource scope: containers, images, state files, and optional model volumes.
