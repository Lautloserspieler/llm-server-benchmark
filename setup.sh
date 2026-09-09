#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
ROOT_DIR=$(pwd)
EXECUTION_MODE="${LLMBENCH_EXECUTION_MODE:-auto}"

case "$EXECUTION_MODE" in
    auto|docker|native) ;;
    *)
        echo "[!] LLMBENCH_EXECUTION_MODE muss auto, docker oder native sein." >&2
        exit 1
        ;;
esac

echo ""
echo "===================================================="
echo "   LLM Server Benchmark - Einrichtung (Linux/macOS)"
echo "===================================================="
echo ""
echo "Ausfuehrungsmodus: $EXECUTION_MODE"

# Linux/NVIDIA: Docker ist der bevorzugte reproduzierbare Pfad. In auto wird
# bei Problemen auf den bisherigen nativen Pfad zurueckgefallen.
if [ "$(uname -s)" = "Linux" ] && [ "$EXECUTION_MODE" != "native" ]; then
    # shellcheck disable=SC1091
    source "$ROOT_DIR/scripts/docker_common.sh"
    if [ "$EXECUTION_MODE" = "docker" ] || command -v nvidia-smi >/dev/null 2>&1; then
        echo ""
        echo "=== Docker + NVIDIA CUDA Runtime ==="
        if llmbench_setup_docker; then
            echo ""
            echo "===================================================="
            echo "   Einrichtung abgeschlossen (Docker + CUDA)."
            echo "   Fuer den Benchmark nur START_BENCHMARK.sh starten."
            echo "===================================================="
            echo ""
            exit 0
        fi
        if [ "$EXECUTION_MODE" = "docker" ]; then
            echo "[!] Docker-Modus wurde erzwungen und konnte nicht eingerichtet werden." >&2
            exit 1
        fi
        echo "[!] Docker/CUDA konnte nicht vollstaendig eingerichtet werden."
        echo "    Auto-Modus verwendet jetzt den nativen Fallback."
    fi
fi

if [ "$EXECUTION_MODE" = "docker" ]; then
    echo "[!] Docker-Modus wird auf diesem System nicht automatisch unterstuetzt." >&2
    exit 1
fi

# ------------------------------- Nativer Fallback -------------------------------
echo ""
echo "=== Native Runtime ==="
if ! command -v python3 >/dev/null 2>&1; then
    echo "[!] Python 3 wurde nicht gefunden. Bitte Python 3.10 oder neuer installieren."
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "[+] Erstelle virtuelle Umgebung (.venv)..."
    python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e "."

echo ""
echo "[OK] Programm und Abhaengigkeiten sind bereit."
echo ""
echo "[+] Pruefe/installiere passenden llama.cpp-Build..."
python -m llmbench install-llama-cpp --root "$ROOT_DIR"
echo ""
echo "Hinweis: Auf Linux/NVIDIA wird CUDA automatisch bevorzugt, sobald"
echo "NVIDIA-Treiber und CUDA Toolkit (nvcc) vorhanden sind. Vulkan und CPU"
echo "bleiben automatische Fallbacks."
echo ""

mkdir -p models
echo "===================================================="
echo "  Modelle fuer den Benchmark auswaehlen"
echo "===================================================="
python -m llmbench.model_select --models-dir models --select

# Der anschliessende Setup-Wizard prueft nur die gespeicherte Auswahl.
export LLMBENCH_USE_SAVED_SELECTION=1

echo ""
echo "Starte jetzt die Konfiguration..."
python -m llmbench setup

echo ""
echo "===================================================="
echo "   Einrichtung abgeschlossen (Native)."
echo "   Fuer den Benchmark nur START_BENCHMARK.sh starten."
echo "===================================================="
echo ""
