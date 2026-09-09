# LLM Server Benchmark

Automated benchmark framework for llama.cpp and LLM servers with Docker support, GPU acceleration, and reproducible reports (HTML/PDF/Terminal).

## Features

- **Automated Benchmarking**: Tests GGUF models under various profiles (CPU-Only, Full-GPU, Hybrid)
- **Docker Runtime**: Production-ready Docker images with NVIDIA CUDA support, published to GHCR
- **Reproducibility**: Pinned llama.cpp commits, hardware documentation, SHA-tagged images
- **Comprehensive Testing**: Soak tests (sustained load), endpoint tests (multi-user), VRAM safety checks
- **Cross-Platform**: Windows (PowerShell), Linux (Ubuntu/Debian), macOS support
- **Detailed Reports**: HTML, PDF, and colorful terminal output with hardware info and telemetry

## Quick Start

### Prerequisites

- Python 3.10+ (automatically installed if missing)
- Docker Desktop (optional, for containerized runs)
- NVIDIA GPU with CUDA drivers (optional, for GPU benchmarks)

### Run Benchmark

**Linux/macOS:**
```bash
./setup.sh
./START_BENCHMARK.sh
```

**Windows:**
```powershell
.\setup.bat
.\START_BENCHMARK.bat
```

The setup scripts automatically:
- Install Python if not found
- Create virtual environment
- Install dependencies
- Download llama.cpp with appropriate backend (CUDA/Vulkan/CPU)

## Configuration

Edit `benchmark.yaml` to configure:
- Models (GGUF files in `models/` directory)
- Test profiles (CPU/GPU layer allocation, batch sizes, contexts)
- Test duration (short/long runs)
- Soak test settings (duration, throttling thresholds)

Example profile:
```yaml
models:
  - path: models/mistral-7b-instruct-v0.3.Q4_K_M.gguf
    profiles:
      - name: Full-GPU
        gpu_layers: 999
        batch_size: 512
      - name: CPU-Only
        gpu_layers: 0
        threads: auto
```

## Test Types

| Test | Description |
|------|-------------|
| **pp (Prompt Processing)** | Measures tokens/s for context prefill (no generation) |
| **tg (Token Generation)** | Measures tokens/s during text generation |
| **Soak (Sustained Load)** | CPU + GPU servers under simultaneous load for extended periods |
| **Endpoint (Multi-User)** | Concurrent requests to test server capacity |

## Reports

After each run, reports are generated in `results/<timestamp>/`:
- `report.html` – Interactive HTML report
- `report.pdf` – Printable PDF version
- `summary.json` – Machine-readable results
- `hardware.json` – Documented system state

Compare runs with:
```bash
llmbench compare results/run1/summary.json results/run2/summary.json
```

## Docker Mode

Use Docker for reproducible environments:

```bash
# Automatic (pulls from GHCR, falls back to local build)
LLMBENCH_EXECUTION_MODE=auto ./START_BENCHMARK.sh

# Force Docker
LLMBENCH_EXECUTION_MODE=docker ./START_BENCHMARK.sh

# Pin specific image for identical comparison
LLMBENCH_DOCKER_IMAGE=ghcr.io/lautloserspieler/llm-server-benchmark:sha-abc123 ./START_BENCHMARK.sh
```

See [`docs/DOCKER.md`](docs/DOCKER.md) for details.

## CLI Commands

```bash
llmbench run           # Run full benchmark suite
llmbench bootstrap     # Auto-detect models and create profiles
llmbench compare       # Compare multiple runs
llmbench doctor        # Check system configuration
llmbench export        # Export results (CSV, Markdown)
llmbench install-llama-cpp  # Manually install llama.cpp
```

## Reproducibility Guarantees

This project ensures reproducible benchmarks through:
- **Pinned llama.cpp**: Exact commit in `llama-cpp-version.txt`
- **Documented Hardware**: CPU, GPU, RAM, power state, drivers
- **Docker Images**: SHA-tagged images for identical environments
- **Test Conditions**: All parameters logged in `summary.json`

## Requirements

- Python 3.10+
- llama.cpp (auto-installed)
- Optional: Docker, NVIDIA CUDA Toolkit

## License

MIT License – see [`LICENSE`](LICENSE)

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md) for version history.
