#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Python-Umgebung fehlt; erstelle .venv ..."
  if ! python3 -m venv .venv; then
    echo "Konnte .venv nicht erstellen. Installiere Python 3 mit venv-Unterstuetzung und starte erneut." >&2
    exit 1
  fi
fi
if ! .venv/bin/python -c 'from pydantic import field_validator; import yaml, httpx, rich, psutil, huggingface_hub' >/dev/null 2>&1; then
  echo "Installiere Projektabhaengigkeiten in .venv ..."
  .venv/bin/python -m pip install -e .
fi
exec .venv/bin/python scripts/smoke_all_backends.py "$@"
