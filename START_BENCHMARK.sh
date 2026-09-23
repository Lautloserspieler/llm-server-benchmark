#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
ROOT_DIR=$(pwd)
CONFIG="benchmark.yaml"
EXECUTION_MODE="${LLMBENCH_EXECUTION_MODE:-auto}"

# Terminal-Oberflaeche + Sprachsystem (Texte: scripts/locales/<lang>.sh)
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/ui.sh"
ui_select_language

if [ -f "models/.llmbench-model-selection.json" ]; then
    export LLMBENCH_USE_SAVED_SELECTION=1
fi

case "$EXECUTION_MODE" in
    auto|docker|native) ;;
    *)
        ui_fail setup.invalid_mode
        exit 1
        ;;
esac

ui_header start.title "$(ui_t setup.mode "$EXECUTION_MODE")"

if [ "$(uname -s)" = "Linux" ] && [ "$EXECUTION_MODE" != "native" ]; then
    # shellcheck disable=SC1091
    source "$ROOT_DIR/scripts/docker_common.sh"

    if llmbench_docker_ready; then
        ui_ok start.docker_detected
        llmbench_docker_run
        exit $?
    fi

    if [ "$EXECUTION_MODE" = "docker" ]; then
        ui_warn start.docker_setup_now
        llmbench_setup_docker
        llmbench_docker_run
        exit $?
    fi

    # Im Auto-Modus richten wir Docker beim Start nur dann nach, wenn Docker
    # bereits vorhanden ist. Eine systemweite Erstinstallation bleibt setup.sh vorbehalten.
    if command -v docker >/dev/null 2>&1 && command -v nvidia-smi >/dev/null 2>&1; then
        ui_step start.docker_repair
        if llmbench_setup_docker; then
            llmbench_docker_run
            exit $?
        fi
        ui_warn start.docker_repair_failed
    fi
fi

if [ "$EXECUTION_MODE" = "docker" ]; then
    ui_fail start.docker_not_ready
    exit 1
fi

# ------------------------------- Nativer Fallback -------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    ui_fail setup.python_manual
    exit 1
fi

ui_section setup.section_packages
if [ ! -d ".venv" ]; then
    ui_step setup.venv_create
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip setuptools wheel
python -m pip install --quiet -e "."
ui_ok setup.packages_ready

ui_section_raw "llama.cpp"
mkdir -p tools/llama.cpp
ui_step setup.llama_check
if ! python -m llmbench install-llama-cpp --root "$ROOT_DIR"; then
    ui_fail start.llama_failed
    ui_info start.llama_failed_hint
    exit 1
fi

ui_section start.suite_title
mkdir -p models
if ! python -m llmbench download --suite all --models-dir models --verify-only >/dev/null 2>&1; then
    ui_step start.suite_download
    python -m llmbench download --suite all --models-dir models
fi
python -m llmbench download --suite all --models-dir models --verify-only

ui_section setup.section_config
python -m llmbench bootstrap --config "$CONFIG" --root "$ROOT_DIR" \
    --llama-dir "tools/llama.cpp" --models-dir models

ui_section start.doctor_title
python -m llmbench doctor --config "$CONFIG"

ui_benchmark_options
args=(python -m llmbench run --config "$CONFIG" --duration "$UI_DURATION" --hardware "$UI_HARDWARE")
if [ "$UI_STRESS" = "1" ]; then
    args+=(--stress)
fi
"${args[@]}"
