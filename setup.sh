#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
ROOT_DIR=$(pwd)

echo ""
echo "===================================================="
echo "   LLM Server Benchmark - Einrichtung (Linux/macOS)"
echo "===================================================="
echo ""

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
echo "bleiben automatische Fallbacks. Fuer denselben Build auf allen"
echo "Vergleichsservern kann eine feste Version in llama-cpp-version.txt"
echo "eingetragen werden."
echo ""

mkdir -p models
if ! python -m llmbench download --suite all --models-dir models --verify-only >/dev/null 2>&1; then
    echo "[+] V2-Standard-Suite ist unvollstaendig. Lade fehlende Modelle/Shards..."
    python -m llmbench download --suite all --models-dir models
fi
python -m llmbench download --suite all --models-dir models --verify-only

echo ""
echo "Starte jetzt die Konfiguration..."
python -m llmbench setup

echo ""
echo "===================================================="
echo "   Einrichtung abgeschlossen."
echo "   Fuer den Benchmark nur START_BENCHMARK.sh starten."
echo "===================================================="
echo ""
