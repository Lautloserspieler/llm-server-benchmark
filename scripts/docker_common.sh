#!/usr/bin/env bash
# Gemeinsame Docker-Helfer fuer setup.sh und START_BENCHMARK.sh.
# Diese Datei ist intern; fuer Nutzer bleiben die beiden Top-Level-Skripte die Einstiegspunkte.
# Texte laufen ueber scripts/lib/ui.sh (Sprachsystem); wird hier nachgeladen,
# falls der Aufrufer es noch nicht getan hat.
if ! declare -F ui_t >/dev/null 2>&1; then
    # shellcheck disable=SC1091
    source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/ui.sh"
fi

LLMBENCH_DOCKER_CMD=()
LLMBENCH_DOCKER_IMAGE="${LLMBENCH_DOCKER_IMAGE:-ghcr.io/lautloserspieler/llm-server-benchmark:latest}"
LLMBENCH_DOCKER_BUILD_LOCAL="${LLMBENCH_DOCKER_BUILD_LOCAL:-0}"
LLMBENCH_CUDA_SMOKE_IMAGE="${LLMBENCH_CUDA_SMOKE_IMAGE:-nvidia/cuda:13.2.1-base-ubuntu24.04}"

_llmbench_sudo() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        ui_fail docker.sudo_missing
        return 1
    fi
}

_llmbench_compose() {
    "${LLMBENCH_DOCKER_CMD[@]}" compose -f "$ROOT_DIR/compose.yaml" "$@"
}

_llmbench_docker() {
    "${LLMBENCH_DOCKER_CMD[@]}" "$@"
}

llmbench_resolve_docker_cmd() {
    LLMBENCH_DOCKER_CMD=()
    if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
        LLMBENCH_DOCKER_CMD=(docker)
    elif command -v docker >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1 && sudo docker info >/dev/null 2>&1; then
        LLMBENCH_DOCKER_CMD=(sudo docker)
    else
        return 1
    fi
    "${LLMBENCH_DOCKER_CMD[@]}" compose version >/dev/null 2>&1
}

_llmbench_linux_family() {
    [ -r /etc/os-release ] || return 1
    # shellcheck disable=SC1091
    . /etc/os-release
    case "${ID:-}" in
        ubuntu) echo ubuntu ;;
        debian) echo debian ;;
        *) return 1 ;;
    esac
}

llmbench_install_docker_engine_linux() {
    local family codename arch
    family=$(_llmbench_linux_family) || {
        ui_fail docker.only_debian
        return 1
    }

    # shellcheck disable=SC1091
    . /etc/os-release
    if [ "$family" = "ubuntu" ]; then
        codename="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
    else
        codename="${VERSION_CODENAME:-}"
    fi
    [ -n "$codename" ] || { ui_fail docker.no_codename; return 1; }
    arch=$(dpkg --print-architecture)

    ui_confirm_install "Docker Engine + Buildx + Compose" || { ui_fail docker.declined "Docker Engine"; return 1; }
    ui_step docker.install_engine
    _llmbench_sudo apt-get update
    _llmbench_sudo apt-get install -y ca-certificates curl
    _llmbench_sudo install -m 0755 -d /etc/apt/keyrings
    _llmbench_sudo curl -fsSL "https://download.docker.com/linux/${family}/gpg" -o /etc/apt/keyrings/docker.asc
    _llmbench_sudo chmod a+r /etc/apt/keyrings/docker.asc

    local tmp
    tmp=$(mktemp)
    cat >"$tmp" <<EOF
Types: deb
URIs: https://download.docker.com/linux/${family}
Suites: ${codename}
Components: stable
Architectures: ${arch}
Signed-By: /etc/apt/keyrings/docker.asc
EOF
    _llmbench_sudo cp "$tmp" /etc/apt/sources.list.d/docker.sources
    rm -f "$tmp"

    _llmbench_sudo apt-get update
    _llmbench_sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    if command -v systemctl >/dev/null 2>&1; then
        _llmbench_sudo systemctl enable --now docker
    fi
}

