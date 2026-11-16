# Release & Demo Checklist

[🇩🇪 Deutsch](RELEASE_CHECKLIST.de.md) | 🇬🇧 English

This document collects the public-release and demo-readiness steps for **LLM Server Benchmark**.

## One-sentence pitch

**LLM Server Benchmark is an open-source framework that makes local LLM performance results reproducible by recording the exact NVIDIA GPU/CUDA environment, model/build fingerprints and live NVML telemetry together with throughput, latency, context and power-efficiency measurements.**

## Problem

Local LLM benchmark screenshots often show only a model name and tokens/s. That makes results difficult to reproduce or compare because important variables are missing:

- exact GPU and driver
- CUDA/backend selection
- llama.cpp build
- model file / quantization
- context and benchmark configuration
- VRAM pressure
- background GPU load
- temperature and power state

The project keeps those variables next to the measurement and can reject incompatible comparisons in strict mode.

## NVIDIA technology used

- `nvidia-smi` for NVIDIA GPU discovery and hardware metadata
- NVML via `nvidia-ml-py` for live utilization, VRAM, temperature, power and compute-process telemetry
- native llama.cpp CUDA backend on NVIDIA systems
- automatic Linux CUDA source build with `GGML_CUDA=ON` when an NVIDIA GPU and CUDA Toolkit (`nvcc`) are detected
- CUDA-enabled Windows path for NVIDIA systems

## Recommended demo sequence

A short demo should make the value obvious without requiring viewers to understand the codebase.

### 45–60 second sequence

1. **0–5 s – Problem**  
   Show two arbitrary-looking LLM performance numbers and the question: *Can these results actually be compared?*

2. **5–12 s – Start**  
   Run `START_BENCHMARK.bat` or `./START_BENCHMARK.sh`.

3. **12–20 s – NVIDIA detection**  
   Show the detected NVIDIA GPU, driver, VRAM and CUDA/backend path.

4. **20–35 s – Live benchmark**  
   Show generation throughput together with GPU utilization, VRAM, temperature and power telemetry.

5. **35–47 s – Reproducibility evidence**  
   Show the report fields for llama.cpp build, model SHA256 and configuration fingerprint.

6. **47–55 s – Compare**  
   Show `llmbench compare` between two machines/runs and highlight that incompatible conditions are detected.

7. **55–60 s – Close**  
   Show the public GitHub repository and the message: *Open source. Reproducible. Built for real local LLM hardware comparisons.*

## Recommended screenshots

Use a small set of clear visuals rather than a wall of terminal text:

1. Hardware detection with the NVIDIA GPU visible
2. Benchmark result with tokens/s and TTFT
3. NVML telemetry: VRAM, utilization, temperature and power
4. Provenance block with model/build/config fingerprints
5. Optional machine-to-machine comparison

## Release checklist

Before publishing a release or public demo:

- [ ] `main` contains the current README and documentation
- [ ] GitHub Actions are green
- [ ] Repository is public
- [ ] MIT license is present
- [ ] Final NVIDIA Windows test completed
- [ ] Final NVIDIA Linux/CUDA test completed
- [ ] `llmbench doctor` shows the intended GPU/backend
- [ ] A clean benchmark result was generated with no foreign-GPU-load warning
- [ ] HTML/PDF report opens correctly
- [ ] Demo video is short and readable on mobile
- [ ] Public project links point to the current repository
- [ ] Contributor attribution checked: external changes in `CHANGELOG.md` name the contributor with `@username`
- [ ] Release notes credit external contributors for their changes and do not reassign authorship to the maintainer
- [ ] Where multiple people substantially co-authored work, all contributors are credited
- [ ] German and English Markdown documentation is synchronized
- [ ] v1.7.0 only: the evidence list in [`docs/validation/v1.7.0-qualification.md`](validation/v1.7.0-qualification.md) is filled in with real measurement records (no ticks without hardware evidence)
- [ ] v1.7.0 scope is llama.cpp, vLLM and Ollama; obsolete TGI validation/dependency entries in #116/#120/#124 are reconciled with #167
- [ ] Required Ollama version/context/CPU/GPU combinations and five independent reference repeats have inspectable results
- [ ] The 8-hour soak has attached result/telemetry/cleanup artifacts; a maintainer statement alone is distinguished from an inspectable record
- [ ] Unavailable AMD/Intel hardware is explicitly marked untested; implemented providers and green CI are not advertised as hardware qualification

TGI removal and SGLang beta are planned for 1.8.0, with full SGLang integration
and stability validation planned for 1.9.0. SGLang is not selectable yet and is not
part of the 1.7.0 acceptance matrix. The current smoke default still includes TGI;
select the active backends explicitly:

```bash
python scripts/smoke_all_backends.py --backends llama_cpp ollama vllm --cycles 10 --device gpu --output results/qualification/cycles
```

## Suggested project announcement copy

> I built **LLM Server Benchmark**, an open-source framework for reproducible local LLM performance testing.
>
> Instead of publishing only a tokens/s number, each run records the exact GPU/driver, CUDA/backend, llama.cpp build, model fingerprints and benchmark configuration while collecting live NVIDIA NVML telemetry for utilization, VRAM, temperature and power.
>
> It measures throughput, TTFT, long-context behavior, concurrent serving, stress limits and power efficiency, and can detect when two benchmark runs were produced under incompatible conditions.
>
> Source: https://github.com/Lautloserspieler/llm-server-benchmark

## Final validation commands

Start with the [read-only qualification preflight](validation/v1.7.0-qualification.md).
It records missing prerequisites without installing or starting backends. A
successful preflight is not hardware acceptance:

```bash
python scripts/qualification_preflight.py --device cuda --gguf models/reference.gguf --hash-model
```

```bash
llmbench doctor --config benchmark.yaml
llmbench run --config benchmark.yaml --hardware gpu --duration short
pytest -q
ruff check .
mypy llmbench
python -m pip check
```

For an NVIDIA Linux machine, confirm the installed llama.cpp backend:

```bash
cat tools/llama.cpp/.llama-build.json
```

Example for a source-built CUDA installation (downloaded CUDA builds may record
`source_build: false`):

```json
{
  "backend": "cuda",
  "source_build": true
}
```

The exact file contains additional fields such as the pinned llama.cpp tag and build paths.
Also retain the actual GPU API reported by llama.cpp and the benchmark result.
A GPU/Vulkan run is not CUDA evidence, and installation metadata alone does not
establish which runtime executed the workload.
