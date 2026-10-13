# Core architecture

[🇩🇪 Deutsch](core.md) | [Overview](README.en.md)

## Core responsibility

The core orchestrates a benchmark run without owning task-specific methodology or the
implementation details of a concrete runtime/backend.

Long-term layer boundary:

```text
CLI / Terminal UI
       |
       v
Benchmark Engine
       |
       +---- Task / Workload
       |
       +---- Runtime / Backend
       |
       +---- Dataset
       |
       +---- Telemetry
       |
       v
Normalized Result
       |
       v
Reports / Compare / Export
```

Today `llmbench/runner.py` performs much of this orchestration for text generation. That
remains valid until a deliberate migration replaces parts of it.

## The core may

- load and validate configuration,
- select models and profiles,
- coordinate lifecycle boundaries,
- schedule workloads,
- start and stop telemetry,
- merge results and warnings,
- coordinate failure, cancellation, and cleanup,
- invoke reports/exports using normalized results.

## The core must not

- know runtime-specific HTTP paths,
- spread TGI/Ollama/llama.cpp name checks throughout orchestration,
- calculate WER, RTF, mAP, or other task-specific quality metrics itself,
- create a universal score from unrelated tasks,
- invent missing measurements or silently treat them as zero.

## Current reference

For text generation, the current reference points are:

- `BenchmarkBackend` in `llmbench/backends/base.py`
- `get_backend()` in `llmbench/backends/`
- `run_suite()` in `llmbench/runner.py`
- `TelemetryProvider` in `llmbench/telemetry.py`

These APIs are the starting point, not necessarily the final multimodal API.

## Future extension

When Phase 4 (Multimodal Core) starts, task and runtime responsibilities should become
explicitly separate. The intended terms are `TaskAdapter` and `RuntimeAdapter`; Phase 0
defines their responsibility boundary only and does not implement them.