llmbench_install_compose_plugin_linux() {
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        return 0
    fi
    if _llmbench_linux_family >/dev/null 2>&1; then
        ui_confirm_install "Docker Compose Plugin" || { ui_fail docker.declined "Docker Compose Plugin"; return 1; }
        ui_step docker.install_compose
        _llmbench_sudo apt-get update
        _llmbench_sudo apt-get install -y docker-compose-plugin || return 1
    fi
}

llmbench_install_nvidia_toolkit_linux() {
    command -v nvidia-smi >/dev/null 2>&1 || {
        ui_fail docker.no_nvidia
        return 1
    }

    if ! command -v nvidia-ctk >/dev/null 2>&1; then
        _llmbench_linux_family >/dev/null 2>&1 || {
            ui_fail docker.toolkit_manual
            return 1
        }
        ui_confirm_install "NVIDIA Container Toolkit" || { ui_fail docker.declined "NVIDIA Container Toolkit"; return 1; }
        ui_step docker.install_toolkit
        _llmbench_sudo apt-get update
        _llmbench_sudo apt-get install -y ca-certificates curl gnupg
        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
            | gpg --dearmor \
            | _llmbench_sudo tee /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg >/dev/null
        curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
            | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
            | _llmbench_sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
        _llmbench_sudo apt-get update
        _llmbench_sudo apt-get install -y nvidia-container-toolkit
    fi

    ui_step docker.configure_runtime
    _llmbench_sudo nvidia-ctk runtime configure --runtime=docker
    if command -v systemctl >/dev/null 2>&1; then
        _llmbench_sudo systemctl restart docker
    fi
}

llmbench_prepare_docker_host() {
    if ! command -v docker >/dev/null 2>&1; then
        llmbench_install_docker_engine_linux || return 1
    fi
    llmbench_install_compose_plugin_linux || return 1

    if ! llmbench_resolve_docker_cmd; then
        ui_fail docker.daemon_unreachable
        return 1
    fi

    if command -v nvidia-smi >/dev/null 2>&1; then
        if ! command -v nvidia-ctk >/dev/null 2>&1; then
            llmbench_install_nvidia_toolkit_linux || return 1
        else
            # Idempotent erneut konfigurieren; nvidia-ctk erhaelt andere daemon.json-Einstellungen.
            _llmbench_sudo nvidia-ctk runtime configure --runtime=docker >/dev/null
            command -v systemctl >/dev/null 2>&1 && _llmbench_sudo systemctl restart docker
        fi
    else
        ui_fail docker.needs_driver
        return 1
    fi

    llmbench_resolve_docker_cmd
}

llmbench_prepare_docker_paths() {
    mkdir -p "$ROOT_DIR/models" "$ROOT_DIR/results" "$ROOT_DIR/.cache/huggingface" "$ROOT_DIR/.runtime"
    [ -e "$ROOT_DIR/benchmark.yaml" ] || touch "$ROOT_DIR/benchmark.yaml"

    export LLMBENCH_UID="${LLMBENCH_UID:-$(id -u)}"
    export LLMBENCH_GID="${LLMBENCH_GID:-$(id -g)}"
    export LLMBENCH_HOSTNAME="${LLMBENCH_HOSTNAME:-$(hostname)}"
    export LLMBENCH_MODELS_DIR="${LLMBENCH_MODELS_DIR:-$ROOT_DIR/models}"
    export LLMBENCH_RESULTS_DIR="${LLMBENCH_RESULTS_DIR:-$ROOT_DIR/results}"
    export LLMBENCH_CONFIG_FILE="${LLMBENCH_CONFIG_FILE:-$ROOT_DIR/benchmark.yaml}"
    export LLMBENCH_HF_CACHE_DIR="${LLMBENCH_HF_CACHE_DIR:-$ROOT_DIR/.cache/huggingface}"
    export LLMBENCH_EXPECT_GPU="${LLMBENCH_EXPECT_GPU:-1}"
    export LLMBENCH_DOCKER_IMAGE
}

