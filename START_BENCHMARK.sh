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
python -m pip install -e ".[web]"

echo "=== llama.cpp ==="
mkdir -p tools/llama.cpp
if [ ! -f "tools/llama.cpp/llama-bench" ] || [ ! -f "tools/llama.cpp/llama-server" ]; then
    echo "HINWEIS: Der automatische Download von llama.cpp ist derzeit nur unter"
    echo "Windows implementiert. Bitte llama-bench und llama-server fuer dieses"
    echo "System bauen oder herunterladen und in tools/llama.cpp/ ablegen:"
    echo "  https://github.com/ggml-org/llama.cpp/releases"
    echo ""
    echo "Wichtig fuer den Serververgleich: auf allen Servern denselben Build"
    echo "verwenden. 'llmbench compare' prueft das und meldet Abweichungen."
fi

echo "=== Konfiguration und Modellerkennung ==="
mkdir -p models
python -m llmbench bootstrap --config "$CONFIG" --root "$ROOT_DIR" \
    --llama-dir "tools/llama.cpp" --models-dir models

if [ -z "$(find models -name '*.gguf' -print -quit 2>/dev/null)" ]; then
    echo ""
    echo "Einrichtung beendet. Es wurden keine GGUF-Modelle gefunden."
    echo "Lege eine oder mehrere .gguf-Dateien unter models/ ab und starte erneut."
    exit 0
fi

echo "=== Vorabpruefung ==="
python -m llmbench doctor --config "$CONFIG"

echo "=== Benchmark ==="
python -m llmbench run --config "$CONFIG"
