import json
from pathlib import Path

import pytest

from llmbench.backends import DEFAULT_BACKEND, backend_name, get_backend
from llmbench.backends.base import BenchmarkBackend
from llmbench.backends.llama_cpp import LlamaCppBackend
from llmbench.runner import BENCH_KINDS, SOAK_LABELS, _resolve_endpoint_profile, count_tests, filter_profiles_by_hardware, run_suite


def _cfg(models, soak_enabled=True):
    return {"models": models, "soak": {"enabled": soak_enabled}}


def test_count_tests_adds_soak_labels_when_both_profiles_present():
    models = [{
        "name": "M",
        "profiles": [{"name": "Full-GPU", "gpu_layers": -1}, {"name": "CPU-Only", "gpu_layers": 0}],
    }]
    total = count_tests(_cfg(models))
    assert total == 2 * len(BENCH_KINDS) + len(SOAK_LABELS)


def test_count_tests_skips_soak_without_a_cpu_profile():
    models = [{"name": "M", "profiles": [{"name": "Full-GPU", "gpu_layers": -1}]}]
    total = count_tests(_cfg(models))
    assert total == 1 * len(BENCH_KINDS)


def test_count_tests_skips_soak_when_disabled():
    models = [{
        "name": "M",
        "profiles": [{"name": "Full-GPU", "gpu_layers": -1}, {"name": "CPU-Only", "gpu_layers": 0}],
    }]
    total = count_tests(_cfg(models, soak_enabled=False))
    assert total == 2 * len(BENCH_KINDS)


def test_count_tests_respects_selected_model_filter():
    models = [
        {"name": "A", "profiles": [{"name": "GPU", "gpu_layers": -1}]},
        {"name": "B", "profiles": [{"name": "GPU", "gpu_layers": -1}, {"name": "CPU", "gpu_layers": 0}]},
    ]
    total = count_tests(_cfg(models), selected_model="a")
    assert total == 1 * len(BENCH_KINDS)


# --------------------------------------------------------------------------- filter_profiles_by_hardware

_PROFILES = [
    {"name": "Full-GPU", "gpu_layers": -1},
    {"name": "CPU-Only", "gpu_layers": 0},
    {"name": "Hybrid-30L", "gpu_layers": 30},
]


def test_filter_profiles_both_returns_everything_unchanged():
    assert filter_profiles_by_hardware(_PROFILES, "both") == _PROFILES


def test_filter_profiles_cpu_keeps_only_gpu_layers_zero():
    result = filter_profiles_by_hardware(_PROFILES, "cpu")
    assert [p["name"] for p in result] == ["CPU-Only"]


def test_filter_profiles_gpu_keeps_full_gpu_and_hybrid():
    result = filter_profiles_by_hardware(_PROFILES, "gpu")
    assert [p["name"] for p in result] == ["Full-GPU", "Hybrid-30L"]


def test_filter_profiles_handles_empty_list():
    assert filter_profiles_by_hardware([], "cpu") == []


# --------------------------------------------------------------------------- count_tests(hardware_target=...)

def test_count_tests_hardware_cpu_only_counts_only_cpu_profile():
    models = [{
        "name": "M",
        "profiles": [{"name": "Full-GPU", "gpu_layers": -1}, {"name": "CPU-Only", "gpu_layers": 0}],
    }]
    total = count_tests(_cfg(models), hardware_target="cpu")
    assert total == 1 * len(BENCH_KINDS)


def test_count_tests_hardware_restriction_excludes_soak_even_when_both_profiles_exist():
    models = [{
        "name": "M",
        "profiles": [{"name": "Full-GPU", "gpu_layers": -1}, {"name": "CPU-Only", "gpu_layers": 0}],
    }]
    total_cpu = count_tests(_cfg(models), hardware_target="cpu")
    total_gpu = count_tests(_cfg(models), hardware_target="gpu")
    assert total_cpu == 1 * len(BENCH_KINDS)
    assert total_gpu == 1 * len(BENCH_KINDS)


# --------------------------------------------------------------------------- _resolve_endpoint_profile

def test_resolve_endpoint_profile_defaults_to_first_when_unset():
    profile, note = _resolve_endpoint_profile(_PROFILES, "M", {})
    assert profile["name"] == "Full-GPU"
    assert note is None


def test_resolve_endpoint_profile_matches_by_name():
    profile, note = _resolve_endpoint_profile(_PROFILES, "M", {"profile": "CPU-Only"})
    assert profile["name"] == "CPU-Only"
    assert note is None


def test_resolve_endpoint_profile_falls_back_and_warns_when_name_not_found():
    profile, note = _resolve_endpoint_profile(_PROFILES, "M", {"profile": "Does-Not-Exist"})
    assert profile["name"] == "Full-GPU"
    assert note is not None
    assert "Does-Not-Exist" in note


# --------------------------------------------------------------- get_backend

def _tools(**overrides):
    tools = {"llama_bench": "llama-bench", "llama_server": "llama-server"}
    tools.update(overrides)
    return tools


