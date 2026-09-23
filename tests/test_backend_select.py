"""Backend-Auswahl im Setup: fragt vor jedem Download, installiert nie ungefragt."""

from __future__ import annotations

import yaml

from llmbench import backend_select, backend_setup


def _fake_env(monkeypatch, tmp_path, *, docker: bool, tty: bool, answer: bool = False):
    installed: list[str] = []

    def fake_ensure(name, root, **_kwargs):
        installed.append(name)
        target = backend_setup.state_file(name, root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"image": "x"}', encoding="utf-8")
        return {"image": "x"}

    monkeypatch.setattr(backend_select.docker_backend, "docker_available", lambda: docker)
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
