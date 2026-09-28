[Deutsch](DE-Home) | [English](EN-Home)

---

# LLM Server Benchmark Wiki

Welcome to the user guide for **LLM Server Benchmark (llmbench)**.

llmbench records more than tokens per second. It stores the surrounding test conditions as well: hardware, drivers, backend, model hash, quantization, configuration, and telemetry. This makes local LLM system comparisons reproducible and auditable.

## Quick links

- [Installation](EN-Installation)
- [Quick Start](EN-Quick-Start)
- [Model Suite](EN-Model-Suite)
- [Benchmark Methodology](EN-Benchmark-Methodology)
- [Hardware Telemetry](EN-Hardware-Telemetry)
- [Benchmark Profiles](EN-Benchmark-Profiles)
- [Backends](EN-Backends)
- [Understanding Results](EN-Understanding-Results)
- [Reports and Export](EN-Reports-and-Export)
- [Comparing Systems](EN-Comparing-Systems)
- [Troubleshooting](EN-Troubleshooting)
- [FAQ](EN-FAQ)
- [Development](EN-Development)
- [Roadmap](EN-Roadmap)

## What llmbench measures

- Prompt processing and text generation
- Long-context performance
- CPU, GPU, and hybrid profiles
- TTFT, concurrency, and system throughput
- Soak, OOM, multi-tenant, and quantization tests
- CPU, RAM, GPU, VRAM, temperature, and power telemetry

## Supported backends

| Backend | Status | Execution |
| --- | --- | --- |
| llama.cpp | supported | native |
| vLLM | supported | Docker |
| TGI | planned | Docker |
| Ollama | planned | Docker |

## Core principle

A single value such as **84 tok/s** has limited meaning without its test conditions. A defensible comparison needs at least the same model, quantization, preferably the same backend build, and the same benchmark configuration.

```bash
llmbench compare results/run-a results/run-b --strict
```
