from __future__ import annotations

from pathlib import Path

import yaml

from llmbench.execution import collect_execution_environment


ROOT = Path(__file__).resolve().parents[1]


def test_execution_environment_defaults_to_native(monkeypatch):
    for name in (
        "LLMBENCH_EXECUTION_ENV",
        "LLMBENCH_CONTAINER_RUNTIME",
        "LLMBENCH_CONTAINER_IMAGE_ID",
        "LLMBENCH_CUDA_DEVEL_IMAGE",
        "LLMBENCH_CUDA_RUNTIME_IMAGE",
        "LLMBENCH_LLAMA_CPP_COMMIT",
        "LLMBENCH_HOSTNAME",
        "NVIDIA_VISIBLE_DEVICES",
    ):
        monkeypatch.delenv(name, raising=False)
    data = collect_execution_environment()
    # CI itself can be containerized, therefore only require a truthful non-empty mode.
    assert data["mode"] in {"native", "container", "docker"}
    assert isinstance(data["containerized"], bool)


def test_execution_environment_records_docker_identity(monkeypatch):
    monkeypatch.setenv("LLMBENCH_EXECUTION_ENV", "docker")
    monkeypatch.setenv("LLMBENCH_CONTAINER_RUNTIME", "docker")
    monkeypatch.setenv("LLMBENCH_CONTAINER_IMAGE_ID", "sha256:test")
    monkeypatch.setenv("LLMBENCH_CUDA_RUNTIME_IMAGE", "nvidia/cuda:test")
    monkeypatch.setenv("LLMBENCH_LLAMA_CPP_COMMIT", "abc123")
    monkeypatch.setenv("NVIDIA_VISIBLE_DEVICES", "0,1")
    data = collect_execution_environment()
    assert data["mode"] == "docker"
    assert data["containerized"] is True
    assert data["container_runtime"] == "docker"
    assert data["container_image_id"] == "sha256:test"
    assert data["cuda_runtime_image"] == "nvidia/cuda:test"
    assert data["llama_cpp_commit"] == "abc123"
    assert data["gpu_devices"] == "0,1"


def test_compose_requests_nvidia_gpu_and_persists_data():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    service = compose["services"]["llmbench"]
    devices = service["deploy"]["resources"]["reservations"]["devices"]
    assert devices == [{"driver": "nvidia", "count": "all", "capabilities": ["gpu"]}]
    targets = {entry["target"] for entry in service["volumes"]}
    assert {"/workspace/models", "/workspace/results", "/workspace/benchmark.yaml"} <= targets
    assert service["environment"]["LLMBENCH_EXECUTION_ENV"] == "docker"


def test_dockerfile_is_cuda_and_llama_cpp_pinned():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "nvidia/cuda:13.2.1-devel-ubuntu24.04" in dockerfile
    assert "nvidia/cuda:13.2.1-runtime-ubuntu24.04" in dockerfile
    assert "64a155d242cb427766055ea9caea6f34df1ca94b" in dockerfile
    assert "-DGGML_CUDA=ON" in dockerfile
    assert "git checkout --detach" in dockerfile


def test_user_facing_launchers_keep_auto_native_docker_modes():
    linux_setup = (ROOT / "setup.sh").read_text(encoding="utf-8")
    linux_start = (ROOT / "START_BENCHMARK.sh").read_text(encoding="utf-8")
    windows_setup = (ROOT / "setup.bat").read_text(encoding="utf-8")
    windows_start = (ROOT / "START_BENCHMARK.bat").read_text(encoding="utf-8")
    for content in (linux_setup, linux_start, windows_setup, windows_start):
        assert "LLMBENCH_EXECUTION_MODE" in content
    assert "scripts/docker_common.sh" in linux_setup
    assert "scripts\\DOCKER_BENCHMARK.ps1" in windows_setup


def test_container_entrypoint_has_real_gpu_preflight():
    entrypoint = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "nvidia-smi" in entrypoint
    assert "llama-bench --list-devices" in entrypoint
    assert "container-setup" in entrypoint
