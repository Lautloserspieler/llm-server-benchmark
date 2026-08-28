#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

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

echo "[+] Installiere llmbench..."
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e "."

echo ""
echo "[OK] Installation abgeschlossen."
echo ""
echo "Hinweis: llama-bench und llama-server werden unter Linux/macOS nicht"
echo "automatisch heruntergeladen. Lege beide unter tools/llama.cpp/ ab"
echo "(Download: https://github.com/ggml-org/llama.cpp/releases oder selbst bauen)."
echo ""
echo "Starte jetzt die Einrichtung..."
echo ""

python -m llmbench setup

echo ""
echo "===================================================="
echo "   Weiter mit:"
echo "   ./.venv/bin/llmbench doctor --config benchmark.yaml"
echo "   ./.venv/bin/llmbench run    --config benchmark.yaml"
echo "===================================================="
echo ""
