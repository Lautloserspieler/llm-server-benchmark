"""Tests fuer die docker-CLI-Huelle. Es wird nie ein echtes docker aufgerufen."""

import subprocess

import pytest

from llmbench import docker_backend


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def docker_calls(monkeypatch):
    """Faengt jeden subprocess.run-Aufruf ab und liefert die Kommandozeilen."""
    calls: list[list[str]] = []

    def _fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        return _FakeCompleted(0, "CONTAINERID\n")

    monkeypatch.setattr(docker_backend.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(docker_backend.subprocess, "run", _fake_run)
    return calls


# --------------------------------------------------------------- Verfuegbarkeit


def test_docker_available_false_without_binary(monkeypatch):
    monkeypatch.setattr(docker_backend.shutil, "which", lambda _name: None)
    assert docker_backend.docker_available() is False


def test_docker_available_false_when_daemon_unreachable(monkeypatch):
    monkeypatch.setattr(docker_backend.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(
        docker_backend.subprocess, "run", lambda *_a, **_k: _FakeCompleted(1, "", "cannot connect")
    )
    assert docker_backend.docker_available() is False


def test_docker_available_true_when_daemon_answers(docker_calls):
    assert docker_backend.docker_available() is True
    assert docker_calls[0][:2] == ["/usr/bin/docker", "info"]


def test_docker_available_false_on_exception(monkeypatch):
    monkeypatch.setattr(docker_backend.shutil, "which", lambda _name: "/usr/bin/docker")

    def _boom(*_a, **_k):
        raise OSError("boom")

    monkeypatch.setattr(docker_backend.subprocess, "run", _boom)
    assert docker_backend.docker_available() is False


def test_missing_docker_raises_helpful_error(monkeypatch):
    monkeypatch.setattr(docker_backend.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="Docker wurde nicht gefunden"):
        docker_backend.pull_image("vllm/vllm-openai:latest")


# --------------------------------------------------------------------- Images


def test_pull_image_builds_expected_command(docker_calls):
    docker_backend.pull_image("vllm/vllm-openai:v0.6.0")
    assert docker_calls[-1] == ["/usr/bin/docker", "pull", "vllm/vllm-openai:v0.6.0"]


def test_pull_image_raises_on_failure(monkeypatch):
    monkeypatch.setattr(docker_backend.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(
        docker_backend.subprocess, "run", lambda *_a, **_k: _FakeCompleted(1, "", "not found")
    )
    with pytest.raises(RuntimeError, match="fehlgeschlagen"):
        docker_backend.pull_image("nope:latest")


def test_remove_image_uses_force_and_tolerates_missing_image(monkeypatch):
    calls = []
    monkeypatch.setattr(docker_backend.shutil, "which", lambda _name: "/usr/bin/docker")

    def _fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        return _FakeCompleted(1, "", "No such image")

    monkeypatch.setattr(docker_backend.subprocess, "run", _fake_run)
    # Darf nicht werfen: uninstall muss auch ohne vorhandenes Image durchlaufen.
    docker_backend.remove_image("vllm/vllm-openai:latest")
    assert calls[-1] == ["/usr/bin/docker", "image", "rm", "-f", "vllm/vllm-openai:latest"]


def test_image_digest_prefers_repo_digest(monkeypatch):
    monkeypatch.setattr(docker_backend.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(
        docker_backend.subprocess,
        "run",
        lambda *_a, **_k: _FakeCompleted(0, '["vllm/vllm-openai@sha256:abc123"]\n'),
    )
    assert docker_backend.image_digest("vllm/vllm-openai:latest") == "vllm/vllm-openai@sha256:abc123"


def test_image_digest_falls_back_to_image_id(monkeypatch):
    monkeypatch.setattr(docker_backend.shutil, "which", lambda _name: "/usr/bin/docker")
    seen = []

    def _fake_run(cmd, **_kwargs):
        seen.append(list(cmd))
        if "{{json .RepoDigests}}" in cmd:
            return _FakeCompleted(0, "[]\n")
        return _FakeCompleted(0, "sha256:localbuild\n")

    monkeypatch.setattr(docker_backend.subprocess, "run", _fake_run)
    assert docker_backend.image_digest("local:dev") == "sha256:localbuild"


def test_image_digest_none_without_docker(monkeypatch):
    monkeypatch.setattr(docker_backend.shutil, "which", lambda _name: None)
    assert docker_backend.image_digest("x:y") is None


def test_image_exists_reflects_returncode(monkeypatch):
    monkeypatch.setattr(docker_backend.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(docker_backend.subprocess, "run", lambda *_a, **_k: _FakeCompleted(0, "sha256:x"))
    assert docker_backend.image_exists("a:b") is True
    monkeypatch.setattr(docker_backend.subprocess, "run", lambda *_a, **_k: _FakeCompleted(1, "", "no"))
    assert docker_backend.image_exists("a:b") is False


# ------------------------------------------------------------------ Container


def test_run_container_builds_full_command(docker_calls):
    container_id = docker_backend.run_container(
        "llmbench-vllm",
        "vllm/vllm-openai:latest",
        ["--model", "/models/m", "--port", "8000"],
        gpu=True,
        port_map={8000: 8000},
        env={"HF_TOKEN": "secret"},
        volumes={"/host/models": "/models:ro", "llmbench-vllm-cache": "/root/.cache/huggingface"},
        extra_args=["--shm-size", "8g"],
    )
    cmd = docker_calls[-1]

    assert cmd[:5] == ["/usr/bin/docker", "run", "-d", "--name", "llmbench-vllm"]
    # GPU-Freigabe nach der LLMBENCH_GPU_DEVICES-Konvention
    assert "--gpus" in cmd and cmd[cmd.index("--gpus") + 1] == "all"
    assert "NVIDIA_VISIBLE_DEVICES=all" in cmd
    assert "NVIDIA_DRIVER_CAPABILITIES=compute,utility" in cmd
    assert "HF_TOKEN=secret" in cmd
    assert "-p" in cmd and cmd[cmd.index("-p") + 1] == "8000:8000"
    assert "/host/models:/models:ro" in cmd
    assert "llmbench-vllm-cache:/root/.cache/huggingface" in cmd
    assert "--shm-size" in cmd and cmd[cmd.index("--shm-size") + 1] == "8g"
    # Image steht vor den Serverargumenten.
    image_at = cmd.index("vllm/vllm-openai:latest")
    assert cmd[image_at + 1:] == ["--model", "/models/m", "--port", "8000"]
    assert container_id == "CONTAINERID"


def test_run_container_without_gpu_omits_gpu_flags(docker_calls):
    docker_backend.run_container("c", "img", [], gpu=False)
    cmd = docker_calls[-1]
    assert "--gpus" not in cmd
    assert not any(x.startswith("NVIDIA_VISIBLE_DEVICES") for x in cmd)


def test_run_container_respects_explicit_gpu_device_list(docker_calls, monkeypatch):
    monkeypatch.setenv(docker_backend.GPU_DEVICES_ENV, "0,1")
    docker_backend.run_container("c", "img", [], gpu=True)
    cmd = docker_calls[-1]
    assert cmd[cmd.index("--gpus") + 1] == "device=0,1"
    assert "NVIDIA_VISIBLE_DEVICES=0,1" in cmd


def test_run_container_adds_network_when_requested(docker_calls):
    docker_backend.run_container("c", "img", [], network="benchnet")
    cmd = docker_calls[-1]
    assert "--network" in cmd and cmd[cmd.index("--network") + 1] == "benchnet"


def test_run_container_raises_on_failure(monkeypatch):
    monkeypatch.setattr(docker_backend.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(
        docker_backend.subprocess, "run",
        lambda *_a, **_k: _FakeCompleted(125, "", "port is already allocated"),
    )
    with pytest.raises(RuntimeError, match="port is already allocated"):
        docker_backend.run_container("c", "img", [])


def test_stop_container_stops_then_removes(docker_calls):
    docker_backend.stop_container("llmbench-vllm")
    assert docker_calls[-2] == ["/usr/bin/docker", "stop", "llmbench-vllm"]
    assert docker_calls[-1] == ["/usr/bin/docker", "rm", "-f", "llmbench-vllm"]


def test_stop_container_tolerates_missing_container(monkeypatch):
    monkeypatch.setattr(docker_backend.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(
        docker_backend.subprocess, "run",
        lambda *_a, **_k: _FakeCompleted(1, "", "No such container"),
    )
    docker_backend.stop_container("ghost")  # darf nicht werfen


def test_container_pid_returns_int(monkeypatch):
    monkeypatch.setattr(docker_backend.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(docker_backend.subprocess, "run", lambda *_a, **_k: _FakeCompleted(0, "4242\n"))
    assert docker_backend.container_pid("c") == 4242


def test_container_pid_none_when_zero(monkeypatch):
    """Docker Desktop meldet 0, weil der Daemon in einer VM laeuft."""
    monkeypatch.setattr(docker_backend.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(docker_backend.subprocess, "run", lambda *_a, **_k: _FakeCompleted(0, "0\n"))
    assert docker_backend.container_pid("c") is None


def test_container_pid_none_on_garbage(monkeypatch):
    monkeypatch.setattr(docker_backend.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(docker_backend.subprocess, "run", lambda *_a, **_k: _FakeCompleted(0, "n/a"))
    assert docker_backend.container_pid("c") is None


def test_container_logs_joins_streams(monkeypatch):
    monkeypatch.setattr(docker_backend.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(
        docker_backend.subprocess, "run", lambda *_a, **_k: _FakeCompleted(0, "out", "err")
    )
    assert docker_backend.container_logs("c") == "outerr"


def test_container_logs_passes_tail(docker_calls):
    docker_backend.container_logs("c", tail=50)
    assert docker_calls[-1] == ["/usr/bin/docker", "logs", "--tail", "50", "c"]


def test_container_logs_empty_without_docker(monkeypatch):
    monkeypatch.setattr(docker_backend.shutil, "which", lambda _name: None)
    assert docker_backend.container_logs("c") == ""


# -------------------------------------------------------------------- Volumes


def test_remove_volume_builds_expected_command(docker_calls):
    docker_backend.remove_volume("llmbench-vllm-cache")
    assert docker_calls[-1] == ["/usr/bin/docker", "volume", "rm", "-f", "llmbench-vllm-cache"]


def test_remove_volume_tolerates_missing_volume(monkeypatch):
    monkeypatch.setattr(docker_backend.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(
        docker_backend.subprocess, "run",
        lambda *_a, **_k: _FakeCompleted(1, "", "no such volume"),
    )
    docker_backend.remove_volume("ghost")  # darf nicht werfen


def test_timeout_is_reported_as_runtime_error(monkeypatch):
    monkeypatch.setattr(docker_backend.shutil, "which", lambda _name: "/usr/bin/docker")

    def _timeout(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=1)

    monkeypatch.setattr(docker_backend.subprocess, "run", _timeout)
    with pytest.raises(RuntimeError, match="Zeitlimit"):
        docker_backend.pull_image("x:y")
