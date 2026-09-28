# Installation

## Voraussetzungen

Empfohlen:

- 64-Bit Windows oder Linux
- Python 3.10+
- ausreichend freier Speicher für Modelle
- aktueller GPU-Treiber
- für Container-Backends: Docker
- für NVIDIA-Docker: funktionierender GPU-Zugriff im Container

## Windows

```powershell
git clone https://github.com/Lautloserspieler/llm-server-benchmark.git
cd llm-server-benchmark
.\setup.bat
```

Danach:

```powershell
.\START_BENCHMARK.bat
```

Das Setup prüft unter anderem Python, llama.cpp, WSL2/Docker Desktop und GPU-Voraussetzungen. Systemänderungen werden nicht still ausgeführt, sofern kein expliziter Auto-Install-Modus aktiviert wurde.

## Linux / Ubuntu

```bash
git clone https://github.com/Lautloserspieler/llm-server-benchmark.git
cd llm-server-benchmark
chmod +x setup.sh START_BENCHMARK.sh
./setup.sh
```

Benchmark starten:

```bash
./START_BENCHMARK.sh
```

## Native Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
llmbench install-llama-cpp --root .
```

Unter Windows:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
llmbench install-llama-cpp --root .
```

## Modelle

```bash
llmbench download --suite small
llmbench download --suite mid
llmbench download --suite heavy
llmbench download --suite all
```

Extreme-Test:

```bash
llmbench download --suite extreme
```

Vorhandene Modelle prüfen:

```bash
llmbench download --suite all --verify-only
```

## Installation prüfen

```bash
llmbench doctor --config benchmark.yaml
```

Vor einem Referenzlauf sollten keine unerwarteten Warnungen zu Backend, GPU, Modellen oder Energieprofil übrig sein.
