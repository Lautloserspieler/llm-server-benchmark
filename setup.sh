#!/bin/bash

echo ""
echo "===================================================="
echo "   LLM Server Benchmark - Quick Setup (Linux/macOS)"
echo "===================================================="
echo ""

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "[!] Python 3 wurde nicht gefunden."
    echo "Bitte installiere Python 3.10+."
    exit 1
fi

# Create Virtual Environment
if [ ! -d ".venv" ]; then
    echo "[+] Erstelle virtuelle Umgebung (.venv)..."
    python3 -m venv .venv
fi

# Activate and Install
echo "[+] Installiere Abhängigkeiten..."
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "[V] Setup erfolgreich!"
echo ""
echo "Starte jetzt den Setup-Wizard..."
echo ""

python3 -m llmbench setup

echo ""
echo "===================================================="
echo "   Setup beendet. Du kannst jetzt starten mit:"
echo "   ./.venv/bin/python -m llmbench run"
echo "===================================================="
echo ""
