# LLM Server Benchmark

**Reproducible benchmarking for local LLM inference across llama.cpp and containerized server backends.**

[![Tests](https://github.com/Lautloserspieler/llm-server-benchmark/actions/workflows/tests.yml/badge.svg)](https://github.com/Lautloserspieler/llm-server-benchmark/actions/workflows/tests.yml)
[![Security](https://github.com/Lautloserspieler/llm-server-benchmark/actions/workflows/security.yml/badge.svg)](https://github.com/Lautloserspieler/llm-server-benchmark/actions/workflows/security.yml)
[![Docker](https://github.com/Lautloserspieler/llm-server-benchmark/actions/workflows/docker-image.yml/badge.svg)](https://github.com/Lautloserspieler/llm-server-benchmark/actions/workflows/docker-image.yml)
[![OpenSSF Scorecard](https://github.com/Lautloserspieler/llm-server-benchmark/actions/workflows/scorecard.yml/badge.svg)](https://github.com/Lautloserspieler/llm-server-benchmark/actions/workflows/scorecard.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

LLM benchmark results are often reduced to a single number such as **84 tok/s**. That number is useful only when the surrounding conditions are known.

**LLM Server Benchmark** records the hardware, driver, backend, model files, quantization, benchmark settings, execution environment and telemetry together with the performance result. The goal is to make local LLM server comparisons **repeatable, inspectable and defensible**.

---

## Highlights

- Reproducible local LLM benchmarks instead of isolated tokens/s numbers
- Native **llama.cpp** benchmarking
- Containerized **vLLM** backend support
- NVIDIA GPU telemetry through NVML
- AMD GPU telemetry through `rocm-smi`
- CPU-only, GPU and hybrid benchmark profiles
- Prompt-processing and text-generation throughput
- Long-context benchmarks with populated KV cache
- Endpoint/load testing with TTFT and concurrency measurements
- Stress, soak, OOM, multi-tenant and quantization tests
- HTML, PDF, CSV and JSON reports
- Model, binary and configuration fingerprints
- Cross-machine comparison with strict reproducibility validation
- Windows, Linux and macOS launchers
- Docker image with SBOM, provenance and vulnerability scanning
- CI across Python 3.10–3.14 on Windows and Linux

---

## Why this project exists

A useful benchmark result should answer more than:

> How many tokens per second did the model generate?

It should also answer:

- Which exact CPU and GPU produced the result?
- Which driver and GPU runtime were active?
- Was CUDA, ROCm, Vulkan, Metal or CPU execution actually used?
- Which backend and backend build were tested?
- Which exact model files and quantization were used?
- Were both machines using identical benchmark settings?
- How much VRAM, power and temperature did the run reach?
- Was another process consuming GPU resources?
- How did performance change under long context or concurrent requests?
- Can somebody else reproduce the same measurement?

`llmbench` stores that evidence next to the benchmark output.

---

## Support matrix

### Inference backends

| Backend | Status | Execution | Notes |
| --- | --- | --- | --- |
| **llama.cpp** | ✅ Supported | Native | Reference backend using `llama-bench` and `llama-server` |
| **vLLM** | ✅ Supported | Docker | OpenAI-compatible serving backend |
| **TGI** | 📋 Planned | Docker | Planned container backend |
| **Ollama** | 📋 Planned | Docker | Planned native-API backend |

### GPU telemetry

| Platform | Status | Telemetry source |
| --- | --- | --- |
| **NVIDIA** | ✅ Supported | NVML / `nvidia-ml-py`, `nvidia-smi` |
| **AMD** | ✅ Supported | `rocm-smi --json` |
| **Intel GPU** | 📋 Planned | `xpu-smi` |
| **Apple Silicon** | ✅ Benchmark execution | Platform llama.cpp build; telemetry is more limited |

See [ROADMAP.md](ROADMAP.md) for the current development plan.

---

## What llmbench measures

### Core inference

- prompt processing / input tokens per second
- text generation / output tokens per second
- long-context performance
- CPU-only, GPU and hybrid execution profiles
- repeated runs for variance measurement

### Interactive serving

- system throughput
- tokens/s per request
- TTFT P50 / P95
- request success rate
- configurable concurrency levels
- endpoint/server behavior under load

### Stress and capacity

- short and long soak tests
- thermal throttling indicators
- TTFT stress
- multi-tenant / two-model load
- KV-cache and context-limit/OOM testing
- quantization comparisons for the same base model

### Hardware telemetry

- CPU utilization
- RAM utilization
- GPU utilization
- VRAM usage
- GPU temperature
- NVIDIA power draw
- background/foreign GPU-process detection
- Linux CPU governor and power-profile capture

---

## Quick start

### Windows

Open **PowerShell** and clone the repository:

```powershell
git clone https://github.com/Lautloserspieler/llm-server-benchmark.git
cd llm-server-benchmark
```

Run the setup:

```powershell
.\setup.bat
```

The setup checks the required components and guides you through missing dependencies such as Python 3.10+, WSL2, Docker Desktop and GPU prerequisites. System-changing installations require confirmation unless automatic installation was explicitly enabled.

After setup, start the benchmark launcher:

```powershell
.\START_BENCHMARK.bat
```

The launcher then lets you choose the benchmark duration, hardware mode and other available options.

If script execution is restricted in your PowerShell environment, the `.bat` launchers can also be started from Command Prompt:

```cmd
setup.bat
START_BENCHMARK.bat
```

Language can be selected during setup or forced before starting:

```powershell
$env:LLMBENCH_LANG = "de"
# or
$env:LLMBENCH_LANG = "en"

.\setup.bat
```

### Linux

```bash
git clone https://github.com/Lautloserspieler/llm-server-benchmark.git
cd llm-server-benchmark

chmod +x setup.sh START_BENCHMARK.sh
./setup.sh
./START_BENCHMARK.sh
```

For native NVIDIA CUDA builds, install a working NVIDIA driver and CUDA Toolkit so that `nvcc` is available.

### macOS

```bash
git clone https://github.com/Lautloserspieler/llm-server-benchmark.git
cd llm-server-benchmark

chmod +x setup.sh START_BENCHMARK.sh
./setup.sh
./START_BENCHMARK.sh
```

Apple Silicon acceleration is provided by the platform llama.cpp build.

---

## Manual Python installation

For development or manual CLI usage:

```bash
git clone https://github.com/Lautloserspieler/llm-server-benchmark.git
cd llm-server-benchmark

python -m venv .venv
```

Activate the environment:

**Windows**

```powershell
.\.venv\Scripts\Activate.ps1
```

**Linux/macOS**

```bash
source .venv/bin/activate
```

Install the project:

```bash
python -m pip install --upgrade pip
pip install -e .
```

Verify the installation:

```bash
llmbench --version
llmbench --help
```

---

## Typical workflow

A normal benchmark workflow looks like this:

```bash
# 1. Check configuration, tools, hardware and model paths
llmbench doctor --config benchmark.yaml

# 2. Detect local tools and models
llmbench bootstrap \
  --config benchmark.yaml \
  --root . \
  --llama-dir tools/llama.cpp \
  --models-dir models

# 3. Run a benchmark
llmbench run --config benchmark.yaml --hardware gpu --duration medium

# 4. Optionally include the stress suite
llmbench run --config benchmark.yaml --hardware gpu --duration medium --stress

# 5. Compare two systems
llmbench compare \
  "results/ServerA_..." \
  "results/ServerB_..." \
  --out comparison

# 6. Reject comparisons with incompatible benchmark conditions
llmbench compare \
  "results/ServerA_..." \
  "results/ServerB_..." \
  --strict
```

---

## Benchmark configuration

Start from the supplied example:

```bash
cp benchmark.example.yaml benchmark.yaml
```

Important sections include:

```yaml
project:
  name: "LLM Server Benchmark"
  output_dir: "results"

tools:
  backend: "llama_cpp"

benchmark:
  repetitions: 5
  batch_size: 2048
  ubatch_size: 512
  flash_attention: auto
  prompt_tokens: [512, 4096, 8192]
  generation_tokens: [128, 512]
  context_depths: [0, 8192, 32768, 65536, 130000]

endpoint:
  enabled: false
  concurrency: [1, 2, 4, 8]

models:
  - name: "Example-Model"
    path: "models/example.gguf"
    profiles:
      - name: "Full-GPU"
        gpu_layers: -1
      - name: "CPU-Only"
        gpu_layers: 0
```

See [benchmark.example.yaml](benchmark.example.yaml) for the full configuration.

---

## Hardware modes

```bash
llmbench run --hardware cpu
llmbench run --hardware gpu
llmbench run --hardware both
```

You can also select a single model:

```bash
llmbench run --config benchmark.yaml --model "Qwen3-8B"
```

And choose a duration preset:

```bash
llmbench run --duration short
llmbench run --duration medium
llmbench run --duration long
```

---

## Full performance mode

Every `llmbench run` and `llmbench stress-*` switches the machine to full performance first, so results reflect the hardware and not a power-saving profile. This is on by default and **stays active after the run**.

| Platform | What is changed |
| --- | --- |
| **Linux** | power-profiles-daemon / tuned → `performance`, ACPI platform profile → `performance`, CPU governor and energy-performance-preference → `performance`, turbo/boost on, `scaling_max_freq` → hardware maximum, Intel RAPL power limits → maximum allowed, PCIe ASPM → `performance`, NVIDIA persistence mode on and power limit → `power.max_limit`, AMD GPU power cap → `power1_cap_max` and DPM level `high` |
| **Windows** | a dedicated `llmbench Volle Leistung` power plan (copy of *Ultimate Performance*, falling back to *High performance*) with 100 % min/max processor state, aggressive boost, no core parking, no PCIe ASPM, no standby; NVIDIA power limit → `power.max_limit` |

```bash
llmbench performance status   # was anything set by llmbench?
llmbench performance on       # full performance now, without a benchmark
llmbench performance off      # restore the exact previous settings
llmbench run --no-performance-mode   # leave power settings untouched for one run
```

Power limits and sysfs values need root (Linux, via `sudo`; asked once if needed) or an elevated shell (Windows). Anything that cannot be set is listed in the run output and in `summary.json` (`performance_mode`, `warnings`) — the benchmark still runs. The original values are stored in `.runtime/performance_state.json`, so `performance off` always restores the state from before llmbench touched it. Configure it in `benchmark.yaml`:

```yaml
performance:
  enabled: true
  restore_after_run: false   # true = restore after every run
  use_sudo: true
```

Firmware-level limits (BIOS/UEFI PL1/PL2, laptop EC limits, thermal limits) cannot be lifted from the OS.

## llama.cpp setup

Install or verify llama.cpp directly:

```bash
llmbench install-llama-cpp --root .
```

For reproducible machine-to-machine comparisons, pin the llama.cpp revision in:

```text
llama-cpp-version.txt
```

Example:

```text
b10456
```

Linux/macOS:

```bash
llmbench install-llama-cpp --root . --tag b10456
```

Windows PowerShell:

```powershell
$env:LLMBENCH_LLAMACPP_TAG = "b10456"
```

The actual build identity is recorded in the result metadata.

---

## NVIDIA / CUDA behavior

On NVIDIA systems, llmbench integrates with NVIDIA tooling instead of treating the GPU as an anonymous accelerator.

Collected information includes:

- GPU model
- driver version
- VRAM
- compute capability
- VBIOS
- power limit
- utilization
- temperature
- power draw
- compute processes

On Linux, llmbench can build llama.cpp automatically with `GGML_CUDA=ON` when `nvcc` is available.

Backend selection can be controlled explicitly:

```bash
export LLMBENCH_LLAMACPP_BUILD_BACKEND=auto
export LLMBENCH_LLAMACPP_BUILD_BACKEND=cuda
export LLMBENCH_LLAMACPP_BUILD_BACKEND=vulkan
export LLMBENCH_LLAMACPP_BUILD_BACKEND=cpu
```

On PowerShell:

```powershell
$env:LLMBENCH_LLAMACPP_BUILD_BACKEND = "cuda"
```

---

## vLLM backend

vLLM runs through Docker rather than as a native llmbench Python dependency.

Install:

```bash
llmbench install-backend --backend vllm
```

Remove:

```bash
llmbench uninstall-backend --backend vllm
```

Select it in the benchmark configuration:

```yaml
tools:
  backend: "vllm"
  vllm_image: "vllm/vllm-openai:latest"
```

A vLLM profile can then define options such as tensor parallelism and GPU memory utilization.

---

## Standard model suite

The bundled model-suite management includes Q4_K_M variants of models such as:

- Qwen3-8B
- DeepSeek-R1-Distill-Qwen-7B
- Qwen3.8-27B
- Qwen2.5-72B-Instruct
- Mixtral-8x22B-Instruct

Download suites:

```bash
llmbench download --suite small
llmbench download --suite mid
llmbench download --suite heavy
llmbench download --suite all
```

Verify an existing suite without downloading:

```bash
llmbench download --suite all --verify-only
```

Split GGUF files are treated as one logical model. Partial shard sets are rejected as incomplete.

---

## Stress commands

```bash
llmbench stress-ttft --config benchmark.yaml
llmbench stress-multitenant --config benchmark.yaml
llmbench stress-oom --config benchmark.yaml
llmbench stress-quant --config benchmark.yaml
```

`stress-quant` compares different quantizations only when they belong to the same base model.

---

## Reproducibility

Every run records the information required to validate whether two benchmark results are actually comparable.

| Evidence | Purpose |
| --- | --- |
| `config_fingerprint` | Hash of result-relevant benchmark settings |
| `config` | Full configuration used for the run |
| `tools.llama_bench.binary.sha256` | Hash of the exact llama-bench binary |
| `tools.llama_cpp_build_ids` | llama.cpp build identity |
| `llmbench_version` | Benchmark framework version |
| `models[].model.sha256` | Exact model or combined GGUF shard fingerprint |
| hardware metadata | CPU, RAM, GPU, driver and execution environment |

When reproducibility matters, use:

```bash
llmbench compare run-a run-b --strict
```

The command exits with status code `1` when incompatible conditions are detected.

---

## Result structure

A run produces a self-contained result directory similar to:

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

The raw files preserve commands, stdout/stderr and telemetry. `summary.json` contains the aggregated data used for reports and comparisons.

---

## Reports

llmbench generates several output formats so results can be inspected by both humans and automation:

- **HTML** — interactive/readable report
- **PDF** — portable benchmark report
- **CSV** — tabular analysis
- **JSON** — full machine-readable result data
- **Terminal output** — quick local overview

---

## Docker image

The project includes a CUDA-enabled Docker image containing llmbench and the pinned llama.cpp runtime.

The CI pipeline:

- builds the image
- smoke-tests it without requiring a GPU
- verifies the included llama.cpp binaries
- scans HIGH and CRITICAL vulnerabilities with Trivy
- publishes SBOM metadata
- publishes build provenance
- pushes approved builds to GHCR

See [docs/DOCKER.md](docs/DOCKER.md) for usage details.

---

## Development

Install development dependencies:

```bash
pip install -e ".[dev]"
```

Run the main local checks:

```bash
ruff check .
mypy llmbench
pytest -q
```

Coverage:

```bash
pytest --cov=llmbench --cov-report=term-missing
```

Build the Python package:

```bash
python -m build
```

The GitHub Actions CI currently validates the project on:

- Ubuntu
- Windows
- Python 3.10
- Python 3.11
- Python 3.12
- Python 3.13
- Python 3.14

Additional CI checks include CodeQL, dependency review, `pip-audit`, packaging tests, coverage, Docker smoke tests and container vulnerability scanning.

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

---

## Security

Please do **not** publish suspected vulnerabilities as normal public issues.

See [SECURITY.md](SECURITY.md) for responsible-disclosure instructions.

The repository also uses:

- CodeQL
- GitHub Dependency Review
- `pip-audit`
- Trivy container scanning
- OpenSSF Scorecard
- Dependabot
- SHA-pinned GitHub Actions

---

## Documentation

| Document | Purpose |
| --- | --- |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development setup, architecture and contribution rules |
| [ROADMAP.md](ROADMAP.md) | Backend, telemetry and feature roadmap |
| [CHANGELOG.md](CHANGELOG.md) | Released changes |
| [docs/DOCKER.md](docs/DOCKER.md) | Docker usage |
| [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) | Release validation checklist |
| [SECURITY.md](SECURITY.md) | Vulnerability reporting |

---

## Project scope

This project is **not an official MLPerf submission runner**.

It is an independent open-source framework focused on reproducible benchmarking of local LLM inference servers and hardware.

---

## Contributing

Contributions are welcome.

Good contribution areas include:

- new benchmark backends
- additional telemetry providers
- test coverage
- platform compatibility
- report improvements
- reproducibility checks
- documentation

Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting a pull request.

---

## License

Released under the [MIT License](LICENSE).
