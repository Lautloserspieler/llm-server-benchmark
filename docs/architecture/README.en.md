# Architecture contracts

[🇩🇪 Deutsch](README.md)

This directory defines the stable architecture terminology and compatibility rules used for
future `llmbench` development. These documents are intentionally separate from release
schedules: they define **which responsibility belongs to which layer** before new backends
and later multimodal workloads are implemented.

## Phase 0 purpose

Phase 0 does not change benchmark methodology. It freezes the concepts and boundaries used
by v1.7+:

- [Core](core.en.md) — orchestration and layer boundaries
- [Backends and runtimes](backends.en.md) — how software executes a model
- [Tasks and workloads](workloads.en.md) — what a model does and how it is tested
- [Telemetry](telemetry.en.md) — shared hardware/resource observation
- [Results](results.en.md) — result model, provenance, and metric rules
- [Compatibility](compatibility.en.md) — rules for existing configurations and results

## Core terminology

| Term | Meaning | Examples |
| --- | --- | --- |
| **Task** | What a model does | text generation, STT, TTS, OCR |
| **Runtime/backend** | Software executing the model | llama.cpp, vLLM, TGI, Ollama |
| **Workload** | Reproducible way to exercise a task | long context, concurrency, 10 h STT |
| **Metric** | Measurement produced by a workload | tokens/s, TTFT, WER, RTF |
| **Telemetry** | Hardware/system state sampled during execution | VRAM, power, temperature |
| **Result** | Normalized output including provenance | metrics + config + hardware |

## Phase 0 non-goals

Phase 0 does **not** introduce multimodal runtimes, replace the existing
`BenchmarkBackend`, or rewrite the runner. Existing text benchmarks remain the reference
path. New abstractions are implemented only when a later phase actually needs them.
