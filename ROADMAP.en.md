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
| TGI | ⛔ being discontinued (decision in #167; replacement SGLang, planned for 1.8.0) — beta without validation until it is removed | Docker container (`ghcr.io/huggingface/text-generation-inference`) | Phase 2, OpenAI-compatible `/v1/completions` backend |
| Ollama | ✅ complete (1.6.5) | Docker container (`ollama/ollama`) | Phase 3, native `/api/generate`; local GGUF import through blob/create APIs |
| SGLang | 📋 planned (#167) | Docker container (planned) | Beta planned for 1.8.0; full integration and stability validation planned for 1.9.0; no adapter yet |

“Complete” describes implementation, not unrestricted hardware qualification.
The [v1.7.0 qualification record](docs/validation/v1.7.0-qualification.md)
lists the available measurements and remaining untested combinations.

The existing server adapters (vLLM/Ollama and the retained TGI adapter) are intentionally containerized instead of
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

NVIDIA measurements are documented in the qualification record; real AMD and
Intel traces are still missing there. Implemented providers are not thereby
validated on every hardware configuration.

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
llama.cpp supports the four existing stress paths. vLLM, TGI, and Ollama run the generic
TTFT/concurrency stress workload and the HTTP context/OOM probe
(`llmbench/backends/http_probe.py`, including failure classification `out_of_memory`,
`context_exceeded`, `context_truncated`, `timeout`, `connection_error`; tested against a
fake HTTP server; existing Ollama GPU context evidence and its limits are recorded
in the [qualification protocol](docs/validation/v1.7.0-qualification.md)). Local quantization
comparison and multi-model stress remain explicitly unsupported there because no
reproducible adapter contract exists (see docs/architecture/backends.md).

The llama.cpp-specific HTTP operations required by the context/OOM probe now live inside
the llama.cpp backend instead of the generic stress runner.

## Multimodal Groundwork 🚧 *in progress (unreleased)*

Additive groundwork for future multimodal tasks that leaves the text path untouched:
package `llmbench/tasks/` with `TaskAdapter`/`RuntimeAdapter`, a task ID enum, a workload
registry, and `TextGenerationTask`; a validated dataset manifest (source, version, license,
SHA-256, sample selection); optional `task`/`workload`/`dataset` fields in schema v3
(deliberately no v4, old results stay readable unchanged). There is no universal score, and
missing values are never stored as 0. **Not** included yet: multimodal backends, workloads,
or runner integration. See [docs/architecture/](docs/architecture/README.en.md).

## Current development path: 1.7.0 to 2.0.0

The project version is still **1.6.5**. Work for 1.7.0 is integrated on `main`,
but release acceptance remains open. Release numbers describe planned scope,
not promised delivery dates.

| Release | Focus | Tracking |
| --- | --- | --- |
| 1.7.0 | Stabilize llama.cpp, vLLM and Ollama; HTTP probes, telemetry, platforms and hardware qualification | [#116](https://github.com/Lautloserspieler/llm-server-benchmark/issues/116), #121–#124; TGI validation #120 dropped by #167 |
| 1.8.0 | Token calibration, traffic profiles, SLO/Goodput and reports; remove TGI and introduce SGLang beta | [#117](https://github.com/Lautloserspieler/llm-server-benchmark/issues/117), #125–#128, [#167](https://github.com/Lautloserspieler/llm-server-benchmark/issues/167) |
| 1.9.0 | Adaptive capacity, engine comparisons, multi-turn and statistics; complete SGLang integration and stability validation | [#118](https://github.com/Lautloserspieler/llm-server-benchmark/issues/118), #129–#132, #167 |
| 2.0.0 | Multimodal orchestration, STT, TTS, images, OCR, embeddings and qualification | [#119](https://github.com/Lautloserspieler/llm-server-benchmark/issues/119), #133–#139 |

The remaining 1.7.0 work includes real CUDA and Windows hardware runs, a second
Ollama version, required context sizes, repeated reference measurements, and
inspectable long-soak artifacts. AMD/Intel are tested where hardware is available
and otherwise explicitly marked untested. Details and reconciliation of the
still-open issues are in the
[qualification protocol](docs/validation/v1.7.0-qualification.md).

## Foundations already integrated

Everything below must continue to support **both German and English** and use the common
terminal UI.

1. **Language system + terminal UI** ✅ *implemented (unreleased)* — language selection at
   startup, translated installer scripts (PowerShell/Bash), common UI helpers, and
   translation-coverage tests.
2. **Finish setup/installer** ✅ *implemented (unreleased)* — NVIDIA driver checks on
   Windows, resume after reboot, backend selection during setup, and installer tests in CI.
3. **Stress tests through backend capabilities** ✅ *implemented/merged* — stress paths run through `get_backend()` and unsupported workloads are skipped with a structured reason.
4. **TGI backend** (Phase C) — being discontinued (#167), no further validation for 1.7.0; it stays beta until it is removed; `TgiBackend` is registered in the backend factory,
   config, setup, and runner alongside `VllmBackend` as a containerized, OpenAI-compatible HTTP
   backend. **Ollama backend** (Phase B, using existing GGUFs where applicable) is released as stable in 1.6.5 (CPU and GPU).

## Original phase plan

The original phase plan below records how the adapters were introduced.
New work follows the development path above and decision #167.

1. **Phase F, part 1 — Project infrastructure**  
   Low risk: roadmap, contribution guide, issue/PR templates, and project conventions.
2. **Phase A — vLLM backend** ✅ *released in 1.6.0*  
   Architectural proof that `BenchmarkBackend` can support HTTP/server backends through
   profile hooks, Docker lifecycle management, and calibrated HTTP measurements.
3. **Phase C — TGI backend** ⛔ *superseded by #167*
   The adapter was implemented but will not receive further qualification or
   legacy maintenance. Removal and replacement with SGLang are planned.
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

The historical sequence is not the current task list.

## Ideas, not commitments

The following are **non-binding ideas** for a more distant future. They are not scheduled
phases and have no promised timeframe:

- Additional backends beyond the already planned SGLang: TensorRT-LLM
- Additional GPU vendors/telemetry sources beyond NVIDIA/AMD/Intel
- Cloud or remote inference targets in addition to local servers

If you are interested in one of these areas, open an issue using the
`backend_request` template under [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/).

## Related documents

- [`CONTRIBUTING.en.md`](CONTRIBUTING.en.md) — how to contribute to these areas
- [`CHANGELOG.en.md`](CHANGELOG.en.md) — released changes
- [`docs/DOCKER.en.md`](docs/DOCKER.en.md) — running llmbench with Docker
- [`docs/architecture/README.en.md`](docs/architecture/README.en.md) — architecture contracts for v1.7+
