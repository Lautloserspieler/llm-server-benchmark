from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _is_containerized() -> bool:
    if os.environ.get("LLMBENCH_EXECUTION_ENV") == "docker":
        return True
    if Path("/.dockerenv").exists():
        return True
    try:
        text = Path("/proc/1/cgroup").read_text(encoding="utf-8", errors="ignore").lower()
        return any(token in text for token in ("docker", "containerd", "kubepods", "podman"))
    except OSError:
        return False


def collect_execution_environment() -> dict[str, Any]:
    """Describe the execution layer without depending on the Docker CLI.

    Values injected by the launcher are intentionally persisted in every run so
    native and containerized measurements cannot silently look identical.
    """
    containerized = _is_containerized()
    mode = os.environ.get("LLMBENCH_EXECUTION_ENV") or ("container" if containerized else "native")
    data: dict[str, Any] = {
        "mode": mode,
        "containerized": containerized,
    }

    mapping = {
        "container_runtime": "LLMBENCH_CONTAINER_RUNTIME",
        "container_image_id": "LLMBENCH_CONTAINER_IMAGE_ID",
        "cuda_devel_image": "LLMBENCH_CUDA_DEVEL_IMAGE",
        "cuda_runtime_image": "LLMBENCH_CUDA_RUNTIME_IMAGE",
        "cuda_architectures": "LLMBENCH_CUDA_ARCHITECTURES",
        "llama_cpp_commit": "LLMBENCH_LLAMA_CPP_COMMIT",
        "host_name": "LLMBENCH_HOSTNAME",
        "gpu_devices": "NVIDIA_VISIBLE_DEVICES",
    }
    for key, env_name in mapping.items():
        value = os.environ.get(env_name)
        if value not in (None, ""):
            data[key] = value

    return data
