import subprocess
from pathlib import Path

import pytest

from llmbench import llama_flags
from llmbench.endpoint import start_llama_server
from llmbench.llama_bench import _base_args, _rejected_no_mmap

NEW_HELP = "-lm,   --load-mode MODE   model loading mode (default: auto)"
OLD_HELP = "--no-mmap   do not memory-map model\n--mlock   force system to keep model in RAM"


@pytest.fixture(autouse=True)
def _clear_cache():
    llama_flags.supports_load_mode.cache_clear()
    yield
    llama_flags.supports_load_mode.cache_clear()


def _fake_help(monkeypatch, text: str) -> None:
    monkeypatch.setattr(
        llama_flags,
        "run_capture",
        lambda cmd, **_kw: subprocess.CompletedProcess(cmd, 0, stdout=text, stderr=""),
    )


def test_new_build_uses_load_mode(monkeypatch):
    _fake_help(monkeypatch, NEW_HELP)
    assert llama_flags.load_flags("llama-server", no_mmap=True, mlock=False) == ["-lm", "none"]
    assert llama_flags.load_flags("llama-server", no_mmap=True, mlock=True) == ["-lm", "mlock"]
    assert llama_flags.load_flags("llama-server", no_mmap=False, mlock=False) == []


def test_old_build_keeps_legacy_flags(monkeypatch):
    _fake_help(monkeypatch, OLD_HELP)
    assert llama_flags.load_flags("llama-server", no_mmap=True, mlock=True) == ["--no-mmap", "--mlock"]


def test_help_failure_falls_back_to_legacy_flags(monkeypatch):
    def boom(*_args, **_kwargs):
        raise OSError("nicht startbar")

    monkeypatch.setattr(llama_flags, "run_capture", boom)
    assert llama_flags.load_flags("llama-server", no_mmap=True, mlock=False) == ["--no-mmap"]


def test_cpu_server_on_new_build_gets_load_mode_none(monkeypatch, tmp_path: Path):
    _fake_help(monkeypatch, NEW_HELP)
    captured = {}

    class FakeProc:
        pid = 1

    def fake_popen(cmd, **_kwargs):
        captured["cmd"] = cmd
        return FakeProc()

    monkeypatch.setattr("llmbench.endpoint.resolve_executable", lambda exe: exe)
    monkeypatch.setattr("llmbench.endpoint.port_in_use", lambda _h, _p: False)
    monkeypatch.setattr("llmbench.endpoint.subprocess.Popen", fake_popen)
    start_llama_server(
        "llama-server",
        "model.gguf",
        {"gpu_layers": 0},
        {"base_url": "http://127.0.0.1:8081", "context_size": 4096, "parallel_slots": 1},
        {"batch_size": 512, "ubatch_size": 512},
        tmp_path / "server.log",
    )
    cmd = captured["cmd"]
    assert "--no-mmap" not in cmd
    assert cmd[cmd.index("-lm") + 1] == "none"


def test_cpu_bench_on_new_build_gets_load_mode_none(monkeypatch):
    _fake_help(monkeypatch, NEW_HELP)
    args = _base_args("llama-bench", "m.gguf", {"repetitions": 1, "batch_size": 512, "ubatch_size": 512}, {"gpu_layers": 0})
    assert "--no-mmap" not in args
    assert args[args.index("-lm") + 1] == "none"


def test_server_rejection_of_no_mmap_is_detected():
    assert _rejected_no_mmap("", "error: invalid argument: --no-mmap")
    assert _rejected_no_mmap("", "error: invalid parameter for argument: --no-mmap")
    assert not _rejected_no_mmap("", "error: invalid argument: --foo")
