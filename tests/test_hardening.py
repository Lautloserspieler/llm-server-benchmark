from pathlib import Path

import pytest

from llmbench import llama_cpp_setup as lcs
from llmbench import soak, tuner
from llmbench.backends import llama_cpp as backend_mod
from llmbench.capacity import profile_vram_issue, total_gpu_vram_bytes
from llmbench.stress import multitenant

GIB = 1024 ** 3
MIB = 1024 ** 2


def _hardware(vram_mib: int = 32768) -> dict:
    return {"gpus": [{"memory.total": vram_mib}]}


def test_total_gpu_vram_bytes_accepts_hardware_and_telemetry_units():
    hardware = {
        "gpus": [
            {"memory.total": 1024},
            {"memory_total_bytes": 2 * GIB},
        ]
    }
    assert total_gpu_vram_bytes(hardware) == 3 * GIB


def test_full_gpu_capacity_guard_blocks_oversized_model():
    issue = profile_vram_issue(
        {"size_bytes": 41 * GIB},
        {"name": "Full-GPU", "gpu_layers": -1},
        _hardware(),
    )
    assert issue is not None
    assert "Full-GPU" in issue
    assert "Hybrid" in issue


def test_capacity_guard_allows_small_partial_and_explicit_override():
    assert profile_vram_issue(
        {"size_bytes": 4 * GIB},
        {"gpu_layers": -1},
        _hardware(),
    ) is None
    assert profile_vram_issue(
        {"size_bytes": 80 * GIB},
        {"gpu_layers": 20},
        _hardware(),
    ) is None
    assert profile_vram_issue(
        {"size_bytes": 80 * GIB},
        {"gpu_layers": -1, "allow_oversized_gpu": True},
        _hardware(),
    ) is None


