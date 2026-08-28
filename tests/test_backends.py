from pathlib import Path

from llmbench.backends.llama_cpp import LlamaCppBackend


def test_run_benchmark_delegates_to_run_llama_bench(monkeypatch, tmp_path: Path):
    calls = {}

    def _fake_run_llama_bench(exe, model_path, bench_cfg, profile, kind, out_dir, on_progress=None):  # noqa: ARG001
        calls["args"] = (exe, model_path, bench_cfg, profile, kind, out_dir)
        return {"status": "ok"}

    monkeypatch.setattr("llmbench.backends.llama_cpp.run_llama_bench", _fake_run_llama_bench)

    backend = LlamaCppBackend("llama-bench", "llama-server")
    result = backend.run_benchmark("model.gguf", {"name": "GPU"}, "generation", tmp_path, {"repetitions": 1})

    assert result == {"status": "ok"}
    assert calls["args"][0] == "llama-bench"
    assert calls["args"][1] == "model.gguf"
    assert calls["args"][4] == "generation"


def test_start_server_delegates_to_start_llama_server(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "llmbench.backends.llama_cpp.start_llama_server",
        lambda _exe, _model_path, _profile, _endpoint_cfg, _bench_cfg, _log_path: ("PROC", "cmd string"),
    )
    backend = LlamaCppBackend("llama-bench", "llama-server")
    proc, cmd = backend.start_server("model.gguf", {}, {}, {}, tmp_path / "log.txt")
    assert proc == "PROC"
    assert cmd == "cmd string"


def test_stop_server_delegates_to_stop_llama_server(monkeypatch):
    calls = {}
    monkeypatch.setattr("llmbench.backends.llama_cpp.stop_llama_server", lambda proc: calls.setdefault("proc", proc))
    backend = LlamaCppBackend("llama-bench", "llama-server")
    backend.stop_server("PROC")
    assert calls["proc"] == "PROC"


def test_wait_health_delegates_to_wait_health(monkeypatch):
    monkeypatch.setattr(
        "llmbench.backends.llama_cpp.wait_health", lambda _base_url, _timeout_s, _headers=None: 1.23
    )
    backend = LlamaCppBackend("llama-bench", "llama-server")
    assert backend.wait_health("http://x", 5.0) == 1.23
