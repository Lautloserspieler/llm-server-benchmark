#!/usr/bin/env bash
set -euo pipefail

export PATH="/opt/venv/bin:/opt/llama.cpp:${PATH}"
export HF_HOME="${HF_HOME:-/workspace/.cache/huggingface}"

mkdir -p /workspace/models /workspace/results /workspace/.cache/huggingface

# Das Image enthaelt scripts/ nicht; die wenigen Texte hier kommen daher direkt
# zweisprachig. LLMBENCH_LANG reichen setup/START_BENCHMARK ueber compose.yaml durch.
say() {
    if [ "${LLMBENCH_LANG:-de}" = "en" ]; then printf '%s\n' "$2"; else printf '%s\n' "$1"; fi
}

check_gpu() {
    if [ "${LLMBENCH_EXPECT_GPU:-1}" != "1" ]; then
        return 0
    fi
    if ! command -v nvidia-smi >/dev/null 2>&1; then
        say "  [X]  NVIDIA-GPU wurde für den Container angefordert, aber nvidia-smi ist nicht verfügbar." \
            "  [X]  An NVIDIA GPU was requested for the container, but nvidia-smi is not available." >&2
        say "       NVIDIA Container Toolkit bzw. GPU-Support von Docker Desktop/WSL2 prüfen." \
            "       Check the NVIDIA Container Toolkit or Docker Desktop/WSL2 GPU support." >&2
        return 1
    fi
    if ! nvidia-smi >/dev/null 2>&1; then
        say "  [X]  NVIDIA-Runtime ist vorhanden, aber die GPU ist im Container nicht nutzbar." \
            "  [X]  The NVIDIA runtime is present, but the GPU is not usable inside the container." >&2
        return 1
    fi
    if ! /opt/llama.cpp/llama-bench --list-devices 2>&1 | grep -iE 'CUDA|NVIDIA' >/dev/null; then
        say "  [X]  llama.cpp sieht im Container kein CUDA/NVIDIA-Gerät." \
            "  [X]  llama.cpp does not see a CUDA/NVIDIA device inside the container." >&2
        /opt/llama.cpp/llama-bench --list-devices || true
        return 1
    fi
}

container_setup() {
    check_gpu
    touch /workspace/benchmark.yaml

    say "  ── Docker-Runtime" "  ── Docker runtime"
    python --version
    nvidia-smi --query-gpu=index,name,driver_version,memory.total --format=csv,noheader || true

    say "  ── Modelle" "  ── Models"
    python -m llmbench.model_select --models-dir /workspace/models --select
    export LLMBENCH_USE_SAVED_SELECTION=1
    python -m llmbench download --suite all --models-dir /workspace/models --verify-only

    say "  ── Konfiguration" "  ── Configuration"
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

    say "  ── Vorprüfung" "  ── Pre-check"
    python -m llmbench doctor --config /workspace/benchmark.yaml
}

case "${1:-}" in
    container-check)
        check_gpu
        say "  [OK] Docker, NVIDIA-Runtime und llama.cpp CUDA funktionieren." \
            "  [OK] Docker, NVIDIA runtime and llama.cpp CUDA are working."
        exit 0
        ;;
    container-setup)
        container_setup
        exit 0
        ;;
esac

check_gpu
exec "$@"
