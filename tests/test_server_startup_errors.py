"""Ein sofort beendeter llama-server muss sofort und mit echtem Grund gemeldet werden.

Vorher wartete wait_health bis zu 300 s und meldete dann nur
"All connection attempts failed" - ohne Exitcode und ohne Server-Log.
"""

from __future__ import annotations

import socket
import sys
import time

import pytest

from llmbench import endpoint
from llmbench.utils import format_exit_code


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _cfgs(port: int) -> tuple[dict, dict, dict]:
    endpoint_cfg = {"base_url": f"http://127.0.0.1:{port}", "context_size": 512, "parallel_slots": 1}
    bench_cfg = {"batch_size": 512, "ubatch_size": 512}
    return {"name": "p", "gpu_layers": 0}, endpoint_cfg, bench_cfg


def test_exited_server_is_reported_immediately_with_log(tmp_path):
    # Echter Prozess, der sofort mit Fehler endet: "python -m <modell>" findet das Modul nicht -
    # genauso wie ein llama-server, der einen Parameter ablehnt oder abstuerzt.
    port = _free_port()
    profile, endpoint_cfg, bench_cfg = _cfgs(port)
    log = tmp_path / "server.log"
    proc, _command = endpoint.start_llama_server(
        sys.executable, "llmbench_no_such_module", profile, endpoint_cfg, bench_cfg, log
    )
    try:
        started = time.monotonic()
        with pytest.raises(RuntimeError) as info:
            endpoint.wait_health(endpoint_cfg["base_url"], 60, proc=proc)
        assert time.monotonic() - started < 15, "Absturz wurde nicht sofort erkannt"
        message = str(info.value)
        assert "llama-server hat sich beim Start beendet" in message
        assert "llmbench_no_such_module" in message  # Zeile aus dem Server-Log
        assert str(log) in message
    finally:
        endpoint.stop_llama_server(proc)


class _ExitedProc:
    def __init__(self, code: int, log_path: str | None = None):
        self._code = code
        self._llmbench_log_path = log_path

    def poll(self) -> int:
        return self._code


def test_windows_crash_code_is_readable(tmp_path):
    log = tmp_path / "gpu-server.log"
    log.write_text("load_backend: loaded CUDA backend\n\nggml_cuda_init: found 1 CUDA devices\n", encoding="utf-8")
    with pytest.raises(RuntimeError) as info:
        endpoint.wait_health("http://127.0.0.1:9", 30, proc=_ExitedProc(-1073741819, str(log)))
    message = str(info.value)
    assert "0xC0000005" in message
    assert "ggml_cuda_init: found 1 CUDA devices" in message


def test_running_process_does_not_trigger_early_exit():
    class Running:
        def poll(self):
            return None

    with pytest.raises(TimeoutError):
        endpoint.wait_health(f"http://127.0.0.1:{_free_port()}", 1.5, proc=Running())


def test_busy_port_is_rejected_before_start(tmp_path):
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        profile, endpoint_cfg, bench_cfg = _cfgs(port)
        with pytest.raises(RuntimeError, match=f"Port {port} ist bereits belegt"):
            endpoint.start_llama_server(sys.executable, "x", profile, endpoint_cfg, bench_cfg, tmp_path / "s.log")
    assert not (tmp_path / "s.log").exists(), "bei belegtem Port darf kein Server gestartet werden"


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (-1073741819, "0xC0000005 – Absturz (Zugriffsverletzung)"),
        (3221225781, "0xC0000135 – eine DLL fehlt"),
        (1, "Exitcode 1"),
        (None, "kein Exitcode"),
    ],
)
def test_format_exit_code(code, expected):
    assert format_exit_code(code) == expected


def test_exit_during_last_health_attempt_is_still_reported(monkeypatch):
    # Der letzte Request verbraucht die restliche Zeit, waehrend der Server stirbt:
    # trotzdem Exitcode statt generischem Timeout.
    class DiesLate:
        polls = 0

        def poll(self):
            self.polls += 1
            return None if self.polls == 1 else -1073741819

    async def slow_get(*_args, **_kwargs):
        import asyncio

        await asyncio.sleep(0.3)
        raise endpoint.httpx.ConnectError("All connection attempts failed")

    monkeypatch.setattr(endpoint.httpx.AsyncClient, "get", slow_get)
    with pytest.raises(RuntimeError, match="0xC0000005"):
        endpoint.wait_health("http://127.0.0.1:9", 0.2, proc=DiesLate())


