"""CUDA must not silently turn into Vulkan (Vulkan is much slower on NVIDIA)."""

from __future__ import annotations

import pytest

from llmbench import gpu_backend
from llmbench.provenance import condition_rows
from llmbench.runner import _check_gpu_backend

CUDA_DEVICES = "Available devices:\n  CUDA0: NVIDIA GeForce RTX 5070 (12227 MiB, 11000 MiB free)\n"
VULKAN_DEVICES = "Available devices:\n  Vulkan0: NVIDIA GeForce RTX 5070 (12227 MiB, 11000 MiB free)\n"


def _tools(devices: str | None, installed: str | None = None, requested: str | None = None) -> dict:
    marker = {}
    if installed:
        marker["backend"] = installed
    if requested:
        marker["requested_backend"] = requested
    return {"llama_bench": {"devices_output": devices, "build_marker": marker}}


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (CUDA_DEVICES, ["cuda"]),
        (VULKAN_DEVICES, ["vulkan"]),
        ("  CUDA0: a\n  CUDA1: b\n  Vulkan0: c\n", ["cuda", "vulkan"]),
        ("  ROCm0: AMD\n  Metal0: Apple\n", ["hip", "metal"]),
        ("Available devices:\n", []),
        ("", []),
        (None, []),
        ("some unrelated: text line", []),
    ],
)
def test_runtime_gpu_apis_reads_what_the_binary_reports(output, expected):
    assert gpu_backend.runtime_gpu_apis(output) == expected


def test_effective_backend_prefers_the_runtime_report_over_the_install_marker():
    info = gpu_backend.effective_backend(_tools(VULKAN_DEVICES, installed="cuda"))
    assert info["effective"] == "vulkan" and info["installed"] == "cuda"


def test_effective_backend_falls_back_to_the_marker_without_a_device_list():
    assert gpu_backend.label(_tools("", installed="cpu")) == "cpu"
    assert gpu_backend.label({}) == "unbekannt"


def test_requested_cuda_with_a_vulkan_build_is_an_error_not_a_vulkan_run():
    verdict = gpu_backend.check(_tools(VULKAN_DEVICES, installed="vulkan"), nvidia_present=True, uses_gpu=True,
                                requested="cuda")
    assert verdict is not None and verdict[0] == "error"
    assert "vulkan" in verdict[1] and "--backend cuda" in verdict[1]


def test_requested_cuda_with_a_cuda_build_passes():
    assert gpu_backend.check(_tools(CUDA_DEVICES, installed="cuda"), nvidia_present=True, uses_gpu=True,
                             requested="cuda") is None


def test_requested_cuda_is_read_from_the_install_marker_too():
    tools = _tools(VULKAN_DEVICES, installed="vulkan", requested="cuda")
    verdict = gpu_backend.check(tools, nvidia_present=True, uses_gpu=True)
    assert verdict is not None and verdict[0] == "error"


def test_auto_with_nvidia_and_vulkan_warns_but_still_runs():
    verdict = gpu_backend.check(_tools(VULKAN_DEVICES, installed="vulkan"), nvidia_present=True, uses_gpu=True)
    assert verdict is not None and verdict[0] == "warning"
    assert "langsamer" in verdict[1]


@pytest.mark.parametrize(
    ("nvidia", "uses_gpu"),
    [(False, True), (True, False)],
    ids=["no_nvidia_card", "cpu_only_run"],
)
def test_no_warning_without_an_nvidia_gpu_or_without_gpu_profiles(nvidia, uses_gpu):
    assert gpu_backend.check(_tools(VULKAN_DEVICES, installed="vulkan"), nvidia_present=nvidia,
                             uses_gpu=uses_gpu) is None


def test_explicit_vulkan_choice_is_respected_without_a_warning():
    assert gpu_backend.check(_tools(VULKAN_DEVICES, installed="vulkan"), nvidia_present=True, uses_gpu=True,
                             requested="vulkan") is None


# ----------------------------------------------------------------- runner glue


def _cfg(backend="llama_cpp", gpu_layers=-1):
    return {"tools": {"backend": backend}, "models": [{"name": "M", "profiles": [{"name": "P", "gpu_layers": gpu_layers}]}]}


@pytest.fixture
def nvidia(monkeypatch):
    monkeypatch.setattr("llmbench.llama_cpp_setup.nvidia_gpu_present", lambda: True)
    monkeypatch.delenv("LLMBENCH_LLAMACPP_BUILD_BACKEND", raising=False)


@pytest.mark.usefixtures("nvidia")
def test_runner_check_warns_for_vulkan_on_nvidia():
    message = _check_gpu_backend(_cfg(), _tools(VULKAN_DEVICES, installed="vulkan"), "both")
    assert message and "Vulkan" in message


@pytest.mark.usefixtures("nvidia")
def test_runner_check_aborts_when_cuda_was_requested_via_the_environment(monkeypatch):
    monkeypatch.setenv("LLMBENCH_LLAMACPP_BUILD_BACKEND", "cuda")
    with pytest.raises(RuntimeError, match="CUDA wurde angefordert"):
        _check_gpu_backend(_cfg(), _tools(VULKAN_DEVICES, installed="vulkan"), "gpu")


@pytest.mark.usefixtures("nvidia")
def test_runner_check_ignores_cpu_runs_and_container_backends():
    assert _check_gpu_backend(_cfg(), _tools(VULKAN_DEVICES, installed="vulkan"), "cpu") is None
    assert _check_gpu_backend(_cfg(gpu_layers=0), _tools(VULKAN_DEVICES, installed="vulkan"), "both") is None
    assert _check_gpu_backend(_cfg(backend="ollama"), {}, "both") is None


@pytest.mark.usefixtures("nvidia")
def test_runner_check_is_quiet_for_a_cuda_build():
    assert _check_gpu_backend(_cfg(), _tools(CUDA_DEVICES, installed="cuda"), "both") is None


def test_the_conditions_table_shows_which_gpu_api_was_used():
    summary = {"backend": "llama_cpp", "tools": _tools(VULKAN_DEVICES, installed="vulkan"), "config": {}}
    rows = dict(condition_rows(summary))
    assert rows["GPU-API (llama.cpp)"] == "vulkan"