def test_backend_name_defaults_to_llama_cpp_without_the_key():
    assert backend_name({"tools": _tools()}) == "llama_cpp"
    assert backend_name({}) == DEFAULT_BACKEND


def test_get_backend_returns_llama_cpp_backend_by_default():
    """Eine Konfiguration ohne tools.backend muss sich verhalten wie bisher."""
    backend = get_backend({"tools": _tools()})
    assert isinstance(backend, LlamaCppBackend)
    assert backend.llama_bench_exe == "llama-bench"
    assert backend.llama_server_exe == "llama-server"


def test_get_backend_dispatches_to_vllm():
    from llmbench.backends.vllm import VllmBackend

    backend = get_backend({"tools": _tools(backend="vllm"), "endpoint": {}})
    assert isinstance(backend, VllmBackend)
    assert backend.image == "vllm/vllm-openai:latest"


def test_get_backend_rejects_unknown_backend():
    with pytest.raises(ValueError, match="Unbekanntes Backend"):
        get_backend({"tools": _tools(backend="sglang")})


# ------------------------------------------------- Lifecycle-Hooks (Regression)

def test_llama_cpp_backend_does_not_override_the_hooks():
    """Die Hooks muessen fuer llama.cpp die geerbten no-ops bleiben - sonst
    aendert sich sein Verhalten gegenueber frueher."""
    assert "begin_profile" not in LlamaCppBackend.__dict__
    assert "end_profile" not in LlamaCppBackend.__dict__
    assert LlamaCppBackend.begin_profile is BenchmarkBackend.begin_profile
    assert LlamaCppBackend.end_profile is BenchmarkBackend.end_profile


def test_llama_cpp_hooks_are_callable_no_ops(tmp_path: Path):
    backend = LlamaCppBackend("llama-bench", "llama-server")
    assert backend.begin_profile("m.gguf", {"name": "P"}, {}, tmp_path) is None
    assert backend.end_profile() is None


# -------------------------------------------------------- run_suite Integration

class _RecordingBackend(BenchmarkBackend):
    """Protokolliert die Reihenfolge der Backend-Aufrufe."""

    def __init__(self, fail_on_kind: str | None = None):
        self.events: list[str] = []
        self.fail_on_kind = fail_on_kind

    def begin_profile(self, _model_path, profile, _bench_cfg, _out_dir):
        self.events.append(f"begin:{profile['name']}")

    def end_profile(self):
        self.events.append("end")

    def run_benchmark(self, _model_path, _profile, kind, _out_dir, _bench_cfg, on_progress=None):
        self.events.append(f"bench:{kind}")
        if on_progress:
            on_progress(f"{kind} laeuft", None)
        if kind == self.fail_on_kind:
            raise RuntimeError("Messung abgestuerzt")
        return {"kind": kind, "status": "ok", "rows": [
            {"test": f"{kind}-row", "avg_ts": 10.0, "stddev_ts": 0.5}
        ]}

    def start_server(self, _model_path, _profile, _endpoint_cfg, _bench_cfg, _log_path):
        raise AssertionError("Endpoint ist in diesem Test deaktiviert")

    def stop_server(self, _proc):
        raise AssertionError("Endpoint ist in diesem Test deaktiviert")

    def wait_health(self, _base_url, _timeout_s, _headers=None, proc=None):  # noqa: ARG002
        return 0.0


@pytest.fixture
def suite_env(tmp_path: Path, monkeypatch):
    """Minimale, schnelle Umgebung fuer run_suite (keine echte Hardware/Reports)."""
    monkeypatch.setattr("llmbench.runner.collect_hardware", lambda _root: {"cpu": {"name": "TestCPU"}})
    monkeypatch.setattr("llmbench.runner.generate_run_html", lambda _s, _p: None)
    monkeypatch.setattr("llmbench.runner.generate_run_pdf", lambda _s, _p: None)
    monkeypatch.setattr("llmbench.runner.print_run_report", lambda _s, _c: None)

    model = tmp_path / "model.gguf"
    model.write_bytes(b"gguf")

    cfg = {
        "project": {"name": "T", "server_name": "srv", "output_dir": str(tmp_path / "out"),
                    "hash_models": False, "hash_tools": False},
        "tools": {"llama_bench": "llama-bench", "llama_server": "llama-server"},
        "benchmark": dict(repetitions=1, prompt_tokens=[512], generation_tokens=[128],
                          context_depths=[0], long_context_prompt_tokens=512,
                          long_context_generation_tokens=128, batch_size=2048, ubatch_size=512,
                          flash_attention="auto", cache_type_k="f16", cache_type_v="f16"),
        "endpoint": {"enabled": False},
        "soak": {"enabled": False},
        "models": [{"name": "M", "path": str(model),
                    "profiles": [{"name": "Full-GPU", "gpu_layers": -1}]}],
        "_config_dir": str(tmp_path),
    }
    return cfg


def _read_summary(run_dir: Path) -> dict:
    return json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))


