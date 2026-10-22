# Roadmap

[🇩🇪 Deutsch](ROADMAP.md) | 🇬🇧 English

This document describes the planned development of `llmbench`: what already works, what is
in progress, and what is only an idea without commitment. It does not replace case-by-case
decisions; implementation details may still change.

## Vision

`llmbench` is called "LLM **Server** Benchmark". The project started with **llama.cpp**
and **NVIDIA/NVML**, but its goal is broader: multiple server backends through the shared
`BenchmarkBackend` abstraction and multiple GPU vendors through the
`TelemetryProvider` abstraction, while preserving the core strength of the project:
traceable benchmark results backed by evidence instead of isolated tokens/s numbers.

## Backend support matrix

| Backend | Status | Transport | Notes |
| --- | --- | --- | --- |
| llama.cpp | ✅ complete | local binary (`llama-bench`/`llama-server`) | Reference backend |
| vLLM | ✅ complete (1.6.0) | Docker container (`vllm/vllm-openai`) | Phase A |
| TGI | 🧪 Beta (since 1.6.5; stable planned for 1.7.0) | Docker container (`ghcr.io/huggingface/text-generation-inference`) | Phase 2, OpenAI-compatible `/v1/completions` backend |
| Ollama | ✅ complete (1.6.5) | Docker container (`ollama/ollama`) | Phase 3, native `/api/generate`; local GGUF import through blob/create APIs |

New server backends such as vLLM/Ollama/TGI are intentionally containerized instead of
using another native/bare-metal installation path like llama.cpp. Docker, including the
required GPU runtime, provides a more predictable installation and cleanup model and keeps
Windows (Docker Desktop/WSL2) and Linux behavior closer together.

See [CONTRIBUTING.en.md](CONTRIBUTING.en.md#installingremoving-backend-runtimes) for the
runtime install/uninstall expectations.

## GPU telemetry matrix

| Vendor | Status | Source | Notes |
| --- | --- | --- | --- |
| NVIDIA | ✅ complete | NVML (`nvidia-ml-py`) | Utilization, VRAM, temperature, power, compute PIDs |
| AMD | ✅ complete (1.6.0) | `rocm-smi --json` | Phase D, `compute_pids` currently limited |
| Intel | ✅ complete | `xpu-smi stats -d <id> -j` | Phase E, one subprocess call per GPU; `compute_pids` stays empty |

When multiple GPU vendors are present, `CompositeProvider` (since 1.6.0) can combine
available providers instead of selecting only the first source.

## Phase 0 — Architecture contracts ✅ *implemented/merged*

Before additional backends and later multimodal workloads enter the core, the layer
boundaries and compatibility rules are now documented explicitly. The contracts separate
**task**, **runtime/backend**, **workload**, **metric**, **telemetry**, and **result**, and
state that the working text path must not be replaced through a big-bang rewrite.

See [docs/architecture/](docs/architecture/README.en.md) for the core, runtimes,
tasks/workloads, telemetry, results, and compatibility contracts.

## Phase 1 — Backend capabilities and backend-independent stress tests ✅ *implemented/merged*

`BenchmarkBackend` now exposes explicit `BackendCapabilities`. TTFT, context/OOM,
quantization, and multi-tenant stress no longer instantiate the llama.cpp backend directly;
they use `get_backend()` and check the capabilities they require.

An unsupported workload is not a benchmark failure: it writes structured
`status: skipped` data with `reason: backend_capability_missing` and returns exit code 2.
llama.cpp supports the four existing stress paths. vLLM can run the generic
TTFT/concurrency stress workload; OOM probing, local quantization comparison, and
multi-model stress remain explicitly unsupported until their adapters can implement those
methods reliably.

The llama.cpp-specific HTTP operations required by the context/OOM probe now live inside
the llama.cpp backend instead of the generic stress runner.

## Next steps (after 1.6.0)

Everything below must continue to support **both German and English** and use the common
terminal UI.

1. **Language system + terminal UI** ✅ *implemented (unreleased)* — language selection at
   startup, translated installer scripts (PowerShell/Bash), common UI helpers, and
   translation-coverage tests.
2. **Finish setup/installer** ✅ *implemented (unreleased)* — NVIDIA driver checks on
   Windows, resume after reboot, backend selection during setup, and installer tests in CI.
3. **Stress tests through backend capabilities** ✅ *implemented/merged* — stress paths run through `get_backend()` and unsupported workloads are skipped with a structured reason.
4. **TGI backend** (Phase C) — beta; extensive real-world testing pending; `TgiBackend` is registered in the backend factory,
   config, setup, and runner alongside `VllmBackend` as a containerized, OpenAI-compatible HTTP
   backend. **Ollama backend** (Phase B, using existing GGUFs where applicable) is released as stable in 1.6.5 (CPU and GPU).

## Original phase plan

The detailed technical planning lives in the project planning material. The high-level
sequence is:

1. **Phase F, part 1 — Project infrastructure**  
   Low risk: roadmap, contribution guide, issue/PR templates, and project conventions.
2. **Phase A — vLLM backend** ✅ *released in 1.6.0*  
   Architectural proof that `BenchmarkBackend` can support HTTP/server backends through
   profile hooks, Docker lifecycle management, and calibrated HTTP measurements.
3. **Phase C — TGI backend**  
   Reuses the HTTP benchmarking infrastructure and validates the abstraction with another
   server.
4. **Phase B — Ollama backend**  
   Kept later because Ollama's native `/api/generate` API differs more strongly from the
   OpenAI-compatible path.
5. **Phase D — AMD GPU telemetry** ✅ *released in 1.6.0*  
   Adds `AmdProvider` using `rocm-smi` and fixes telemetry-source reporting for
   non-NVIDIA providers.
6. **Phase E — Intel GPU telemetry** ✅ *implemented (unreleased)*  
   Builds on the same `TelemetryProvider`/`CompositeProvider` infrastructure.
7. **Phase F, remainder — i18n sweep + templates**  
   Final language and contribution-flow audit after feature phases introduce additional
   user-visible strings.

The order after Phase A is a recommendation, not a hard commitment. It may change based on
resources, testing results, and contributor feedback.

## Ideas, not commitments

The following are **non-binding ideas** for a more distant future. They are not scheduled
phases and have no promised timeframe:

- Additional backends: SGLang, TensorRT-LLM
- Additional GPU vendors/telemetry sources beyond NVIDIA/AMD/Intel
- Cloud or remote inference targets in addition to local servers

If you are interested in one of these areas, open an issue using the
`backend_request` template under [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/).

## Related documents

- [`CONTRIBUTING.en.md`](CONTRIBUTING.en.md) — how to contribute to these areas
- [`CHANGELOG.en.md`](CHANGELOG.en.md) — released changes
- [`docs/DOCKER.en.md`](docs/DOCKER.en.md) — running llmbench with Docker
- [`docs/architecture/README.en.md`](docs/architecture/README.en.md) — architecture contracts for v1.7+
