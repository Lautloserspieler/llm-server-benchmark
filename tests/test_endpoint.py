import json
from pathlib import Path

import httpx
import pytest

from llmbench.endpoint import (
    _auth_headers,
    percentile,
    run_endpoint_load,
    start_llama_server,
    stop_llama_server,
)


# --------------------------------------------------------------------------- percentile

def test_percentile_empty_list_returns_none():
    assert percentile([], 0.5) is None


def test_percentile_single_value_returns_that_value():
    assert percentile([42.0], 0.95) == 42.0


def test_percentile_p50_of_sorted_values():
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.5) == 3.0


def test_percentile_interpolates_between_neighbours():
    # 4 sorted values -> p50 index = 1.5 -> interpolate between index 1 and 2
    assert percentile([10.0, 20.0, 30.0, 40.0], 0.5) == pytest.approx(25.0)


# --------------------------------------------------------------------------- auth headers

def test_auth_headers_empty_without_api_key():
    assert _auth_headers({}) == {}


def test_auth_headers_bearer_token_with_api_key():
    assert _auth_headers({"api_key": "secret"}) == {"Authorization": "Bearer secret"}


# --------------------------------------------------------------------------- start/stop server

def _endpoint_cfg(**overrides):
    cfg = {
        "base_url": "http://127.0.0.1:8099",
        "context_size": 32768,
        "parallel_slots": 8,
    }
    cfg.update(overrides)
    return cfg


def _bench_cfg(**overrides):
    cfg = {
        "batch_size": 2048,
        "ubatch_size": 512,
        "flash_attention": "auto",
        "cache_type_k": "f16",
        "cache_type_v": "f16",
    }
    cfg.update(overrides)
    return cfg


def test_start_llama_server_builds_expected_command(tmp_path: Path, monkeypatch):
    exe = tmp_path / "llama-server"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)

    captured = {}

    class _FakeProc:
        pid = 4242

    def _fake_popen(cmd, **_kwargs):
        captured["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr("llmbench.endpoint.subprocess.Popen", _fake_popen)

    log_path = tmp_path / "server.log"
    proc, printable = start_llama_server(
        str(exe), "model.gguf", {"gpu_layers": -1, "threads": "auto"},
        _endpoint_cfg(api_key="topsecret"), _bench_cfg(), log_path,
    )

    cmd = captured["cmd"]
    assert cmd[0] == str(exe.resolve())
    assert "-ngl" in cmd and cmd[cmd.index("-ngl") + 1] == "all"
    assert "--host" in cmd and cmd[cmd.index("--host") + 1] == "127.0.0.1"
    assert "--port" in cmd and cmd[cmd.index("--port") + 1] == "8099"
    assert "-t" not in cmd  # threads=auto is omitted
    assert "--api-key" in cmd and cmd[cmd.index("--api-key") + 1] == "topsecret"
    # The printable command must redact the API key.
    assert "topsecret" not in printable
    assert "***" in printable


def test_start_llama_server_passes_explicit_gpu_layers_and_threads(tmp_path: Path, monkeypatch):
    exe = tmp_path / "llama-server"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    captured = {}

    class _FakeProc:
        pid = 1

    def _fake_popen(cmd, **_kwargs):
        captured["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr("llmbench.endpoint.subprocess.Popen", _fake_popen)

    start_llama_server(
        str(exe), "model.gguf", {"gpu_layers": 20, "threads": 8},
        _endpoint_cfg(), _bench_cfg(), tmp_path / "server.log",
    )
    cmd = captured["cmd"]
    assert cmd[cmd.index("-ngl") + 1] == "20"
    assert cmd[cmd.index("-t") + 1] == "8"


def test_stop_llama_server_kills_process_and_closes_log(tmp_path: Path, monkeypatch):
    killed = {}
    monkeypatch.setattr("llmbench.endpoint.kill_process_tree", lambda proc: killed.setdefault("proc", proc))

    log_f = open(tmp_path / "log.txt", "w")  # noqa: SIM115

    class _FakeProc:
        pass

    proc = _FakeProc()
    proc._llmbench_log_file = log_f

    stop_llama_server(proc)
    assert killed["proc"] is proc
    assert log_f.closed


# --------------------------------------------------------------------------- endpoint load (SSE streaming)

def _sse_response_handler(tokens_per_request: int):
    def _handler(_request: httpx.Request) -> httpx.Response:
        lines = []
        for i in range(tokens_per_request):
            lines.append("data: " + json.dumps({"tokens": [i], "content": "x"}))
        lines.append(
            "data: " + json.dumps({"tokens": [], "content": "", "timings": {"predicted_n": tokens_per_request}})
        )
        body = "\n".join(lines) + "\n"
        return httpx.Response(200, text=body)

    return _handler


def test_run_endpoint_load_reports_tokens_and_success(tmp_path: Path, monkeypatch):
    transport = httpx.MockTransport(_sse_response_handler(tokens_per_request=5))

    class _PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("llmbench.endpoint.httpx.AsyncClient", _PatchedAsyncClient)
    monkeypatch.setattr("llmbench.endpoint.ResourceMonitor.start", lambda _self: None)
    monkeypatch.setattr("llmbench.endpoint.ResourceMonitor.stop", lambda _self: {"sample_count": 0})

    cfg = {
        "concurrency": [2],
        "requests_per_level": 2,
        "warmup_requests": 0,
        "max_tokens": 5,
        "prompt": "hello",
        "temperature": 0.0,
        "ignore_eos": True,
        "seed": 42,
    }
    result = run_endpoint_load("http://testserver", cfg, 0.5, tmp_path)

    assert result["status"] == "ok"
    level = result["levels"][0]
    assert level["successful"] == 2
    assert level["failed"] == 0
    assert level["total_output_tokens"] == 10
    assert level["short_responses"] == 0
    assert (tmp_path / "endpoint_load.json").exists()


def test_run_endpoint_load_flags_short_responses_without_ignore_eos(tmp_path: Path, monkeypatch):
    transport = httpx.MockTransport(_sse_response_handler(tokens_per_request=2))

    class _PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("llmbench.endpoint.httpx.AsyncClient", _PatchedAsyncClient)
    monkeypatch.setattr("llmbench.endpoint.ResourceMonitor.start", lambda _self: None)
    monkeypatch.setattr("llmbench.endpoint.ResourceMonitor.stop", lambda _self: {"sample_count": 0})

    cfg = {
        "concurrency": [1],
        "requests_per_level": 1,
        "warmup_requests": 0,
        "max_tokens": 50,
        "prompt": "hello",
        "temperature": 0.0,
        "ignore_eos": True,
        "seed": 42,
    }
    result = run_endpoint_load("http://testserver", cfg, 0.5, tmp_path)
    level = result["levels"][0]
    assert level["short_responses"] == 1
    assert "note" in level
