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

Setup guides you through the terminal UI for:

- language
- required components
- model selection
- optional backends
- configuration

The model-selection screen also shows **DeepSeek-V4-Flash-0731 [EXTREME]**. Extreme is downloaded only when you explicitly select it.

After setup, start future benchmarks with:

```powershell
.\START_BENCHMARK.bat
```

## Linux / Ubuntu

```bash
git clone https://github.com/Lautloserspieler/llm-server-benchmark.git
cd llm-server-benchmark
chmod +x setup.sh START_BENCHMARK.sh
./setup.sh
```

The setup process, including model selection, also runs through the terminal UI on Linux.

Then use:

```bash
./START_BENCHMARK.sh
```

## Normal user workflow

After setup, normal benchmark runs do not require manually entering `llmbench run` or `llmbench download --suite` commands.

The intended flow is:

```text
setup.bat / setup.sh
        ↓
Model selection in the terminal UI
        ↓
START_BENCHMARK.bat / START_BENCHMARK.sh
        ↓
Choose duration
        ↓
Choose hardware mode
        ↓
Choose stress tests
        ↓
Benchmark
```

## Native/advanced use

The Python CLI remains available for development, automation, and manual special cases:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
llmbench install-llama-cpp --root .
```

For normal users, the terminal UI is the recommended path.