llmbench_docker_gpu_smoke() {
    ui_step docker.gpu_check
    _llmbench_docker run --rm --gpus all "$LLMBENCH_CUDA_SMOKE_IMAGE" nvidia-smi >/dev/null
}

llmbench_set_container_image_id() {
    export LLMBENCH_CONTAINER_IMAGE_ID
    LLMBENCH_CONTAINER_IMAGE_ID=$(_llmbench_docker image inspect "$LLMBENCH_DOCKER_IMAGE" --format '{{.Id}}' 2>/dev/null || true)
    [ -n "$LLMBENCH_CONTAINER_IMAGE_ID" ]
}

llmbench_docker_build() {
    llmbench_prepare_docker_paths

    if [ "$LLMBENCH_DOCKER_BUILD_LOCAL" != "1" ]; then
        ui_step docker.image_pull "$LLMBENCH_DOCKER_IMAGE"
        if _llmbench_docker pull "$LLMBENCH_DOCKER_IMAGE"; then
            llmbench_set_container_image_id || return 1
            ui_ok docker.image_ok
            return 0
        fi

        ui_warn docker.image_pull_failed
        if llmbench_set_container_image_id; then
            ui_step docker.image_local "$LLMBENCH_DOCKER_IMAGE"
            return 0
        fi
        ui_step docker.image_build_fallback
    else
        ui_step docker.image_build_forced
    fi

    _llmbench_compose build llmbench
    llmbench_set_container_image_id || return 1
}

llmbench_docker_container_check() {
    llmbench_prepare_docker_paths
    llmbench_set_container_image_id || return 1
    _llmbench_compose run --rm llmbench container-check
}

llmbench_docker_setup_project() {
    llmbench_prepare_docker_paths
    llmbench_set_container_image_id || return 1
    _llmbench_compose run --rm llmbench container-setup
    printf '%s\n' "$LLMBENCH_CONTAINER_IMAGE_ID" > "$ROOT_DIR/.runtime/docker-ready"
    printf '%s\n' "$LLMBENCH_DOCKER_IMAGE" > "$ROOT_DIR/.runtime/docker-image"
}

llmbench_setup_docker() {
    llmbench_prepare_docker_host || return 1
    llmbench_prepare_docker_paths
    llmbench_docker_gpu_smoke || return 1
    llmbench_docker_build || return 1
    llmbench_docker_container_check || return 1
    llmbench_docker_setup_project || return 1
    ui_ok docker.runtime_ready
    ui_info_raw "Image: $LLMBENCH_DOCKER_IMAGE"
    ui_info_raw "Image-ID: $LLMBENCH_CONTAINER_IMAGE_ID"
}

llmbench_docker_ready() {
    [ -f "$ROOT_DIR/.runtime/docker-ready" ] || return 1
    llmbench_resolve_docker_cmd || return 1
    llmbench_docker_container_check >/dev/null 2>&1
}

llmbench_docker_refresh_config() {
    llmbench_prepare_docker_paths
    llmbench_set_container_image_id || return 1
    _llmbench_compose run --rm llmbench python -m llmbench bootstrap \
        --config /workspace/benchmark.yaml \
        --root /workspace \
        --llama-dir /opt/llama.cpp \
        --models-dir /workspace/models
    _llmbench_compose run --rm llmbench python -m llmbench doctor --config /workspace/benchmark.yaml
}

llmbench_docker_run() {
    llmbench_resolve_docker_cmd || return 1
    llmbench_prepare_docker_paths
    llmbench_docker_refresh_config || return 1

    ui_benchmark_options
    local args=(python -m llmbench run --config /workspace/benchmark.yaml --duration "$UI_DURATION" --hardware "$UI_HARDWARE")
    if [ "$UI_STRESS" = "1" ]; then
        args+=(--stress)
    fi

    llmbench_set_container_image_id || return 1
    _llmbench_compose run --rm llmbench "${args[@]}"
}
