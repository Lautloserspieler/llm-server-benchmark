[Deutsch](DE-Installation) | [English](EN-Installation)

---

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

Das Setup prüft Python, llama.cpp, WSL2/Docker Desktop und GPU-Voraussetzungen. Systemänderungen werden nicht still ausgeführt, sofern kein expliziter Auto-Install-Modus aktiviert wurde.

## Linux / Ubuntu

```bash
git clone https://github.com/Lautloserspieler/llm-server-benchmark.git
cd llm-server-benchmark
chmod +x setup.sh START_BENCHMARK.sh
./setup.sh
./START_BENCHMARK.sh
```

## Native Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
llmbench install-llama-cpp --root .
```

## Modelle

```bash
llmbench download --suite small
llmbench download --suite mid
llmbench download --suite heavy
llmbench download --suite all
llmbench download --suite extreme
```

Prüfen:

```bash
llmbench download --suite all --verify-only
llmbench doctor --config benchmark.yaml
```
