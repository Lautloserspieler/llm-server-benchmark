import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from llmbench.backends.capabilities import BackendCapabilities
from llmbench.stress import oom, ttft


class _FakeTtftBackend:
    capabilities = BackendCapabilities(endpoint=True, concurrency=True)

    def __init__(self):
        self.stopped = False

    def supports(self, name: str) -> bool:
        return self.capabilities.supports(name)

    def prepare_endpoint_config(self, endpoint_cfg):
        return dict(endpoint_cfg)

    def start_server(self, *_args, **_kwargs):
        return SimpleNamespace(pid=1234), "fake server"

    def wait_health(self, *_args, **_kwargs):
        return 0.25

    def stop_server(self, _proc):
        self.stopped = True


class _UnsupportedOomBackend:
    capabilities = BackendCapabilities(endpoint=True, oom_probe=False)

    def supports(self, name: str) -> bool:
        return self.capabilities.supports(name)


def _config() -> dict:
    return {
        "project": {"output_dir": "results"},
        "tools": {
            "backend": "vllm",
            "llama_bench": "llama-bench",
            "llama_server": "llama-server",
        },
        "benchmark": {"resource_sample_interval": 0.5, "context_depths": [4096]},
        "endpoint": {
            "base_url": "http://127.0.0.1:8000",
            "concurrency": [1, 2],
            "requests_per_level": 2,
            "parallel_slots": 2,
            "startup_timeout_seconds": 1,
        },
        "models": [
            {
                "name": "M",
                "path": "model",
                "profiles": [{"name": "GPU", "gpu_layers": -1}],
            }
        ],
        "_config_dir": ".",
    }


def test_ttft_stress_uses_configured_backend_factory(monkeypatch, tmp_path: Path):
    backend = _FakeTtftBackend()
    monkeypatch.setattr(ttft, "load_config", lambda _path: _config())
    monkeypatch.setattr(ttft, "get_backend", lambda _cfg: backend)
    monkeypatch.setattr(ttft, "backend_name", lambda _cfg: "fake")
    monkeypatch.setattr(
        ttft,
        "run_endpoint_load",
        lambda *_args, **_kwargs: {
            "status": "ok",
            "levels": [
                {
                    "concurrency": 1,
                    "ttft_p50_seconds": 0.1,
                    "ttft_p95_seconds": 0.2,
                    "system_tps": 10,
                }
            ],
        },
    )

    rc = ttft.run_ttft_stress("ignored.yaml", tmp_path)

    assert rc == 0
    assert backend.stopped is True
    result = json.loads((tmp_path / "ttft.json").read_text(encoding="utf-8"))
    assert result["backend"] == "fake"
    assert result["server_command"] == "fake server"


def test_ttft_stress_cpu_selection_reaches_server(monkeypatch, tmp_path: Path):
    cfg = _config()
    cfg["models"][0]["profiles"].append({"name": "CPU", "gpu_layers": 0, "ollama_num_gpu": 0})
    selected = []
    backend = _FakeTtftBackend()
    backend.start_server = lambda _path, profile, *_args: (selected.append(profile) or SimpleNamespace(pid=1), "cmd")
    monkeypatch.setattr(ttft, "load_config", lambda _path: cfg)
    monkeypatch.setattr(ttft, "get_backend", lambda _cfg: backend)
    monkeypatch.setattr(ttft, "backend_name", lambda _cfg: "ollama")
    monkeypatch.setattr(ttft, "run_endpoint_load", lambda *_a, **_k: {"levels": []})

    assert ttft.run_ttft_stress("ignored.yaml", tmp_path, hardware_target="cpu") == 0
    assert selected[0]["ollama_num_gpu"] == 0


