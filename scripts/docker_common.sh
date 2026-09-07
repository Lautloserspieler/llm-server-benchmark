#!/usr/bin/env bash
# Gemeinsame Docker-Helfer fuer setup.sh und START_BENCHMARK.sh.
# Diese Datei ist intern; fuer Nutzer bleiben die beiden Top-Level-Skripte die Einstiegspunkte.

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
        echo "[!] Root-Rechte werden benoetigt, aber sudo ist nicht installiert." >&2
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
        echo "[!] Automatische Docker-Installation wird nur auf Ubuntu/Debian vorgenommen." >&2
        return 1
    }

    # shellcheck disable=SC1091
    . /etc/os-release
    if [ "$family" = "ubuntu" ]; then
        codename="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
    else
        codename="${VERSION_CODENAME:-}"
    fi
    [ -n "$codename" ] || { echo "[!] Linux-Codename konnte nicht ermittelt werden." >&2; return 1; }
    arch=$(dpkg --print-architecture)

    echo "[+] Installiere Docker Engine + Buildx + Compose Plugin aus dem offiziellen Docker-Repository..."
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
        echo "[+] Docker Compose Plugin fehlt; installiere es..."
        _llmbench_sudo apt-get update
        _llmbench_sudo apt-get install -y docker-compose-plugin || return 1
    fi
}

llmbench_install_nvidia_toolkit_linux() {
    command -v nvidia-smi >/dev/null 2>&1 || {
        echo "[!] Keine NVIDIA-GPU bzw. kein NVIDIA-Treiber auf dem Host erkannt." >&2
        return 1
    }

    if ! command -v nvidia-ctk >/dev/null 2>&1; then
        _llmbench_linux_family >/dev/null 2>&1 || {
            echo "[!] NVIDIA Container Toolkit muss auf dieser Distribution manuell installiert werden." >&2
            return 1
        }
        echo "[+] Installiere NVIDIA Container Toolkit aus dem offiziellen NVIDIA-Repository..."
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

    echo "[+] Konfiguriere NVIDIA Container Runtime fuer Docker..."
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
        echo "[!] Docker Daemon ist nicht erreichbar." >&2
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
        echo "[!] Docker-GPU-Modus benoetigt einen funktionierenden NVIDIA-Treiber auf dem Host." >&2
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
    echo "[+] Pruefe NVIDIA-GPU im Docker Runtime..."
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
        echo "[+] Lade fertiges Benchmark-Image: $LLMBENCH_DOCKER_IMAGE"
        if _llmbench_docker pull "$LLMBENCH_DOCKER_IMAGE"; then
            llmbench_set_container_image_id || return 1
            echo "[OK] GHCR-Image geladen; lokaler CUDA-Build wird uebersprungen."
            return 0
        fi

        echo "[!] GHCR-Image konnte nicht geladen werden." >&2
        if llmbench_set_container_image_id; then
            echo "[+] Verwende bereits lokal vorhandenes Image $LLMBENCH_DOCKER_IMAGE."
            return 0
        fi
        echo "[+] Kein lokales Image vorhanden; falle auf lokalen reproduzierbaren CUDA-Build zurueck."
    else
        echo "[+] LLMBENCH_DOCKER_BUILD_LOCAL=1: erzwinge lokalen CUDA-Build."
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
    echo "[OK] Docker/CUDA Benchmark-Runtime ist bereit."
    echo "     Image: $LLMBENCH_DOCKER_IMAGE"
    echo "     Image-ID: $LLMBENCH_CONTAINER_IMAGE_ID"
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

    echo "=== Benchmark (Docker + CUDA) ==="
    echo "Wie lange soll der Test laufen?"
    echo "  1: kurz (short)    - schnelle Ueberpruefung"
    echo "  2: mittel (medium) - Standardwerte"
    echo "  3: lang (long)     - praezise Ergebnisse"
    read -r -p "Auswahl [1-3, Standard=2]: " choice
    local duration="medium"
    [ "$choice" = "1" ] && duration="short"
    [ "$choice" = "3" ] && duration="long"

    echo ""
    echo "Womit soll getestet werden?"
    echo "  1: Nur CPU"
    echo "  2: Nur GPU"
    echo "  3: CPU und GPU (Standard, inkl. Dauerlast-Test)"
    read -r -p "Auswahl [1-3, Standard=3]: " hw_choice
    local hardware="both"
    [ "$hw_choice" = "1" ] && hardware="cpu"
    [ "$hw_choice" = "2" ] && hardware="gpu"

    read -r -p "Zusaetzliche V2-Stresstests (TTFT/Multi-Tenant/OOM/Quant) starten? [j/N]: " stress_choice
    local args=(python -m llmbench run --config /workspace/benchmark.yaml --duration "$duration" --hardware "$hardware")
    if [[ "$stress_choice" =~ ^[jJyY]$ ]]; then
        args+=(--stress)
    fi

    llmbench_set_container_image_id || return 1
    _llmbench_compose run --rm llmbench "${args[@]}"
}
