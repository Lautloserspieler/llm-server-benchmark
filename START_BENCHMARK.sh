#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"
ROOT_DIR=$(pwd)
CONFIG="benchmark.yaml"

echo "=== System Check ==="
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3.10+ is required."
    exit 1
fi

echo "=== Python Environment ==="
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -e .

echo "=== Llama.cpp Setup ==="
mkdir -p tools/llama.cpp
if [ ! -f "tools/llama.cpp/llama-bench" ] && [ ! -f "tools/llama.cpp/llama-server" ]; then
    echo "WARNING: Automatic download of llama.cpp is not yet fully implemented for Linux/macOS in this script."
    echo "Please compile or download llama-bench and llama-server for your system and place them in tools/llama.cpp/"
fi

echo "=== Configuration & Model Detection ==="
mkdir -p models
python -m llmbench bootstrap --config $CONFIG --root "$ROOT_DIR" --llama-dir "tools/llama.cpp" --models-dir models

if [ -z "$(ls -A models/*.gguf 2>/dev/null)" ]; then
    echo ""
    echo -e "\033[32mSetup finished.\033[0m No GGUF models found."
    echo -e "Please place one or more .gguf files in the \033[33mmodels/\033[0m directory and run this script again."
    exit 0
fi

echo "=== Pre-flight Check ==="
python -m llmbench doctor --config $CONFIG

echo "=== Benchmark ==="
python -m llmbench run --config $CONFIG
