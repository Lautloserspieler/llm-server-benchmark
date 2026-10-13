from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import yaml

from llmbench.backends.capabilities import BackendCapabilities
from llmbench.bootstrap import bootstrap_config, discover_models, model_shards
from llmbench.download import verify_suite
from llmbench.stress.quant import discover_quant_groups


def _write_config(path: Path, models: list[dict], context_depths: list[int] | None = None) -> None:
    data = {
        "tools": {"llama_bench": "bench", "llama_server": "server"},
        "benchmark": {
            "repetitions": 1,
            "prompt_tokens": [512],
            "generation_tokens": [128],
            "context_depths": context_depths or [4096],
        },
        "endpoint": {
            "enabled": True,
            "base_url": "http://127.0.0.1:8080",
            "context_size": 8192,
            "parallel_slots": 2,
            "concurrency": [1, 2],
            "requests_per_level": 2,
            "warmup_requests": 0,
            "max_tokens": 16,
            "timeout_seconds": 10,
            "startup_timeout_seconds": 10,
        },
        "models": models,
    }
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_sharded_gguf_is_one_logical_model_only_when_complete(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    for index in (1, 2, 3):
        (models / f"huge-Q4_K_M-{index:05d}-of-00003.gguf").write_bytes(bytes([index]))

    found = discover_models(tmp_path, models)
    assert [path.name for path in found] == ["huge-Q4_K_M-00001-of-00003.gguf"]
    assert len(model_shards(found[0])) == 3

    (models / "huge-Q4_K_M-00003-of-00003.gguf").unlink()
    assert discover_models(tmp_path, models) == []


def test_bootstrap_removes_old_followup_shards(tmp_path: Path) -> None:
    models = tmp_path / "models"
    tools = tmp_path / "tools" / "llama.cpp"
    models.mkdir()
    tools.mkdir(parents=True)
    (tools / "llama-bench.exe").write_bytes(b"")
    (tools / "llama-server.exe").write_bytes(b"")
    for index in (1, 2):
        (models / f"split-Q4_K_M-{index:05d}-of-00002.gguf").write_bytes(bytes([index]))

    config = tmp_path / "benchmark.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "models": [
                    {"name": "wrong1", "path": "models/split-Q4_K_M-00001-of-00002.gguf", "profiles": [{"name": "GPU", "gpu_layers": -1}]},
                    {"name": "wrong2", "path": "models/split-Q4_K_M-00002-of-00002.gguf", "profiles": [{"name": "GPU", "gpu_layers": -1}]},
                ]
            }
        ),
        encoding="utf-8",
    )

    result = bootstrap_config(config, tmp_path, tools, models)
    cfg = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert len(cfg["models"]) == 1
    assert cfg["models"][0]["path"].endswith("00001-of-00002.gguf")
    assert any("Folge-Shard" in warning for warning in result["warnings"])


def test_verify_suite_requires_complete_manifest_model(tmp_path: Path, monkeypatch) -> None:
    import llmbench.download as download

    monkeypatch.setattr(
        download,
        "MODELS",
        {
            "small": {
                "Fake": {
                    "repo_id": "x/y",
                    "pattern": ["*Q4_K_M*.gguf"],
                    "filename_hint": "fake-model",
                    "estimated_gib": 1.0,
                }
            }
        },
    )
    assert verify_suite(tmp_path, "small") == (False, ["Fake"])
    (tmp_path / "fake-model-Q4_K_M.gguf").write_bytes(b"ok")
    assert verify_suite(tmp_path, "small") == (True, [])


def test_download_raises_if_snapshot_finishes_without_model(tmp_path: Path, monkeypatch) -> None:
    import llmbench.download as download

    monkeypatch.setattr(
        download,
        "MODELS",
        {
            "small": {
                "Fake": {
                    "repo_id": "x/y",
                    "pattern": ["*Q4_K_M*.gguf"],
                    "filename_hint": "fake-model",
                    "estimated_gib": 1.0,
                }
            }
        },
    )
    monkeypatch.setattr(download, "snapshot_download", lambda **_kwargs: str(tmp_path))
    with pytest.raises(RuntimeError, match="unvollstaendig"):
        download.download_models(tmp_path, "small")


def test_quant_discovery_only_groups_same_base_model(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "same-model-Q4_K_M.gguf").write_bytes(b"4")
    (models / "same-model-Q8_0.gguf").write_bytes(b"8")
    (models / "other-model-Q4_K_M.gguf").write_bytes(b"x")

    groups = discover_quant_groups(tmp_path, models)
    assert list(groups) == ["same-model"]
    assert set(groups["same-model"]) == {"Q4_K_M", "Q8_0"}


