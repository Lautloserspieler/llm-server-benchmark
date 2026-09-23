"""Backend-Auswahl im Setup: fragt vor jedem Download, installiert nie ungefragt."""

from __future__ import annotations

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


def test_declined_question_installs_nothing(monkeypatch, tmp_path):
    installed = _fake_env(monkeypatch, tmp_path, docker=True, tty=True, answer=False)
    backend_select.select_backends(tmp_path, "benchmark.yaml")
    assert installed == []


def test_confirmed_backend_is_installed(monkeypatch, tmp_path):
    installed = _fake_env(monkeypatch, tmp_path, docker=True, tty=True, answer=True)
    monkeypatch.setattr(backend_select.console, "input", lambda *_args: "2")
    backend_select.select_backends(tmp_path, "benchmark.yaml")
    assert installed == ["vllm"]
    cfg = yaml.safe_load((tmp_path / "benchmark.yaml").read_text(encoding="utf-8"))
    assert cfg["tools"]["backend"] == "vllm"


def test_without_docker_nothing_is_attempted(monkeypatch, tmp_path):
    installed = _fake_env(monkeypatch, tmp_path, docker=False, tty=True, answer=True)
    monkeypatch.setenv("LLMBENCH_AUTO_INSTALL", "1")
    assert backend_select.select_backends(tmp_path, "benchmark.yaml") == 0
    assert installed == []


def test_auto_install_env_controls_questions(monkeypatch, tmp_path):
    installed = _fake_env(monkeypatch, tmp_path, docker=True, tty=False)
    monkeypatch.setenv("LLMBENCH_AUTO_INSTALL", "1")
    backend_select.select_backends(tmp_path, "benchmark.yaml")
    assert installed == ["vllm"]


def test_vllm_is_not_offered_without_nvidia_gpu_in_docker(monkeypatch, tmp_path):
    # vLLM startet immer mit --gpus; auf CPU-/AMD-Hosts waere der Download nutzlos.
    installed = _fake_env(monkeypatch, tmp_path, docker=True, tty=True, answer=True, gpu=False)
    monkeypatch.setenv("LLMBENCH_AUTO_INSTALL", "1")
    backend_select.select_backends(tmp_path, "benchmark.yaml")
    assert installed == []


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
