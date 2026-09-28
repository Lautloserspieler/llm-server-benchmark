[Deutsch](DE-Installation) | [English](EN-Installation)

---

# Installation

## Requirements

Recommended:

- 64-bit Windows or Linux
- Python 3.10+
- enough free storage for model files
- current GPU driver
- Docker for container backends
- working GPU access inside containers for NVIDIA Docker workloads

## Windows

```powershell
git clone https://github.com/Lautloserspieler/llm-server-benchmark.git
cd llm-server-benchmark
.\setup.bat
```

Then start the benchmark launcher:

```powershell
.\START_BENCHMARK.bat
```

The setup checks Python, llama.cpp, WSL2/Docker Desktop, and GPU prerequisites. System-changing operations are not performed silently unless an explicit automatic installation mode was enabled.

## Linux / Ubuntu

```bash
git clone https://github.com/Lautloserspieler/llm-server-benchmark.git
cd llm-server-benchmark
chmod +x setup.sh START_BENCHMARK.sh
./setup.sh
./START_BENCHMARK.sh
```

## Native installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
llmbench install-llama-cpp --root .
```

## Models

```bash
llmbench download --suite small
llmbench download --suite mid
llmbench download --suite heavy
llmbench download --suite all
llmbench download --suite extreme
```

Verify the installation:

```bash
llmbench download --suite all --verify-only
llmbench doctor --config benchmark.yaml
```
