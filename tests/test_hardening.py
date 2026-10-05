import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from llmbench import llama_bench, llama_cpp_setup as lcs
from llmbench import soak, tuner
from llmbench.backends import llama_cpp as backend_mod
from llmbench.capacity import profile_vram_issue, total_gpu_vram_bytes
from llmbench.stress import multitenant, oom, quant

GIB = 1024 ** 3


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


def test_backend_skips_oversized_benchmark_before_launch(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(backend_mod, "profile_vram_issue_for_path", lambda *_a, **_k: "too large")
    monkeypatch.setattr(backend_mod, "_nvidia_vram_used_mib", lambda: None)
    called = False

    def fake_run(*_args, **_kwargs):
        nonlocal called
        called = True
        return {"status": "ok"}

    monkeypatch.setattr(backend_mod, "run_llama_bench", fake_run)
    backend = backend_mod.LlamaCppBackend("bench", "server")
    result = backend.run_benchmark(
        "model.gguf",
        {"gpu_layers": -1},
        "generation",
        tmp_path,
        {},
    )

    assert called is False
    assert result["status"] == "skipped_capacity"
    assert result["error"] == "too large"
    assert result["runtime_adjustments"][0]["type"] == "capacity_preflight"
    assert result["runtime_adjustments"][0]["effective"] is None


def test_backend_rejects_oversized_server_before_launch(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(backend_mod, "profile_vram_issue_for_path", lambda *_a, **_k: "too large")
    monkeypatch.setattr(backend_mod, "_nvidia_vram_used_mib", lambda: None)
    called = False

    def fake_start(*_args, **_kwargs):
        nonlocal called
        called = True
        return SimpleNamespace(), "cmd"

    monkeypatch.setattr(backend_mod, "start_llama_server", fake_start)
    backend = backend_mod.LlamaCppBackend("bench", "server")

    with pytest.raises(RuntimeError, match="too large"):
        backend.start_server(
            "model.gguf",
            {"gpu_layers": -1},
            {"base_url": "http://127.0.0.1:8080"},
            {},
            tmp_path / "server.log",
        )

    assert called is False


def test_cpu_only_auto_threads_uses_all_allowed_logical_cpus(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(backend_mod, "profile_vram_issue_for_path", lambda *_a, **_k: None)
    monkeypatch.setattr(backend_mod, "_available_cpu_threads", lambda: 24)
    calls = {}

    def fake_run(_exe, _model_path, _bench_cfg, profile, _kind, _out_dir, on_progress=None):  # noqa: ARG001
        calls["profile"] = profile
        return {"status": "ok"}

    monkeypatch.setattr(backend_mod, "run_llama_bench", fake_run)
    backend = backend_mod.LlamaCppBackend("bench", "server")
    result = backend.run_benchmark(
        "model.gguf",
        {"gpu_layers": 0, "threads": "auto"},
        "generation",
        tmp_path,
        {},
    )

    assert calls["profile"]["threads"] == 24
    adjustment = result["runtime_adjustments"][0]
    assert adjustment["type"] == "cpu_threads"
    assert adjustment["effective"] == 24


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


def test_long_context_failure_keeps_completed_rows_and_marks_capacity(monkeypatch, tmp_path: Path):
    rows = [
        {
            "n_prompt": 512,
            "n_gen": 0,
            "n_depth": 0,
            "avg_ts": 3000.0,
            "stddev_ts": 1.0,
        },
        {
            "n_prompt": 0,
            "n_gen": 128,
            "n_depth": 0,
            "avg_ts": 80.0,
            "stddev_ts": 0.1,
        },
        {
            "n_prompt": 512,
            "n_gen": 0,
            "n_depth": 131072,
            "avg_ts": 1200.0,
            "stddev_ts": 2.0,
        },
        {
            "n_prompt": 0,
            "n_gen": 128,
            "n_depth": 131072,
            "avg_ts": 55.0,
            "stddev_ts": 0.1,
        },
    ]
    complete_json = json.dumps(rows, indent=2)
    truncated_json = complete_json[:-1]

    class FakeMonitor:
        def __init__(self, *_args, **_kwargs):
            pass

        def start(self):
            pass

        def stop(self):
            return {"sample_count": 0}

        def latest(self):
            return None

        def set_target_pid(self, _pid):
            pass

    monkeypatch.setattr(llama_bench, "resolve_executable", lambda exe: exe)
    monkeypatch.setattr(llama_bench, "load_flags", lambda *_a, **_k: [])
    monkeypatch.setattr(llama_bench, "no_op_offload_flags", lambda *_a, **_k: [])
    monkeypatch.setattr(llama_bench, "ResourceMonitor", FakeMonitor)
    monkeypatch.setattr(
        llama_bench,
        "_execute",
        lambda *_a, **_k: (
            truncated_json,
            "llama_bench: error: failed to create context with model 'model.gguf'",
            1,
            False,
        ),
    )

    result = llama_bench.run_llama_bench(
        "llama-bench",
        "model.gguf",
        {
            "repetitions": 1,
            "batch_size": 512,
            "ubatch_size": 512,
            "context_depths": [0, 131072, 262144],
            "long_context_prompt_tokens": 512,
            "long_context_generation_tokens": 128,
        },
        {"gpu_layers": -1},
        "long_context",
        tmp_path,
    )

    assert result["status"] == "partial"
    assert result["limit_status"] == "skipped_capacity"
    assert result["failed_context_depth"] == 262144
    assert result["completed_context_depths"] == [0, 131072]
    assert len(result["rows"]) == 4
    assert len(llama_bench.flatten_bench_rows(result)) == 4



def test_long_context_timeout_keeps_completed_rows_only(monkeypatch, tmp_path: Path):
    rows = [
        {"n_prompt": 512, "n_gen": 0, "n_depth": 0, "avg_ts": 3000.0, "stddev_ts": 1.0},
        {"n_prompt": 0, "n_gen": 128, "n_depth": 0, "avg_ts": 80.0, "stddev_ts": 0.1},
        {"n_prompt": 512, "n_gen": 0, "n_depth": 131072, "avg_ts": 1200.0, "stddev_ts": 2.0},
        {"n_prompt": 0, "n_gen": 128, "n_depth": 131072, "avg_ts": 55.0, "stddev_ts": 0.1},
        # Die naechste Stufe hat nur Prompt Processing abgeschlossen, als das
        # Zeitlimit erreicht wurde. Sie darf nicht als gueltige 262K-Stufe
        # in CSV/HTML/PDF auftauchen.
        {"n_prompt": 512, "n_gen": 0, "n_depth": 262144, "avg_ts": 700.0, "stddev_ts": 3.0},
    ]
    truncated_json = json.dumps(rows, indent=2)[:-1]

    class FakeMonitor:
        def __init__(self, *_args, **_kwargs):
            pass

        def start(self):
            pass

        def stop(self):
            return {"sample_count": 0}

        def latest(self):
            return None

        def set_target_pid(self, _pid):
            pass

    monkeypatch.setattr(llama_bench, "resolve_executable", lambda exe: exe)
    monkeypatch.setattr(llama_bench, "load_flags", lambda *_a, **_k: [])
    monkeypatch.setattr(llama_bench, "no_op_offload_flags", lambda *_a, **_k: [])
    monkeypatch.setattr(llama_bench, "ResourceMonitor", FakeMonitor)
    monkeypatch.setattr(
        llama_bench,
        "_execute",
        lambda *_a, **_k: (truncated_json, "benchmark 11/12: depth run 1/10", 15, True),
    )

    result = llama_bench.run_llama_bench(
        "llama-bench",
        "model.gguf",
        {
            "repetitions": 1,
            "batch_size": 512,
            "ubatch_size": 512,
            "context_depths": [0, 131072, 262144],
            "long_context_prompt_tokens": 512,
            "long_context_generation_tokens": 128,
            "gpu_timeout_seconds": 3600,
        },
        {"gpu_layers": -1},
        "long_context",
        tmp_path,
    )

    assert result["status"] == "partial"
    assert result["limit_status"] == "timeout"
    assert result["timed_out"] is True
    assert result["failed_context_depth"] == 262144
    assert result["completed_context_depths"] == [0, 131072]
    assert {row["n_depth"] for row in result["rows"]} == {0, 131072}
    assert len(result["rows"]) == 4


def test_oom_context_levels_migrate_legacy_default_but_preserve_custom_lists():
    legacy = {"stress": {"oom_contexts": list(oom.LEGACY_OOM_CONTEXTS)}}
    levels = oom._context_levels(legacy)

    assert levels == oom.DEFAULT_OOM_CONTEXTS
    assert levels[-3:] == [196608, 262144, 393216]

    custom = {"stress": {"oom_contexts": [4096, 32768, 65536]}}
    assert oom._context_levels(custom) == [4096, 32768, 65536]



def test_quant_stress_without_matching_variants_is_skipped(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        quant,
        "load_config",
        lambda _path: {
            "_config_dir": str(tmp_path),
            "project": {"output_dir": str(tmp_path / "results")},
        },
    )
    monkeypatch.setattr(quant, "discover_quant_groups", lambda *_args, **_kwargs: {})

    out_dir = tmp_path / "quant"
    status = asyncio.run(quant.run_quant_stress("benchmark.yaml", out_dir))

    assert status == 2
    result = json.loads((out_dir / "quant.json").read_text(encoding="utf-8"))
    assert result["status"] == "skipped"
    assert result["reason"] == "no_matching_quantizations"
    assert result["groups"] == []


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
