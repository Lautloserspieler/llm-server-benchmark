import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from llmbench.soak import _summarize_load, find_soak_profiles, run_soak_test


# --------------------------------------------------------------------------- find_soak_profiles

def _model(profiles):
    return {"name": "M", "profiles": profiles}


def test_find_soak_profiles_auto_detects_by_gpu_layers():
    model = _model([
        {"name": "Full-GPU", "gpu_layers": -1},
        {"name": "CPU-Only", "gpu_layers": 0},
    ])
    cpu, gpu = find_soak_profiles(model, {})
    assert cpu["name"] == "CPU-Only"
    assert gpu["name"] == "Full-GPU"


def test_find_soak_profiles_prefers_explicit_names():
    model = _model([
        {"name": "Full-GPU", "gpu_layers": -1},
        {"name": "CPU-Only", "gpu_layers": 0},
        {"name": "Hybrid", "gpu_layers": 20},
    ])
    cpu, gpu = find_soak_profiles(model, {"gpu_profile": "Hybrid"})
    assert cpu["name"] == "CPU-Only"
    assert gpu["name"] == "Hybrid"


def test_find_soak_profiles_returns_none_when_no_cpu_profile_exists():
    model = _model([{"name": "Full-GPU", "gpu_layers": -1}])
    cpu, gpu = find_soak_profiles(model, {})
    assert cpu is None
    assert gpu["name"] == "Full-GPU"


def test_find_soak_profiles_handles_model_without_profiles():
    assert find_soak_profiles({"name": "M"}, {}) == (None, None)


# --------------------------------------------------------------------------- _summarize_load

def test_summarize_load_reports_zero_successful_without_a_note_crash():
    summary = _summarize_load([{"ok": False, "error": "boom"}], duration_seconds=60, throttle_drop_fraction=0.15)
    assert summary["successful"] == 0
    assert summary["failed"] == 1
    assert summary["avg_tps"] is None
    assert summary["throttling_suspected"] is False
    assert "note" in summary


def _result(elapsed, tps):
    return {"ok": True, "elapsed_seconds": elapsed, "output_tokens": 100, "tps": tps}


def test_summarize_load_detects_throttling_from_tps_drop():
    duration = 100.0
    results = [_result(20, 100.0), _result(25, 100.0), _result(90, 50.0), _result(95, 50.0)]
    summary = _summarize_load(results, duration, throttle_drop_fraction=0.15)
    assert summary["early_window_avg_tps"] == pytest.approx(100.0)
    assert summary["late_window_avg_tps"] == pytest.approx(50.0)
    assert summary["tps_drop_fraction"] == pytest.approx(0.5)
    assert summary["throttling_suspected"] is True
    assert "Throttling" in summary["note"]


def test_summarize_load_stable_tps_is_not_flagged_as_throttling():
    duration = 100.0
    results = [_result(20, 100.0), _result(90, 98.0)]
    summary = _summarize_load(results, duration, throttle_drop_fraction=0.15)
    assert summary["throttling_suspected"] is False


# --------------------------------------------------------------------------- run_soak_test

class _FakeBackend:
    def __init__(self, fail_health=False):
        self.started: list[tuple[str, str]] = []
        self.stopped: list[int] = []
        self._fail_health = fail_health
        self._next_pid = 1000

    def start_server(self, _model_path, profile, endpoint_cfg, _bench_cfg, _log_path):
        self._next_pid += 1
        self.started.append((profile.get("name"), endpoint_cfg["base_url"]))
        proc = SimpleNamespace(pid=self._next_pid)
        return proc, f"fake-cmd --port {endpoint_cfg['base_url']}"

    def wait_health(self, base_url, _timeout_s, _headers=None):
        if self._fail_health:
            raise TimeoutError(f"{base_url} wurde nicht bereit")
        return 0.05

    def stop_server(self, proc):
        self.stopped.append(proc.pid)


def _ok_response_handler(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"content": "hallo welt", "timings": {"predicted_n": 8}})


def _patched_async_client(monkeypatch, transport):
    class _PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("llmbench.soak.httpx.AsyncClient", _PatchedAsyncClient)


def _soak_cfg(**overrides):
    cfg = {
        "host": "127.0.0.1",
        "cpu_port": 8090,
        "gpu_port": 8091,
        "sample_interval_seconds": 0.1,
        "concurrency": 1,
        "max_tokens": 8,
        "temperature": 0.0,
        "seed": 42,
        "context_size": 2048,
        "startup_timeout_seconds": 5,
        "throttle_tps_drop_fraction": 0.15,
        "prompt": "hallo",
    }
    cfg.update(overrides)
    return cfg


def test_run_soak_test_drives_both_servers_and_reports_status_ok(tmp_path: Path, monkeypatch):
    _patched_async_client(monkeypatch, httpx.MockTransport(_ok_response_handler))
    backend = _FakeBackend()

    result = run_soak_test(
        backend, "model.gguf",
        {"name": "CPU-Only", "gpu_layers": 0}, {"name": "Full-GPU", "gpu_layers": -1},
        _soak_cfg(), {"batch_size": 2048}, tmp_path, duration_seconds=2, label="short",
    )

    assert result["status"] == "ok"
    assert result["cpu"]["successful"] > 0
    assert result["gpu"]["successful"] > 0
    assert {name for name, _url in backend.started} == {"CPU-Only", "Full-GPU"}
    assert len(backend.stopped) == 2
    assert (tmp_path / "soak_short" / "raw_soak.json").exists()
    saved = json.loads((tmp_path / "soak_short" / "raw_soak.json").read_text())
    assert saved["telemetry"]["sample_count"] >= 0


def test_run_soak_test_stops_servers_and_reports_failure_when_health_check_fails(tmp_path: Path, monkeypatch):
    _patched_async_client(monkeypatch, httpx.MockTransport(_ok_response_handler))
    backend = _FakeBackend(fail_health=True)

    result = run_soak_test(
        backend, "model.gguf",
        {"name": "CPU-Only", "gpu_layers": 0}, {"name": "Full-GPU", "gpu_layers": -1},
        _soak_cfg(), {"batch_size": 2048}, tmp_path, duration_seconds=1, label="short",
    )

    assert result["status"] == "failed"
    assert "error" in result
    # Both servers were started before the health check failed, so both must be stopped.
    assert len(backend.stopped) == len(backend.started)


def test_run_soak_test_invokes_on_tick_with_remaining_time(tmp_path: Path, monkeypatch):
    _patched_async_client(monkeypatch, httpx.MockTransport(_ok_response_handler))
    backend = _FakeBackend()
    ticks: list[float] = []

    run_soak_test(
        backend, "model.gguf",
        {"name": "CPU-Only", "gpu_layers": 0}, {"name": "Full-GPU", "gpu_layers": -1},
        _soak_cfg(sample_interval_seconds=0.1), {"batch_size": 2048}, tmp_path,
        duration_seconds=2, label="short", on_tick=lambda remaining, _sample: ticks.append(remaining),
    )

    assert len(ticks) >= 1
