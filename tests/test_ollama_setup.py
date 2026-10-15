from __future__ import annotations

from pathlib import Path

import pytest

from llmbench import ollama_setup


class _Proc:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode


def _fake_backend(monkeypatch, tmp_path: Path):
    calls: list[tuple] = []

    monkeypatch.setattr(
        ollama_setup.backend_setup,
        "ensure_backend",
        lambda *_a, **_k: {
            "image": "ollama/ollama:latest",
            "volume": "llmbench-ollama-cache",
        },
    )
    monkeypatch.setattr(
        ollama_setup.docker_backend,
        "stop_container",
        lambda name, **_k: calls.append(("stop", name)),
    )
    monkeypatch.setattr(
        ollama_setup.docker_backend,
        "run_container",
        lambda name, image, args, **kwargs: (
            calls.append(("run", name, image, args, kwargs)),
            "container-id",
        )[1],
    )
    def fake_exec(name, args, **_kwargs):
        calls.append(("exec", name, tuple(args)))
        # readiness succeeds; model lookup reports "not installed"
        return _Proc(0 if list(args) == ["ollama", "list"] else 1)

    monkeypatch.setattr(
        ollama_setup.docker_backend,
        "exec_container",
        fake_exec,
    )
    monkeypatch.setattr(
        ollama_setup.docker_backend,
        "exec_container_live",
        lambda name, args, **_k: calls.append(("live", name, tuple(args))),
    )
    return calls


def test_pull_selected_models_uses_persistent_volume_and_order(monkeypatch, tmp_path: Path):
    calls = _fake_backend(monkeypatch, tmp_path)

    pulled = ollama_setup.pull_selected_models(
        tmp_path,
        ["gemma3:1b", "qwen3:8b"],
    )

    assert pulled == ["gemma3:1b", "qwen3:8b"]
    run = next(call for call in calls if call[0] == "run")
    assert run[4]["volumes"] == {"llmbench-ollama-cache": "/root/.ollama"}
    live = [call[2] for call in calls if call[0] == "live"]
    assert live == [
        ("ollama", "pull", "gemma3:1b"),
        ("ollama", "pull", "qwen3:8b"),
    ]
    assert calls[-1] == ("stop", ollama_setup.PULL_CONTAINER_NAME)


def test_pull_selected_models_skips_local_gguf(monkeypatch, tmp_path: Path):
    gguf = tmp_path / "local.gguf"
    gguf.write_bytes(b"GGUF")
    calls = _fake_backend(monkeypatch, tmp_path)

    pulled = ollama_setup.pull_selected_models(
        tmp_path,
        [str(gguf), "qwen3:8b"],
    )

    assert pulled == ["qwen3:8b"]
    live = [call[2] for call in calls if call[0] == "live"]
    assert live == [("ollama", "pull", "qwen3:8b")]


def test_pull_selected_models_does_nothing_for_only_local_gguf(monkeypatch, tmp_path: Path):
    gguf = tmp_path / "local.gguf"
    gguf.write_bytes(b"GGUF")
    calls = _fake_backend(monkeypatch, tmp_path)

    assert ollama_setup.pull_selected_models(tmp_path, [str(gguf)]) == []
    assert calls == []


def test_pull_selected_models_cleans_up_after_failed_pull(monkeypatch, tmp_path: Path):
    calls = _fake_backend(monkeypatch, tmp_path)

    def fail_pull(name, args, **_kwargs):
        calls.append(("live", name, tuple(args)))
        raise RuntimeError("download failed")

    monkeypatch.setattr(ollama_setup.docker_backend, "exec_container_live", fail_pull)

    with pytest.raises(RuntimeError, match="download failed"):
        ollama_setup.pull_selected_models(tmp_path, ["qwen3:8b"])

    assert calls[-1] == ("stop", ollama_setup.PULL_CONTAINER_NAME)



def test_pull_selected_models_skips_download_when_model_is_already_present(monkeypatch, tmp_path: Path):
    calls = _fake_backend(monkeypatch, tmp_path)

    def fake_exec(name, args, **_kwargs):
        calls.append(("exec", name, tuple(args)))
        return _Proc(0)

    monkeypatch.setattr(ollama_setup.docker_backend, "exec_container", fake_exec)

    pulled = ollama_setup.pull_selected_models(tmp_path, ["qwen3:8b"])

    assert pulled == ["qwen3:8b"]
    assert not any(call[0] == "live" for call in calls)
