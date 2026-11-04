"""Backend-Auswahl: zuerst waehlen, danach nur das gewaehlte Backend installieren."""

from __future__ import annotations

import contextlib

import yaml

from llmbench import backend_select, backend_setup


def _fake_env(monkeypatch, tmp_path, *, docker: bool, tty: bool, answer: bool = False, gpu: bool = True):
    installed: list[str] = []

    def fake_ensure(name, root, **_kwargs):
        installed.append(name)
        target = backend_setup.state_file(name, root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"image": "x"}', encoding="utf-8")
        return {"image": "x"}

    monkeypatch.setattr(backend_select.docker_backend, "docker_available", lambda: docker)
    monkeypatch.setattr(backend_select.docker_backend, "nvidia_runtime_available", lambda: gpu)
    monkeypatch.setattr(backend_select.backend_setup, "ensure_backend", fake_ensure)
    monkeypatch.setattr(backend_select, "_interactive", lambda: tty)
    monkeypatch.setattr(backend_select, "ask_yes_no", lambda *_args, **_kwargs: answer)
    monkeypatch.delenv("LLMBENCH_AUTO_INSTALL", raising=False)
    (tmp_path / "benchmark.yaml").write_text("project:\n  name: x\n", encoding="utf-8")
    return installed


def test_nothing_is_installed_without_terminal(monkeypatch, tmp_path):
    installed = _fake_env(monkeypatch, tmp_path, docker=True, tty=False)
    assert backend_select.select_backends(tmp_path, "benchmark.yaml") == 0
    assert installed == []


def test_declined_selected_backend_installs_nothing(monkeypatch, tmp_path):
    installed = _fake_env(monkeypatch, tmp_path, docker=True, tty=True, answer=False)
    monkeypatch.setattr(backend_select.console, "input", lambda *_args: "2")
    assert backend_select.select_backends(tmp_path, "benchmark.yaml") == 1
    assert installed == []


def test_confirmed_backend_is_installed(monkeypatch, tmp_path):
    installed = _fake_env(monkeypatch, tmp_path, docker=True, tty=True, answer=True)
    # Verfuegbar: 1 llama.cpp, 2 Ollama, 3 TGI, 4 vLLM.
    monkeypatch.setattr(backend_select.console, "input", lambda *_args: "4")
    backend_select.select_backends(tmp_path, "benchmark.yaml")
    assert installed == ["vllm"]
    cfg = yaml.safe_load((tmp_path / "benchmark.yaml").read_text(encoding="utf-8"))
    assert cfg["tools"]["backend"] == "vllm"


def test_confirmed_ollama_backend_is_installed(monkeypatch, tmp_path):
    installed = _fake_env(monkeypatch, tmp_path, docker=True, tty=True, answer=True)
    monkeypatch.setattr(backend_select.console, "input", lambda *_args: "2")
    backend_select.select_backends(tmp_path, "benchmark.yaml")
    assert installed == ["ollama"]
    cfg = yaml.safe_load((tmp_path / "benchmark.yaml").read_text(encoding="utf-8"))
    assert cfg["tools"]["backend"] == "ollama"



def test_choose_only_never_installs_missing_backends(monkeypatch, tmp_path):
    installed = _fake_env(monkeypatch, tmp_path, docker=True, tty=True, answer=True)
    monkeypatch.setattr(backend_select.console, "input", lambda *_args: "")
    backend_select.select_backends(tmp_path, "benchmark.yaml", install_missing=False)
    assert installed == []


def test_choose_only_can_select_already_installed_ollama(monkeypatch, tmp_path):
    installed = _fake_env(monkeypatch, tmp_path, docker=True, tty=True, answer=False)
    state = backend_setup.state_file("ollama", tmp_path)
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text('{"image": "ollama/ollama:latest"}', encoding="utf-8")
    monkeypatch.setattr(backend_select.console, "input", lambda *_args: "2")
    backend_select.select_backends(tmp_path, "benchmark.yaml", install_missing=False)
    assert installed == []
    cfg = yaml.safe_load((tmp_path / "benchmark.yaml").read_text(encoding="utf-8"))
    assert cfg["tools"]["backend"] == "ollama"

def test_without_docker_nothing_is_attempted(monkeypatch, tmp_path):
    installed = _fake_env(monkeypatch, tmp_path, docker=False, tty=True, answer=True)
    monkeypatch.setenv("LLMBENCH_AUTO_INSTALL", "1")
    assert backend_select.select_backends(tmp_path, "benchmark.yaml") == 0
    assert installed == []


def test_auto_install_env_installs_only_configured_backend(monkeypatch, tmp_path):
    installed = _fake_env(monkeypatch, tmp_path, docker=True, tty=False)
    (tmp_path / "benchmark.yaml").write_text("tools:\n  backend: ollama\n", encoding="utf-8")
    monkeypatch.setenv("LLMBENCH_AUTO_INSTALL", "1")
    backend_select.select_backends(tmp_path, "benchmark.yaml")
    assert installed == ["ollama"]