def test_multitenant_uses_two_backend_paths_and_separate_result_dirs(tmp_path: Path, monkeypatch) -> None:
    import llmbench.stress.multitenant as module

    config = tmp_path / "benchmark.yaml"
    _write_config(
        config,
        [
            {"name": "A", "path": "A.gguf", "profiles": [{"name": "GPU", "gpu_layers": -1}]},
            {"name": "B", "path": "B.gguf", "profiles": [{"name": "GPU", "gpu_layers": -1}]},
        ],
    )

    calls: dict = {"factory": False, "out_dirs": []}

    class Proc:
        def __init__(self, pid: int):
            self.pid = pid

    class Backend:
        capabilities = BackendCapabilities(endpoint=True, concurrency=True, multi_model=True)

        def __init__(self):
            self.i = 0

        def supports(self, capability: str) -> bool:
            return self.capabilities.supports(capability)

        def start_server(self, *_args):
            self.i += 1
            return Proc(self.i), f"cmd{self.i}"

        def wait_health(self, *_args, **_kwargs):
            return 0.1

        def stop_server(self, _proc):
            return None

    backend = Backend()

    def fake_get_backend(_cfg):
        calls["factory"] = True
        return backend

    async def fake_load(_base, _cfg, _interval, out_dir, target_pid=None, target_pids=None):
        calls["out_dirs"].append(Path(out_dir))
        assert set(target_pids or []) == {1, 2}
        return {"status": "ok", "levels": [{"system_tps": float(target_pid or 1)}]}

    models = [
        {"name": "A", "path": "A.gguf", "profiles": [{"name": "GPU", "gpu_layers": -1}]},
        {"name": "B", "path": "B.gguf", "profiles": [{"name": "GPU", "gpu_layers": -1}]},
    ]
    pair = (
        {"model": models[0], "profile": models[0]["profiles"][0], "path": "A.gguf", "size_bytes": 1},
        {"model": models[1], "profile": models[1]["profiles"][0], "path": "B.gguf", "size_bytes": 1},
    )

    monkeypatch.setattr(module, "get_backend", fake_get_backend)
    monkeypatch.setattr(module, "backend_name", lambda _cfg: "fake")
    monkeypatch.setattr(module, "_select_multitenant_pair", lambda _cfg: (pair, None))
    monkeypatch.setattr(module, "_run_endpoint_load_async", fake_load)

    rc = asyncio.run(module.run_multitenant(str(config), tmp_path / "out"))
    assert rc == 0
    assert calls["factory"] is True
    assert calls["out_dirs"][0] != calls["out_dirs"][1]
    assert (tmp_path / "out" / "multitenant.json").exists()


def test_oom_stress_initializes_backend_correctly_and_restarts_per_level(tmp_path: Path, monkeypatch) -> None:
    import llmbench.stress.oom as module

    config = tmp_path / "benchmark.yaml"
    _write_config(
        config,
        [{"name": "A", "path": "A.gguf", "profiles": [{"name": "GPU", "gpu_layers": -1}]}],
        context_depths=[4096, 8192],
    )
    calls = {"factory": False, "starts": 0, "stops": 0}

    class Proc:
        pid = 1

    class Backend:
        capabilities = BackendCapabilities(endpoint=True, oom_probe=True)

        def supports(self, capability: str) -> bool:
            return self.capabilities.supports(capability)

        def start_server(self, *_args):
            calls["starts"] += 1
            return Proc(), "cmd"

        def wait_health(self, *_args, **_kwargs):
            return 0.1

        async def probe_context(self, _url, prompt_target, _cfg):
            return {"ok": True, "actual_prompt_tokens": prompt_target, "duration_seconds": 0.1}

        def stop_server(self, _proc):
            calls["stops"] += 1

    backend = Backend()

    def fake_get_backend(_cfg):
        calls["factory"] = True
        return backend

    monkeypatch.setattr(module, "get_backend", fake_get_backend)
    monkeypatch.setattr(module, "backend_name", lambda _cfg: "fake")
    monkeypatch.setattr(module.asyncio, "sleep", lambda _seconds: _completed_sleep())

    rc = asyncio.run(module.run_oom_stress(str(config), tmp_path / "oom"))
    assert rc == 0
    assert calls["factory"] is True
    assert calls["starts"] == calls["stops"] == len(module.DEFAULT_OOM_CONTEXTS)
    data = json.loads((tmp_path / "oom" / "oom.json").read_text(encoding="utf-8"))
    assert data["max_stable_prompt_tokens"] == module.DEFAULT_OOM_CONTEXTS[-1]


async def _completed_sleep() -> None:
    return None


def test_ttft_stress_is_real_endpoint_test(tmp_path: Path, monkeypatch) -> None:
    import llmbench.stress.ttft as module

    config = tmp_path / "benchmark.yaml"
    _write_config(
        config,
        [{"name": "A", "path": "A.gguf", "profiles": [{"name": "GPU", "gpu_layers": -1}]}],
    )
    calls = {"factory": False, "load": False}

    class Proc:
        pid = 123

    class Backend:
        capabilities = BackendCapabilities(endpoint=True, concurrency=True)

        def supports(self, capability: str) -> bool:
            return self.capabilities.supports(capability)

        def start_server(self, *_args):
            return Proc(), "cmd"

        def wait_health(self, *_args, **_kwargs):
            return 0.1

        def stop_server(self, _proc):
            return None

    backend = Backend()

    def fake_get_backend(_cfg):
        calls["factory"] = True
        return backend

    def fake_load(*_args, **_kwargs):
        calls["load"] = True
        return {
            "status": "ok",
            "levels": [
                {"concurrency": 1, "ttft_p50_seconds": 0.1, "ttft_p95_seconds": 0.2, "system_tps": 10}
            ],
        }

    monkeypatch.setattr(module, "get_backend", fake_get_backend)
    monkeypatch.setattr(module, "backend_name", lambda _cfg: "fake")
    monkeypatch.setattr(module, "run_endpoint_load", fake_load)

    rc = module.run_ttft_stress(str(config), tmp_path / "ttft")
    assert rc == 0
    assert calls["factory"] is True
    assert calls["load"] is True
    assert (tmp_path / "ttft" / "ttft.json").exists()
