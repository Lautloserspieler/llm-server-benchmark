"""Lifecycle checks for the manually launched backend smoke script."""

import importlib.util
from pathlib import Path


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "smoke_all_backends.py"
    spec = importlib.util.spec_from_file_location("smoke_all_backends", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_smallest_catalog_gguf_reuses_download(tmp_path, monkeypatch):
    script = _script()
    models = tmp_path / "models"
    models.mkdir()
    (models / "tiny.gguf").write_bytes(b"1")
    selected = []
    monkeypatch.setattr(script, "get_catalog_models", lambda: {
        "large": {"estimated_gib": 10.0},
        "small": {"estimated_gib": 6.0},
    })
    def find(_root, model_cfg):
        selected.append(model_cfg["estimated_gib"])
        return models / "tiny.gguf"
    monkeypatch.setattr(script, "find_downloaded_model", find)
    monkeypatch.setattr(script, "download_models", lambda *_args, **_kwargs: None)
    assert script._smallest_catalog_gguf({"_config_dir": str(tmp_path)}) == str(models / "tiny.gguf")
    assert selected == [6.0]


def test_smallest_catalog_gguf_downloads_only_selected_model(tmp_path, monkeypatch):
    script = _script()
    model = tmp_path / "models" / "small.gguf"
    monkeypatch.setattr(script, "get_catalog_models", lambda: {
        "large": {"estimated_gib": 10.0},
        "small": {"estimated_gib": 6.0},
    })
    monkeypatch.setattr(script, "find_downloaded_model", lambda *_args: model if model.exists() else None)
    def download(_root, *, model_names):
        assert model_names == ["small"]
        model.parent.mkdir(exist_ok=True)
        model.write_bytes(b"GGUF")
    monkeypatch.setattr(script, "download_models", download)
    assert script._smallest_catalog_gguf({"_config_dir": str(tmp_path)}) == str(model)


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