def test_backend_skips_oversized_benchmark_before_llama_bench(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(backend_mod, "profile_vram_issue_for_path", lambda *_a, **_k: "too large")

    def fail_if_called(*_a, **_k):
        raise AssertionError("llama-bench must not start")

    monkeypatch.setattr(backend_mod, "run_llama_bench", fail_if_called)
    backend = backend_mod.LlamaCppBackend("bench", "server")
    result = backend.run_benchmark(
        "model.gguf",
        {"gpu_layers": -1},
        "generation",
        tmp_path,
        {},
    )
    assert result["status"] == "skipped_vram"
    assert result["capacity_guard"] is True


def test_backend_refuses_oversized_server_before_start(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(backend_mod, "profile_vram_issue_for_path", lambda *_a, **_k: "too large")

    def fail_if_called(*_a, **_k):
        raise AssertionError("llama-server must not start")

    monkeypatch.setattr(backend_mod, "start_llama_server", fail_if_called)
    backend = backend_mod.LlamaCppBackend("bench", "server")
    with pytest.raises(RuntimeError, match="VRAM-Preflight"):
        backend.start_server(
            "model.gguf",
            {"gpu_layers": -1},
            {"base_url": "http://127.0.0.1:8080"},
            {},
            tmp_path / "server.log",
        )


def test_soak_status_fails_when_any_load_path_has_zero_successes():
    status, error = soak._soak_status(
        {"successful": 3},
        {"successful": 0},
    )
    assert status == "failed"
    assert error is not None and "GPU" in error

    status, error = soak._soak_status(
        {"successful": 1},
        {"successful": 2},
    )
    assert status == "ok"
    assert error is None


def test_tuner_reads_top_level_gpu_telemetry_in_bytes():
    result = {
        "telemetry": {
            "gpus": [
                {"max_memory_used_bytes": 4 * GIB},
                {"max_memory_used_bytes": 2 * GIB},
            ]
        }
    }
    assert tuner._max_vram_used_bytes(result) == 6 * GIB


def test_multitenant_pair_uses_combined_vram_budget(monkeypatch):
    candidates = [
        {"model": {"name": "small-a"}, "size_bytes": 4 * GIB},
        {"model": {"name": "small-b"}, "size_bytes": 5 * GIB},
        {"model": {"name": "huge"}, "size_bytes": 28 * GIB},
    ]
    monkeypatch.setattr(multitenant, "_multitenant_candidates", lambda _cfg, _hw: candidates)
    pair, reason = multitenant._select_multitenant_pair({}, _hardware())
    assert reason is None
    assert pair is not None
    assert [item["model"]["name"] for item in pair] == ["small-a", "small-b"]


def test_multitenant_pair_skips_when_no_pair_fits(monkeypatch):
    candidates = [
        {"model": {"name": "a"}, "size_bytes": 16 * GIB},
        {"model": {"name": "b"}, "size_bytes": 16 * GIB},
    ]
    monkeypatch.setattr(multitenant, "_multitenant_candidates", lambda _cfg, _hw: candidates)
    pair, reason = multitenant._select_multitenant_pair({}, _hardware())
    assert pair is None
    assert reason is not None


def test_release_backend_preference_respects_explicit_choice(monkeypatch):
    monkeypatch.setenv("LLMBENCH_LLAMACPP_BUILD_BACKEND", "cuda")
    assert lcs._backends_to_try("linux", "x64") == []
    monkeypatch.setenv("LLMBENCH_LLAMACPP_BUILD_BACKEND", "vulkan")
    assert lcs._backends_to_try("linux", "x64") == ["vulkan"]
    monkeypatch.setenv("LLMBENCH_LLAMACPP_BUILD_BACKEND", "cpu")
    assert lcs._backends_to_try("linux", "x64") == ["cpu"]


def test_linux_nvidia_prefers_cuda_source_before_vulkan_release(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("LLMBENCH_LLAMACPP_BUILD_BACKEND", raising=False)
    monkeypatch.setattr(lcs, "target_platform", lambda: ("linux", "x64"))
    monkeypatch.setattr(lcs, "_nvidia_gpu_present", lambda: True)
    monkeypatch.setattr(lcs, "_which_nvcc", lambda: "/usr/local/cuda/bin/nvcc")
    monkeypatch.setattr(lcs, "_source_build_enabled", lambda: True)
    monkeypatch.setattr(
        lcs,
        "release_candidates",
        lambda _root, _tag: [
            {
                "tag_name": "b123",
                "draft": False,
                "assets": [
                    {
                        "name": "llama-b123-bin-ubuntu-vulkan-x64.tar.gz",
                        "browser_download_url": "https://example/vulkan.tar.gz",
                    }
                ],
            }
        ],
    )
    called: dict[str, object] = {}

    def fake_build(_root, _llama_dir, ref, _state_file, _arch, _force, _log, backends=None):
        called["ref"] = ref
        called["backends"] = backends
        return {"tag": ref, "backend": "cuda", "source_build": True}

    monkeypatch.setattr(lcs, "build_llama_cpp_from_source", fake_build)

    def fail_asset(*_a, **_k):
        raise AssertionError("Vulkan release must not be installed before CUDA build")

    monkeypatch.setattr(lcs, "_install_asset", fail_asset)
    result = lcs.ensure_llama_cpp(tmp_path, log=lambda _m: None)
    assert result["backend"] == "cuda"
    assert called["backends"] == ["cuda"]


def test_existing_vulkan_is_rejected_when_cuda_is_desired(tmp_path: Path, monkeypatch):
    llama_dir = tmp_path / "tools" / "llama.cpp"
    llama_dir.mkdir(parents=True)
    (llama_dir / "llama-bench").write_text("stub", encoding="utf-8")
    (llama_dir / "llama-server").write_text("stub", encoding="utf-8")
    state = llama_dir / ".llama-build.json"
    state.write_text('{"tag":"b1","backend":"vulkan"}', encoding="utf-8")
    monkeypatch.setattr(lcs, "probe", lambda _path: (True, "ok"))
    assert lcs._existing_install_ok(llama_dir, state, lambda _m: None, "cuda") is False
