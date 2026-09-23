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
