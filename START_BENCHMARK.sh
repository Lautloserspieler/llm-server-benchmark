#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
ROOT_DIR=$(pwd)
CONFIG="benchmark.yaml"

echo "=== Systempruefung ==="
if ! command -v python3 >/dev/null 2>&1; then
    echo "Fehler: Python 3.10 oder neuer wird benoetigt."
    exit 1
fi

echo "=== Python-Umgebung ==="
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e "."

echo "=== llama.cpp ==="
mkdir -p tools/llama.cpp
if [ ! -f "tools/llama.cpp/llama-bench" ] || [ ! -f "tools/llama.cpp/llama-server" ]; then
    echo "llama.cpp fehlt. Installiere Release-Build oder kompiliere unter Linux automatisch aus Source..."
    if ! python -m llmbench install-llama-cpp --root "$ROOT_DIR"; then
        echo "FEHLER: Automatische llama.cpp-Installation/Source-Kompilierung fehlgeschlagen."
        echo "Unter Ubuntu/Debian muessen git, build-essential, cmake und pkg-config verfuegbar sein."
        echo "Lege alternativ llama-bench und llama-server manuell unter tools/llama.cpp/ ab."
        echo "Verwende auf allen Servern denselben Build."
        exit 1
    fi
fi

echo "=== V2 Standard-Suite ==="
mkdir -p models
if ! python -m llmbench download --suite all --models-dir models --verify-only >/dev/null 2>&1; then
    echo "Mindestens ein Standard-Modell fehlt oder ist unvollstaendig."
    echo "Fehlende Dateien werden automatisch von HuggingFace geladen."
    python -m llmbench download --suite all --models-dir models
fi
python -m llmbench download --suite all --models-dir models --verify-only

echo "=== Konfiguration und Modellerkennung ==="
python -m llmbench bootstrap --config "$CONFIG" --root "$ROOT_DIR" \
    --llama-dir "tools/llama.cpp" --models-dir models

echo "=== Vorabpruefung ==="
python -m llmbench doctor --config "$CONFIG"

echo "=== Benchmark ==="
echo "Wie lange soll der Test laufen?"
echo "  1: kurz (short)    - schnelle Ueberpruefung"
echo "  2: mittel (medium) - Standardwerte"
echo "  3: lang (long)     - praezise Ergebnisse"
read -r -p "Auswahl [1-3, Standard=2]: " choice

duration="medium"
if [ "$choice" = "1" ]; then
    duration="short"
elif [ "$choice" = "3" ]; then
    duration="long"
fi

echo ""
echo "Womit soll getestet werden?"
echo "  1: Nur CPU"
echo "  2: Nur GPU"
echo "  3: CPU und GPU (Standard, inkl. Dauerlast-Test)"
read -r -p "Auswahl [1-3, Standard=3]: " hw_choice

hardware="both"
if [ "$hw_choice" = "1" ]; then
    hardware="cpu"
elif [ "$hw_choice" = "2" ]; then
    hardware="gpu"
fi

read -r -p "Zusaetzliche V2-Stresstests (TTFT/Multi-Tenant/OOM/Quant) starten? [j/N]: " stress_choice
args=(python -m llmbench run --config "$CONFIG" --duration "$duration" --hardware "$hardware")
if [[ "$stress_choice" =~ ^[jJyY]$ ]]; then
    args+=(--stress)
fi
"${args[@]}"