def test_nvidia_only_backends_are_not_offered_without_nvidia_gpu_in_docker(monkeypatch, tmp_path):
    installed = _fake_env(monkeypatch, tmp_path, docker=True, tty=True, answer=True, gpu=False)
    monkeypatch.setenv("LLMBENCH_AUTO_INSTALL", "1")
    monkeypatch.setattr(backend_select.console, "input", lambda *_args: "2")
    backend_select.select_backends(tmp_path, "benchmark.yaml")
    assert installed == ["ollama"]


def test_configured_but_missing_backend_is_reset(monkeypatch, tmp_path):
    # z. B. nach uninstall-backend: sonst wuerde der naechste Lauf das Image doch laden.
    _fake_env(monkeypatch, tmp_path, docker=False, tty=False)
    (tmp_path / "benchmark.yaml").write_text("tools:\n  backend: vllm\n", encoding="utf-8")
    backend_select.select_backends(tmp_path, "benchmark.yaml")
    cfg = yaml.safe_load((tmp_path / "benchmark.yaml").read_text(encoding="utf-8"))
    assert cfg["tools"]["backend"] == "llama_cpp"


def test_nvidia_runtime_detection(monkeypatch):
    import subprocess
    import types

    from llmbench import docker_backend

    monkeypatch.setattr(docker_backend, "docker_available", lambda: True)
    monkeypatch.setattr(docker_backend.sys, "platform", "linux")

    # Ohne Host-Treiber (kein nvidia-smi) gibt es keine GPU im Container.
    monkeypatch.setattr(docker_backend.shutil, "which", lambda _name: None)
    assert docker_backend.nvidia_runtime_available() is False

    monkeypatch.setattr(docker_backend.shutil, "which", lambda name: f"/usr/bin/{name}")
    for runtimes, expected in (('{"nvidia":{},"runc":{}}', True), ('{"runc":{}}', False)):
        result = types.SimpleNamespace(returncode=0, stdout=runtimes)
        monkeypatch.setattr(subprocess, "run", lambda *_a, _r=result, **_k: _r)
        assert docker_backend.nvidia_runtime_available() is expected



def test_ollama_download_size_matches_current_docker_image():
    assert backend_select.BACKEND_DOWNLOAD_GIB["ollama"] == 3.5


# --------------------------------------------- Setup-Abbruch / Neustart (Issue #123)


def _config_backend(tmp_path):
    cfg = yaml.safe_load((tmp_path / "benchmark.yaml").read_text(encoding="utf-8"))
    return (cfg.get("tools") or {}).get("backend")


def test_failed_install_keeps_the_previous_backend_selection(monkeypatch, tmp_path):
    _fake_env(monkeypatch, tmp_path, docker=True, tty=True, answer=True)
    (tmp_path / "benchmark.yaml").write_text("tools:\n  backend: llama_cpp\n", encoding="utf-8")
    monkeypatch.setattr(backend_select.console, "input", lambda *_args: "4")

    def failing(*_a, **_k):
        raise RuntimeError("pull failed: connection reset")

    monkeypatch.setattr(backend_select.backend_setup, "ensure_backend", failing)
    assert backend_select.select_backends(tmp_path, "benchmark.yaml") == 1
    assert _config_backend(tmp_path) == "llama_cpp"


def test_interrupted_install_keeps_selection_and_a_restart_completes_it(monkeypatch, tmp_path):
    installed = _fake_env(monkeypatch, tmp_path, docker=True, tty=True, answer=True)
    (tmp_path / "benchmark.yaml").write_text("tools:\n  backend: llama_cpp\n", encoding="utf-8")
    monkeypatch.setattr(backend_select.console, "input", lambda *_args: "2")
    working_install = backend_select.backend_setup.ensure_backend

    def interrupted(*_a, **_k):
        raise KeyboardInterrupt

    monkeypatch.setattr(backend_select.backend_setup, "ensure_backend", interrupted)
    with contextlib.suppress(KeyboardInterrupt):
        backend_select.select_backends(tmp_path, "benchmark.yaml")
    assert _config_backend(tmp_path) == "llama_cpp"
    assert not backend_setup.is_installed("ollama", tmp_path)

    # Restart: the installer works now; the selection is saved only after success.
    monkeypatch.setattr(backend_select.backend_setup, "ensure_backend", working_install)
    assert backend_select.select_backends(tmp_path, "benchmark.yaml") == 0
    assert installed == ["ollama"] and _config_backend(tmp_path) == "ollama"


def test_selection_is_kept_across_restarts_when_nothing_changes(monkeypatch, tmp_path):
    _fake_env(monkeypatch, tmp_path, docker=True, tty=True, answer=True)
    (tmp_path / "benchmark.yaml").write_text("tools:\n  backend: llama_cpp\n", encoding="utf-8")
    monkeypatch.setattr(backend_select.console, "input", lambda *_args: "")  # Enter = keep
    for _restart in range(3):
        assert backend_select.select_backends(tmp_path, "benchmark.yaml") == 0
    assert _config_backend(tmp_path) == "llama_cpp"