def test_ttft_stress_selection_overrides_default_levels(monkeypatch, tmp_path: Path):
    selected = []
    backend = _FakeTtftBackend()
    monkeypatch.setattr(ttft, "load_config", lambda _path: _config())
    monkeypatch.setattr(ttft, "get_backend", lambda _cfg: backend)
    monkeypatch.setattr(ttft, "backend_name", lambda _cfg: "fake")
    monkeypatch.setattr(
        ttft, "run_endpoint_load",
        lambda _url, cfg, *_args, **_kwargs: (selected.append(dict(cfg)) or {"levels": []}),
    )

    assert ttft.run_ttft_stress("ignored.yaml", tmp_path, concurrency=[4, 1, 4]) == 0
    assert selected[0]["concurrency"] == [1, 4]
    assert selected[0]["requests_per_level"] >= 8


def test_oom_stress_cpu_selection_reaches_server(monkeypatch, tmp_path: Path):
    cfg = _config()
    cfg["stress"] = {"oom_contexts": [2048]}
    cfg["models"][0]["profiles"].append({"name": "CPU", "gpu_layers": 0, "ollama_num_gpu": 0})
    selected = []

    class Backend(_FakeTtftBackend):
        capabilities = BackendCapabilities(endpoint=True, oom_probe=True)

        def start_server(self, _path, profile, *_args):
            selected.append(profile)
            return SimpleNamespace(pid=1), "cmd"

        async def probe_context(self, _url, level, _cfg):
            return {"ok": True, "actual_prompt_tokens": level}

    monkeypatch.setattr(oom, "load_config", lambda _path: cfg)
    monkeypatch.setattr(oom, "get_backend", lambda _cfg: Backend())
    monkeypatch.setattr(oom, "backend_name", lambda _cfg: "ollama")

    assert asyncio.run(oom.run_oom_stress("ignored.yaml", tmp_path, hardware_target="cpu")) == 0
    assert selected[0]["ollama_num_gpu"] == 0


def test_oom_stress_skips_unsupported_backend_before_backend_specific_work(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(oom, "load_config", lambda _path: _config())
    monkeypatch.setattr(oom, "get_backend", lambda _cfg: _UnsupportedOomBackend())
    monkeypatch.setattr(oom, "backend_name", lambda _cfg: "vllm")

    rc = asyncio.run(oom.run_oom_stress("ignored.yaml", tmp_path))

    assert rc == 2
    result = json.loads((tmp_path / "oom.json").read_text(encoding="utf-8"))
    assert result["reason"] == "backend_capability_missing"
    assert result["missing_capabilities"] == ["oom_probe"]


def test_resolve_model_ref_checks_relative_local_path_against_config_dir(tmp_path, monkeypatch):
    from llmbench.stress.base import resolve_model_ref

    cfg_dir = tmp_path / "cfg"
    (cfg_dir / "models").mkdir(parents=True)
    (cfg_dir / "models" / "m.gguf").write_bytes(b"x")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # CWD differs from the config directory
    cfg = {"_config_dir": str(cfg_dir)}

    assert resolve_model_ref("models/m.gguf", cfg, "vllm") == str((cfg_dir / "models" / "m.gguf").resolve())
    # a hub reference that exists nowhere stays a reference
    assert resolve_model_ref("org/Model", cfg, "vllm") == "org/Model"
    assert resolve_model_ref("llama3.2:3b", cfg, "ollama") == "llama3.2:3b"
    # llama.cpp always resolves to a file path
    assert resolve_model_ref("org/Model", cfg, "llama_cpp") == str((cfg_dir / "org" / "Model").resolve())


def test_runner_model_meta_uses_same_reference_rule(tmp_path, monkeypatch):
    from llmbench.runner import _model_meta

    cfg_dir = tmp_path / "cfg"
    (cfg_dir / "models").mkdir(parents=True)
    (cfg_dir / "models" / "m.gguf").write_bytes(b"x")
    monkeypatch.chdir(tmp_path)
    cfg = {"_config_dir": str(cfg_dir), "project": {"hash_models": False}, "endpoint": {}, "tools": {"backend": "vllm"}}
    meta = _model_meta({"name": "M", "path": "models/m.gguf"}, cfg)
    assert meta["path"] == str((cfg_dir / "models" / "m.gguf").resolve())