def test_run_suite_wraps_kind_loop_in_begin_and_end_profile(suite_env, monkeypatch):
    backend = _RecordingBackend()
    monkeypatch.setattr("llmbench.runner.get_backend", lambda _cfg: backend)

    run_suite(suite_env, plain=True)

    assert backend.events == [
        "begin:Full-GPU", "bench:prompt", "bench:generation", "bench:long_context", "end",
    ]


def test_run_suite_calls_end_profile_even_when_a_benchmark_raises(suite_env, monkeypatch):
    backend = _RecordingBackend(fail_on_kind="generation")
    monkeypatch.setattr("llmbench.runner.get_backend", lambda _cfg: backend)

    run_dir = run_suite(suite_env, plain=True)

    assert backend.events[-1] == "end"
    summary = _read_summary(run_dir)
    benchmarks = summary["models"][0]["profiles"][0]["benchmarks"]
    assert benchmarks["generation"]["status"] == "failed"
    # Die folgende Testart laeuft trotzdem weiter.
    assert benchmarks["long_context"]["status"] == "ok"


def test_run_suite_records_backend_in_summary(suite_env, monkeypatch):
    monkeypatch.setattr("llmbench.runner.get_backend", lambda _cfg: _RecordingBackend())
    run_dir = run_suite(suite_env, plain=True)
    assert _read_summary(run_dir)["backend"] == "llama_cpp"


def test_run_suite_records_configured_backend_name(suite_env, monkeypatch):
    suite_env["tools"]["backend"] = "vllm"
    monkeypatch.setattr("llmbench.runner.get_backend", lambda _cfg: _RecordingBackend())
    run_dir = run_suite(suite_env, plain=True)
    assert _read_summary(run_dir)["backend"] == "vllm"


def test_run_suite_uses_llama_cpp_backend_when_backend_key_absent(suite_env, monkeypatch):
    """Regressionstest: ohne tools.backend muss weiterhin llama-bench laufen."""
    seen = {}

    def _fake_run_llama_bench(exe, model_path, bench_cfg, profile, kind, out_dir, on_progress=None):  # noqa: ARG001
        seen.setdefault("kinds", []).append(kind)
        seen["exe"] = exe
        return {"kind": kind, "status": "ok", "rows": [{"test": kind, "avg_ts": 1.0, "stddev_ts": 0.0}]}

    monkeypatch.setattr("llmbench.backends.llama_cpp.run_llama_bench", _fake_run_llama_bench)
    monkeypatch.setattr("llmbench.backends.llama_cpp.profile_vram_issue_for_path", lambda *_a: None)
    monkeypatch.setattr("llmbench.runner.probe_build", lambda _exe, with_hash=True: {"binary": {}})  # noqa: ARG005

    run_dir = run_suite(suite_env, plain=True)

    assert seen["kinds"] == list(BENCH_KINDS)
    assert seen["exe"] == "llama-bench"
    summary = _read_summary(run_dir)
    assert summary["backend"] == "llama_cpp"
    benchmarks = summary["models"][0]["profiles"][0]["benchmarks"]
    assert all(benchmarks[k]["status"] == "ok" for k in BENCH_KINDS)


def test_run_suite_reports_backend_start_failure_per_kind(suite_env, monkeypatch):
    """Scheitert begin_profile, darf nicht der ganze Lauf abbrechen."""

    class _BrokenBackend(_RecordingBackend):
        def begin_profile(self, _model_path, _profile, _bench_cfg, _out_dir):
            raise RuntimeError("Container startet nicht")

    monkeypatch.setattr("llmbench.runner.get_backend", lambda _cfg: _BrokenBackend())
    run_dir = run_suite(suite_env, plain=True)

    summary = _read_summary(run_dir)
    benchmarks = summary["models"][0]["profiles"][0]["benchmarks"]
    for kind in BENCH_KINDS:
        assert benchmarks[kind]["status"] == "failed"
        assert "Container startet nicht" in benchmarks[kind]["error"]
    assert any("Container startet nicht" in w for w in summary["warnings"])


def test_tool_info_records_image_digest_for_vllm(suite_env, monkeypatch):
    from llmbench.runner import _tool_info

    monkeypatch.setattr("llmbench.docker_backend.image_digest", lambda _i: "vllm@sha256:abc")
    suite_env["tools"]["backend"] = "vllm"
    suite_env["tools"]["vllm_image"] = "vllm/vllm-openai:v0.6.0"

    info = _tool_info(suite_env)
    assert info["vllm"] == {"image": "vllm/vllm-openai:v0.6.0", "digest": "vllm@sha256:abc"}
    # Ohne llama.cpp-Backend wird auch keine llama-bench-Datei gehasht.
    assert "llama_bench" not in info


def test_tool_info_keeps_llama_cpp_probe_by_default(suite_env, monkeypatch):
    from llmbench.runner import _tool_info

    monkeypatch.setattr("llmbench.runner.probe_build", lambda _exe, with_hash=True: {"binary": {"x": 1}})  # noqa: ARG005
    info = _tool_info(suite_env)
    assert "llama_bench" in info
    assert "vllm" not in info
