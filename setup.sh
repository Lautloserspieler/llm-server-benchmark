#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
ROOT_DIR=$(pwd)
EXECUTION_MODE="${LLMBENCH_EXECUTION_MODE:-auto}"

# Terminal-Oberflaeche + Sprachsystem (Texte: scripts/locales/<lang>.sh)
# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/lib/ui.sh"
ui_select_language

case "$EXECUTION_MODE" in
    auto|docker|native) ;;
    *)
        ui_fail setup.invalid_mode
        exit 1
        ;;
esac

ui_header setup.title "$(ui_t setup.mode "$EXECUTION_MODE")"

# Linux/NVIDIA: Docker ist der bevorzugte reproduzierbare Pfad. In auto wird
# bei Problemen auf den bisherigen nativen Pfad zurueckgefallen.
if [ "$(uname -s)" = "Linux" ] && [ "$EXECUTION_MODE" != "native" ]; then
    # shellcheck disable=SC1091
    source "$ROOT_DIR/scripts/docker_common.sh"
    if [ "$EXECUTION_MODE" = "docker" ] || command -v nvidia-smi >/dev/null 2>&1; then
        ui_section_raw "Docker + NVIDIA CUDA"
        if llmbench_setup_docker; then
            ui_done setup.done_docker setup.done_hint
            exit 0
        fi
        if [ "$EXECUTION_MODE" = "docker" ]; then
            ui_fail setup.docker_forced_failed
            exit 1
        fi
        ui_warn setup.docker_fallback
    fi
fi

if [ "$EXECUTION_MODE" = "docker" ]; then
    ui_fail setup.docker_unsupported
    exit 1
fi

# ------------------------------- Nativer Fallback -------------------------------
ui_section_raw "Python"
python_ok() {
    command -v python3 >/dev/null 2>&1 \
        && python3 -c 'import sys, venv; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}
if ! python_ok; then
    ui_warn setup.python_missing
    if command -v apt-get >/dev/null 2>&1 && ui_confirm_install "Python 3 (python3, python3-venv, python3-pip)"; then
        if [ "$(id -u)" -eq 0 ]; then SUDO=(); else SUDO=(sudo); fi
        ${SUDO[@]+"${SUDO[@]}"} apt-get update
        ${SUDO[@]+"${SUDO[@]}"} apt-get install -y python3 python3-venv python3-pip
    fi
    if ! python_ok; then
        ui_fail setup.python_manual
        exit 1
    fi
fi
ui_ok_raw "Python: $(python3 --version 2>&1)"

ui_section setup.section_packages
if [ ! -d ".venv" ]; then
    ui_step setup.venv_create
    python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
ui_step setup.pip_install
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -e "."
ui_ok setup.packages_ready

ui_section_raw "llama.cpp"
ui_step setup.llama_check
python -m llmbench install-llama-cpp --root "$ROOT_DIR"
ui_info setup.llama_hint

mkdir -p models
ui_section setup.section_models
python -m llmbench.model_select --models-dir models --select

# Der anschliessende Setup-Wizard prueft nur die gespeicherte Auswahl.
export LLMBENCH_USE_SAVED_SELECTION=1

ui_section setup.section_config
python -m llmbench setup

ui_done setup.done_native setup.done_hint
