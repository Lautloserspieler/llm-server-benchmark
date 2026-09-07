#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
ROOT_DIR=$(pwd)
CONFIG="benchmark.yaml"
EXECUTION_MODE="${LLMBENCH_EXECUTION_MODE:-auto}"

case "$EXECUTION_MODE" in
    auto|docker|native) ;;
    *)
        echo "Fehler: LLMBENCH_EXECUTION_MODE muss auto, docker oder native sein." >&2
        exit 1
        ;;
esac

echo "=== Systempruefung ==="
echo "Ausfuehrungsmodus: $EXECUTION_MODE"

if [ "$(uname -s)" = "Linux" ] && [ "$EXECUTION_MODE" != "native" ]; then
    # shellcheck disable=SC1091
    source "$ROOT_DIR/scripts/docker_common.sh"

    if llmbench_docker_ready; then
        echo "=== Docker + CUDA Runtime erkannt ==="
        llmbench_docker_run
        exit $?
    fi

    if [ "$EXECUTION_MODE" = "docker" ]; then
        echo "Docker-Modus ist erzwungen, aber noch nicht bereit. Fuehre die Docker-Einrichtung aus..."
        llmbench_setup_docker
        llmbench_docker_run
        exit $?
    fi

    # Im Auto-Modus richten wir Docker beim Start nur dann nach, wenn Docker
    # bereits vorhanden ist. Eine systemweite Erstinstallation bleibt setup.sh vorbehalten.
    if command -v docker >/dev/null 2>&1 && command -v nvidia-smi >/dev/null 2>&1; then
        echo "Docker/NVIDIA erkannt, aber Runtime noch nicht fertig. Versuche automatische Reparatur..."
        if llmbench_setup_docker; then
            llmbench_docker_run
            exit $?
        fi
        echo "Docker-Reparatur fehlgeschlagen; Auto-Modus faellt auf Native zurueck."
    fi
fi

if [ "$EXECUTION_MODE" = "docker" ]; then
    echo "Fehler: Docker-Modus ist auf diesem System nicht bereit." >&2
    exit 1
fi

# ------------------------------- Nativer Fallback -------------------------------
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
echo "Pruefe llama.cpp-Build und Backend (CUDA wird auf NVIDIA bevorzugt)..."
if ! python -m llmbench install-llama-cpp --root "$ROOT_DIR"; then
    echo "FEHLER: Automatische llama.cpp-Installation/Source-Kompilierung fehlgeschlagen."
    echo "Unter Ubuntu/Debian muessen git, build-essential, cmake und pkg-config verfuegbar sein."
    echo "Fuer CUDA muss das NVIDIA CUDA Toolkit inklusive nvcc installiert sein."
    echo "Lege alternativ llama-bench und llama-server manuell unter tools/llama.cpp/ ab."
    exit 1
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

echo "=== Benchmark (Native) ==="
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
