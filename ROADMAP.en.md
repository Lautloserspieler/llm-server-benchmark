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
| TGI | 📋 planned | Docker container (`ghcr.io/huggingface/text-generation-inference`) | Phase C, builds on Phase A |
| Ollama | 📋 planned | Docker container (`ollama/ollama`) | Phase B, native API instead of OpenAI-compatible |

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
| Intel | 📋 planned | `xpu-smi stats -d <id> -j` | Phase E, one subprocess call per GPU |

When multiple GPU vendors are present, `CompositeProvider` (since 1.6.0) can combine
available providers instead of selecting only the first source.

## Next steps (after 1.6.0)

Everything below must continue to support **both German and English** and use the common
terminal UI.

1. **Language system + terminal UI** ✅ *implemented (unreleased)* — language selection at
   startup, translated installer scripts (PowerShell/Bash), common UI helpers, and
   translation-coverage tests.
2. **Finish setup/installer** ✅ *implemented (unreleased)* — NVIDIA driver checks on
   Windows, resume after reboot, backend selection during setup, and installer tests in CI.
3. **Stress tests for all backends** — TTFT/multi-tenant/OOM/quant are still tied too
   closely to llama.cpp; they should run through `get_backend()`, with unsupported tests
   skipped with an explicit reason.
4. **TGI backend** (Phase C), followed by **Ollama backend** (Phase B, using existing GGUFs
   where applicable).

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
6. **Phase E — Intel GPU telemetry**  
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
