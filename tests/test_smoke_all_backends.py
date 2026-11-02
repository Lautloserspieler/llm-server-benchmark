"""Lifecycle checks for the manually launched backend smoke script."""

import importlib.util
from pathlib import Path


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "smoke_all_backends.py"
    spec = importlib.util.spec_from_file_location("smoke_all_backends", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_smallest_gguf_uses_local_file(tmp_path):
    script = _script()
    models = tmp_path / "models"
    models.mkdir()
    (models / "large.gguf").write_bytes(b"12345")
    (models / "tiny.gguf").write_bytes(b"1")
    cfg = {"models": [], "_config_dir": str(tmp_path)}
    assert script._smallest_gguf(cfg) == str(models / "tiny.gguf")


def test_missing_gguf_is_skipped(tmp_path, monkeypatch):
    script = _script()
    monkeypatch.setattr(script, "_prerequisite", lambda *_args: None)
    cfg = {
        "_config_dir": str(tmp_path),
        "tools": {"llama_server": "missing"},
        "models": [],
        "benchmark": {},
        "endpoint": {"base_url": "http://127.0.0.1:18080"},
    }
    row = script.run_one(cfg, "llama_cpp", tmp_path)
    assert row["status"] == "skipped"
    assert "GGUF" in row["detail"]


def test_run_one_stops_server_on_request_failure(tmp_path, monkeypatch):
    script = _script()
    stopped = []

    class Backend:
        def start_server(self, _model, _profile, endpoint, _bench, _log):
            endpoint["model"] = "gemma3:1b"
            return object(), "start"

        def wait_health(self, *_args):
            return 0

        def prepare_endpoint_config(self, endpoint):
            return {**endpoint, "api_style": "ollama_native"}

        def stop_server(self, proc):
            stopped.append(proc)

    async def fail(*_args, **_kwargs):
        raise RuntimeError("generation failed")

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

    monkeypatch.setattr(script, "_prerequisite", lambda *_args: None)
    monkeypatch.setattr(script, "_free_port", lambda *_args: True)
    monkeypatch.setattr(script, "get_backend", lambda *_args: Backend())
    monkeypatch.setattr(script, "sanity_completion_async", fail)
    monkeypatch.setattr(script.httpx, "AsyncClient", Client)
    cfg = {
        "_config_dir": str(tmp_path),
        "tools": {},
        "benchmark": {},
        "endpoint": {"base_url": "http://127.0.0.1:18080"},
    }
    row = script.run_one(cfg, "ollama", tmp_path)
    assert row["status"] == "failed"
    assert "generation failed" in row["detail"]
    assert len(stopped) == 1
