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

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e "."

echo ""
echo "[OK] Programm und Abhaengigkeiten sind bereit."
echo ""
echo "Hinweis: llama-bench und llama-server werden bei Bedarf automatisch"
echo "als vorgebauter Release von GitHub geladen (Vulkan bei erkannter GPU,"
echo "sonst CPU). Fuer denselben Build auf allen Vergleichsservern kann eine"
echo "feste Version in llama-cpp-version.txt eingetragen werden."
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
echo "   Weiter mit:"
echo "   ./.venv/bin/llmbench doctor --config benchmark.yaml"
echo "   ./.venv/bin/llmbench run    --config benchmark.yaml"
echo "===================================================="
echo ""
