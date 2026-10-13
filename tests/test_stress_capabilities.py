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
    monkeypatch.setattr(ttft, "resolve_path", lambda path, _cfg: path)
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


def test_oom_stress_skips_unsupported_backend_before_backend_specific_work(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(oom, "load_config", lambda _path: _config())
    monkeypatch.setattr(oom, "get_backend", lambda _cfg: _UnsupportedOomBackend())
    monkeypatch.setattr(oom, "backend_name", lambda _cfg: "vllm")

    rc = asyncio.run(oom.run_oom_stress("ignored.yaml", tmp_path))

    assert rc == 2
    result = json.loads((tmp_path / "oom.json").read_text(encoding="utf-8"))
    assert result["reason"] == "backend_capability_missing"
    assert result["missing_capabilities"] == ["oom_probe"]