def test_gpu_idle_wait_is_not_counted_as_benchmark_duration(monkeypatch, tmp_path):
    from llmbench import llama_bench

    class SlowStartMonitor:
        def __init__(self, *_args, **_kwargs):
            pass

        def start(self):
            time.sleep(0.4)  # steht fuer die Wartezeit auf eine ruhige GPU

        def stop(self):
            return {"sample_count": 0, "samples": []}

    monkeypatch.setattr(llama_bench, "ResourceMonitor", SlowStartMonitor)
    monkeypatch.setattr(llama_bench, "resolve_executable", lambda exe: exe)
    monkeypatch.setattr(llama_bench, "_execute", lambda *_a, **_k: ("", "boom", 1, False))
    result = llama_bench.run_llama_bench(
        "llama-bench", "m.gguf", {"repetitions": 1, "batch_size": 512, "ubatch_size": 512, "prompt_tokens": [512]},
        {"name": "p"}, "prompt", tmp_path,
    )
    assert result["duration_seconds"] < 0.3


def test_container_check_stops_health_wait_before_http_request(monkeypatch):
    async def unexpected_request(*_a, **_k):
        pytest.fail("Exited container should be detected before any HTTP request")

    def exited():
        raise RuntimeError("vLLM exited: Free memory on device is less than desired")

    monkeypatch.setattr(endpoint.httpx.AsyncClient, "get", unexpected_request)
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="Free memory on device"):
        endpoint.wait_health("http://127.0.0.1:9", 600, check_alive=exited)
    assert time.monotonic() - started < 1


def test_container_death_during_health_request_is_detected(monkeypatch):
    from types import SimpleNamespace

    polls = []
    requests = []
    clock = [0.0]
    # Client initialization must not consume this test's logical deadline.
    # Replace only endpoint's clock, leaving asyncio's scheduler clock intact.
    monkeypatch.setattr(endpoint, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def alive():
        polls.append(True)
        if len(polls) >= 3:
            raise RuntimeError("container exited while waiting")

    async def unavailable(*_a, **_k):
        requests.append(True)
        clock[0] = 1.0  # The request outlasts the deadline while the container dies.
        raise endpoint.httpx.ConnectError("not ready")

    async def no_sleep(_seconds):
        pass

    monkeypatch.setattr(endpoint.httpx.AsyncClient, "get", unavailable)
    monkeypatch.setattr(endpoint.asyncio, "sleep", no_sleep)
    with pytest.raises(RuntimeError, match="container exited while waiting"):
        endpoint.wait_health("http://127.0.0.1:9", 0.01, check_alive=alive)
    assert len(requests) == 1
    assert len(polls) == 3


@pytest.mark.parametrize("name,class_name", [("vllm", "VllmBackend"), ("tgi", "TgiBackend"), ("ollama", "OllamaBackend")])
def test_container_adapters_connect_health_check_to_actual_handle(monkeypatch, name, class_name):
    import importlib
    from types import SimpleNamespace

    module = importlib.import_module(f"llmbench.backends.{name}")
    seen = []
    monkeypatch.setattr(module.docker_backend, "check_container_alive", seen.append)

    def health(_url, _timeout, _headers, **kwargs):
        kwargs["check_alive"]()
        return 0.1

    monkeypatch.setattr(module, "wait_health", health)
    backend = getattr(module, class_name)("test-image", container_name="default-name")
    assert backend.wait_health("http://127.0.0.1:9", 600, proc=SimpleNamespace(name="actual-smoke-name")) == 0.1
    assert seen == ["actual-smoke-name"]


@pytest.mark.parametrize("name,class_name", [("vllm", "VllmBackend"), ("tgi", "TgiBackend"), ("ollama", "OllamaBackend")])
def test_external_endpoint_health_does_not_require_docker(monkeypatch, name, class_name):
    import importlib

    module = importlib.import_module(f"llmbench.backends.{name}")

    def unexpected(_name):
        pytest.fail("External endpoints must not inspect Docker")

    def health(_url, _timeout, _headers, **kwargs):
        assert kwargs["check_alive"] is None
        return 0.1

    monkeypatch.setattr(module.docker_backend, "check_container_alive", unexpected)
    monkeypatch.setattr(module, "wait_health", health)
    backend = getattr(module, class_name)("test-image")
    assert backend.wait_health("http://external.test", 10) == 0.1
