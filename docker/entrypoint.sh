#!/usr/bin/env bash
set -euo pipefail

export PATH="/opt/venv/bin:/opt/llama.cpp:${PATH}"
export HF_HOME="${HF_HOME:-/workspace/.cache/huggingface}"

mkdir -p /workspace/models /workspace/results /workspace/.cache/huggingface

check_gpu() {
    if [ "${LLMBENCH_EXPECT_GPU:-1}" != "1" ]; then
        return 0
    fi
    if ! command -v nvidia-smi >/dev/null 2>&1; then
        echo "[!] NVIDIA-GPU wurde fuer den Container angefordert, aber nvidia-smi ist nicht verfuegbar." >&2
        echo "    Pruefe NVIDIA Container Toolkit bzw. Docker Desktop WSL2 GPU-Support." >&2
        return 1
    fi
    if ! nvidia-smi >/dev/null 2>&1; then
        echo "[!] NVIDIA Runtime ist vorhanden, aber die GPU ist im Container nicht nutzbar." >&2
        return 1
    fi
    if ! /opt/llama.cpp/llama-bench --list-devices 2>&1 | grep -iE 'CUDA|NVIDIA' >/dev/null; then
        echo "[!] llama.cpp sieht im Container kein CUDA/NVIDIA-Device." >&2
        /opt/llama.cpp/llama-bench --list-devices || true
        return 1
    fi
}

container_setup() {
    check_gpu
    touch /workspace/benchmark.yaml

    echo "=== Docker Runtime ==="
    python --version
    nvidia-smi --query-gpu=index,name,driver_version,memory.total --format=csv,noheader || true

    echo "=== Modelle ==="
    if ! python -m llmbench download --suite all --models-dir /workspace/models --verify-only >/dev/null 2>&1; then
        echo "Standard-Suite ist unvollstaendig. Fehlende Modelle/Shards werden geladen..."
        python -m llmbench download --suite all --models-dir /workspace/models
    fi
    python -m llmbench download --suite all --models-dir /workspace/models --verify-only

    echo "=== Konfiguration ==="
    python -m llmbench bootstrap \
        --config /workspace/benchmark.yaml \
        --root /workspace \
        --llama-dir /opt/llama.cpp \
        --models-dir /workspace/models

    python - <<'PY'
import os
from pathlib import Path
import yaml

path = Path('/workspace/benchmark.yaml')
data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
project = data.setdefault('project', {})
project['server_name'] = os.environ.get('LLMBENCH_HOSTNAME') or project.get('server_name') or 'llmbench-docker'
path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120), encoding='utf-8')
PY

    echo "=== Vorabpruefung ==="
    python -m llmbench doctor --config /workspace/benchmark.yaml
}

case "${1:-}" in
    container-check)
        check_gpu
        echo "[OK] Docker, NVIDIA Runtime und llama.cpp CUDA funktionieren."
        exit 0
        ;;
    container-setup)
        container_setup
        exit 0
        ;;
esac

check_gpu
exec "$@"
