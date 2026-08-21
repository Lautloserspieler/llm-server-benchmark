#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
[ -f benchmark.yaml ] || cp benchmark.example.yaml benchmark.yaml
echo "Fertig. benchmark.yaml anpassen, danach: .venv/bin/python -m llmbench doctor --config benchmark.yaml"
