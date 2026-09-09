# LLM Server Benchmark

**Reproducible benchmarking for local LLM inference on NVIDIA CUDA systems and other llama.cpp-capable hardware.**

[![Tests](https://github.com/Lautloserspieler/llm-server-benchmark/actions/workflows/tests.yml/badge.svg)](https://github.com/Lautloserspieler/llm-server-benchmark/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

LLM benchmark numbers are often hard to reproduce because the GPU, driver, backend, llama.cpp build, model files, quantization, benchmark settings and power state differ between machines. **LLM Server Benchmark** records those conditions together with the performance result so that two systems can be compared under verifiable conditions.

See the [release and demo checklist](docs/RELEASE_CHECKLIST.md) for final validation and presentation guidance.

## Why this project

A result should be more than `84 tok/s`.

A useful result should answer:

- Which exact GPU and driver produced it?
- Was the NVIDIA CUDA backend actually used?
- Which llama.cpp build was tested?
- Which exact GGUF files and quantization were used?
- Were the benchmark settings identical?
- How much VRAM, power and temperature did the run reach?
- Was another process using the GPU during the measurement?
- How does throughput change with context length or concurrent users?

`llmbench` captures that information and keeps the raw evidence next to the final HTML/PDF/CSV/JSON reports.

## NVIDIA / CUDA integration

On NVIDIA systems the project uses NVIDIA tooling directly instead of treating the GPU as an anonymous accelerator.

- GPU discovery through `nvidia-smi`
- GPU name, driver version, VRAM, compute capability, VBIOS and power limit
- NVML telemetry through `nvidia-ml-py`
- GPU utilization and VRAM usage over time
- temperature and power draw
- compute-process detection to flag foreign GPU load
- tokens/s and power-efficiency reporting
- Windows: NVIDIA systems use the matching CUDA-enabled llama.cpp path
- Linux: when an NVIDIA GPU and `nvcc` are available, `llmbench` automatically builds llama.cpp with `GGML_CUDA=ON` before considering Vulkan/CPU fallbacks

The Linux backend can be controlled explicitly:

```bash
export LLMBENCH_LLAMACPP_BUILD_BACKEND=auto    # default: prefer CUDA on NVIDIA
export LLMBENCH_LLAMACPP_BUILD_BACKEND=cuda    # require CUDA
export LLMBENCH_LLAMACPP_BUILD_BACKEND=vulkan
export LLMBENCH_LLAMACPP_BUILD_BACKEND=cpu
```

Set `LLMBENCH_LLAMACPP_SOURCE_BUILD=0` only if automatic source builds should be disabled.

## What it measures

### Core inference

- Prompt processing / input tokens per second
- Text generation / output tokens per second
- Long-context performance with a genuinely populated KV cache
- CPU-only, full-GPU and hybrid profiles

### Interactive serving

- System TPS
- Tokens/s per request
- TTFT P50 / P95
- Success rate
- multiple concurrency levels

### Stress and capacity

- short and long soak tests
- throttling indicators
- TTFT stress
- multi-tenant / two-model load
- KV-cache and context-limit tests
- quantization comparison for multiple quants of the same base model

### Hardware telemetry

- CPU and RAM utilization
- GPU utilization
- VRAM usage
- NVIDIA power draw
- GPU temperature
- background/foreign GPU-process warnings
- Linux CPU governor / power-profile capture

## Reproducibility

Every run records provenance that can be checked before two servers are compared.

| Evidence | Purpose |
| --- | --- |
| `config_fingerprint` | Hash of result-relevant benchmark settings |
| `config` | Full configuration used for the run |
| `tools.llama_bench.binary.sha256` | Exact llama-bench binary |
| `tools.llama_cpp_build_ids` | llama.cpp build identity |
| `llmbench_version` | Benchmark framework version |
| `models[].model.sha256` | Exact model or combined hash of all GGUF shards |
| hardware metadata | CPU, RAM, GPU, driver and execution environment |

`llmbench compare --strict` returns exit code `1` when runs were produced under incompatible conditions.

## Quick start

### Windows

```text
1. Clone or download the repository
2. Run START_BENCHMARK.bat
3. Let setup verify/install dependencies and models
4. Select benchmark duration and hardware mode
```

If Python 3.10+ is already installed, `setup.bat` can also be used directly.

### Linux

```bash
git clone https://github.com/Lautloserspieler/llm-server-benchmark.git
cd llm-server-benchmark
chmod +x setup.sh START_BENCHMARK.sh
./setup.sh
./START_BENCHMARK.sh
```

On an NVIDIA Linux workstation, install a working NVIDIA driver and CUDA Toolkit (`nvcc`) to get the automatic native CUDA source-build path.

You can also install/verify llama.cpp directly:

```bash
llmbench install-llama-cpp --root .
```

### macOS

```bash
./setup.sh
./START_BENCHMARK.sh
```

The normal macOS llama.cpp package is used; Apple Silicon acceleration is provided by the platform build.

## Standard model suite

The default V2 suite manages Q4_K_M variants of:

- Qwen3-8B
- DeepSeek-R1-Distill-Qwen-7B
- Qwen3.8-27B
- Qwen2.5-72B-Instruct
- Mixtral-8x22B-Instruct

The complete suite is large. Free disk space is checked before downloads and the tool warns when capacity is likely insufficient.

```bash
llmbench download --suite small
llmbench download --suite mid
llmbench download --suite heavy
llmbench download --suite all
llmbench download --suite all --verify-only
```

Large split GGUF sets are treated as one logical model. A partial shard set is not accepted as a complete benchmark model, and the model fingerprint covers every shard.

## Pinning llama.cpp

For fair machine-to-machine comparisons, do not silently benchmark different llama.cpp revisions.

Put a release/build identifier into `llama-cpp-version.txt`, for example:

```text
b10456
```

Windows:

```powershell
.\START_BENCHMARK.bat -LlamaCppTag b10456
```

Linux/macOS:

```bash
llmbench install-llama-cpp --root . --tag b10456
```

`LLMBENCH_LLAMACPP_TAG` can also be used. The build actually used is recorded in the result data and checked by `llmbench compare`.

## Running benchmarks

```bash
# Validate tools, models, hardware and configuration
llmbench doctor --config benchmark.yaml

# Refresh detected tools/models
llmbench bootstrap --config benchmark.yaml --root . --llama-dir tools/llama.cpp --models-dir models

# Hardware modes
llmbench run --hardware cpu
llmbench run --hardware gpu
llmbench run --hardware both

# Duration presets
llmbench run --config benchmark.yaml --duration short
llmbench run --config benchmark.yaml --duration medium
llmbench run --config benchmark.yaml --duration long

# One model
llmbench run --config benchmark.yaml --model "Qwen3-8B"

# Normal run plus stress suite
llmbench run --config benchmark.yaml --stress

# Plain output for logs/automation
llmbench run --config benchmark.yaml --plain
```

## Stress commands

```bash
llmbench stress-ttft --config benchmark.yaml
llmbench stress-multitenant --config benchmark.yaml
llmbench stress-oom --config benchmark.yaml
llmbench stress-quant --config benchmark.yaml
```

`stress-quant` intentionally compares only different quantizations of the **same base model**.

## Result structure

A normal run produces a self-contained result directory similar to:

```text
results/
  SERVERNAME_YYYYMMDD-HHMMSSZ/
    hardware.json
    summary.json
    summary.partial.json
    benchmarks.csv
    report.pdf
    report.html
    MODEL/
      PROFILE/
        raw_prompt.json
        raw_generation.json
        raw_long_context.json
      endpoint/
        endpoint_load.json
        llama-server.log
    stress/
      index.json
      ttft/
      multitenant/
      oom/
      quant/
```

Raw files keep exact commands, stdout/stderr and telemetry samples. `summary.json` stays focused on aggregate values for tooling and comparisons.

## Compare machines

```bash
llmbench compare "results/ServerA_..." "results/ServerB_..." --out comparison
llmbench compare "results/ServerA_..." "results/ServerB_..." --strict
```

Use the same llama.cpp build, exact model files, quantization, benchmark configuration and comparable power settings on every machine.

## Linux performance-state warning

`llmbench` records the CPU governor and, where available, the active `power-profiles-daemon` profile. `llmbench doctor` warns when the machine is not in a performance-oriented state.

Typical commands:

```bash
sudo powerprofilesctl set performance
sudo cpupower frequency-set -g performance
```

Use the command appropriate for the system; not every distribution uses both mechanisms.

## Tests and CI

```bash
pip install -e ".[dev]"
pytest -q
ruff check .
```

GitHub Actions runs the test suite on Ubuntu and Windows with Python 3.10 and 3.12. Linux shell/Docker launchers and Windows PowerShell launchers are also syntax-checked.

## Project scope

This project is **not an official MLPerf submission runner**. It is an independent open-source benchmarking framework for reproducible local LLM/server comparisons built around llama.cpp.

## License

MIT - see [LICENSE](LICENSE).