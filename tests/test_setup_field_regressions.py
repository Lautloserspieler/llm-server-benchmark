"""Regression checks for the AMD/Windows setup fixes."""
from __future__ import annotations

import json
import subprocess
import yaml

from llmbench import docker_backend, llama_cpp_setup


def test_docker_pull_streams_progress(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(docker_backend, "_require_docker", lambda: "docker")
    monkeypatch.setattr(docker_backend.subprocess, "run", fake_run)
    docker_backend.pull_image("ollama/ollama:test")
    assert calls[0][0] == ["docker", "pull", "ollama/ollama:test"]
    assert "capture_output" not in calls[0][1]
    assert calls[0][1]["timeout"] == docker_backend.PULL_TIMEOUT_SECONDS


def test_docker_pull_failure_is_reported(monkeypatch):
    import pytest

    monkeypatch.setattr(docker_backend, "_require_docker", lambda: "docker")
    monkeypatch.setattr(
        docker_backend.subprocess, "run",
        lambda cmd, **_kwargs: subprocess.CompletedProcess(cmd, 1),
    )
    with pytest.raises(RuntimeError, match="fehlgeschlagen"):
        docker_backend.pull_image("ollama/ollama:test")


def test_llama_existing_install_must_match_pinned_version(tmp_path, monkeypatch):
    llama_dir = tmp_path / "tools" / "llama.cpp"
    llama_dir.mkdir(parents=True)
    (llama_dir / "llama-bench").write_bytes(b"binary")
    (llama_dir / "llama-server").write_bytes(b"binary")
    state = llama_dir / ".llama-build.json"
    state.write_text(json.dumps({"tag": "b10000", "backend": "cpu"}), encoding="utf-8")
    monkeypatch.setattr(llama_cpp_setup, "probe", lambda _: (True, "OK"))
    assert not llama_cpp_setup._existing_install_ok(
        llama_dir, state, lambda _msg: None, desired_tag="b11748"
    )
    assert llama_cpp_setup._existing_install_ok(
        llama_dir, state, lambda _msg: None, desired_tag="b10000"
    )


def test_bootstrap_migrates_legacy_company_name(tmp_path):
    from llmbench.bootstrap import bootstrap_config

    root = tmp_path
    (root / "models").mkdir()
    (root / "benchmark.yaml").write_text(
        yaml.safe_dump({
            "project": {"name": "Firmenweiter LLM Server Benchmark"},
            "tools": {"backend": "ollama"},
            "models": [],
        }),
        encoding="utf-8",
    )
    bootstrap_config(root / "benchmark.yaml", root, root / "tools" / "llama.cpp", root / "models")
    cfg = yaml.safe_load((root / "benchmark.yaml").read_text(encoding="utf-8"))
    assert cfg["project"]["name"] == "LLM Server Benchmark"
