"""Error-path coverage for setup and backend start (Issue #123).

Missing Docker, no NVIDIA runtime, CPU-only Ollama, bad proxy / download
failures and interrupted setup. Everything is mocked: no network, no Docker.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import URLError

import pytest

from llmbench import backend_setup, download, llama_cpp_setup
from llmbench.backends.ollama import OllamaBackend
from llmbench.backends.tgi import TgiBackend
from llmbench.backends.vllm import VllmBackend

# ------------------------------------------------------------ Docker fehlt


@pytest.mark.parametrize(
    ("backend_cls", "module"),
    [(TgiBackend, "tgi"), (VllmBackend, "vllm"), (OllamaBackend, "ollama")],
)
def test_missing_docker_fails_clearly_and_starts_nothing(monkeypatch, tmp_path: Path, backend_cls, module):
    started: list[str] = []
    monkeypatch.setattr(
        f"llmbench.backends.{module}.backend_setup.ensure_backend",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("Docker wurde nicht gefunden.")),
    )
    monkeypatch.setattr(
        f"llmbench.backends.{module}.docker_backend.run_container",
        lambda *_a, **_k: started.append("run"),
    )
    monkeypatch.setattr(f"llmbench.backends.{module}.docker_backend.stop_container", lambda *_a, **_k: None)
    monkeypatch.setattr(f"llmbench.backends.{module}.docker_backend.container_logs", lambda *_a, **_k: "")
    backend = backend_cls("img", endpoint_cfg={"base_url": "http://127.0.0.1:18080"})

    with pytest.raises(RuntimeError, match="Docker wurde nicht gefunden"):
        backend.begin_profile("org/model", {}, {}, tmp_path)

    assert started == []
    assert backend.container_id is None


# ------------------------------------------------ Keine NVIDIA / CPU-only Ollama


@pytest.fixture
def cpu_only_host(monkeypatch):
    """Docker works, but --gpus is rejected like on a host without NVIDIA runtime."""
    runs: list[dict] = []
    running: set[str] = set()

    def run_container(name, image, args, **kwargs):
        runs.append({"name": name, "image": image, "args": list(args), **kwargs})
        if kwargs.get("gpu"):
            raise RuntimeError(
                'docker: Error response from daemon: could not select device driver "" with capabilities: [[gpu]]'
            )
        running.add(name)
        return "CID"

    monkeypatch.setattr("llmbench.backends.ollama.docker_backend.run_container", run_container)
    monkeypatch.setattr("llmbench.backends.ollama.docker_backend.stop_container", lambda name, log=None: running.discard(name))  # noqa: ARG005
    monkeypatch.setattr("llmbench.backends.ollama.docker_backend.container_pid", lambda _n: 1)
    monkeypatch.setattr("llmbench.backends.ollama.docker_backend.container_exists", lambda _n: False)
    monkeypatch.setattr("llmbench.backends.ollama.docker_backend.container_logs", lambda *_a, **_k: "")
    monkeypatch.setattr("llmbench.backends.ollama.docker_backend.check_container_alive", lambda _n: None)
    monkeypatch.setattr("llmbench.backends.ollama.backend_setup.ensure_backend", lambda *_a, **_k: {})
    monkeypatch.setattr("llmbench.backends.ollama.wait_health", lambda *_a, **_k: 0.1)
    monkeypatch.setattr("llmbench.backends.ollama.OllamaBackend._ensure_registry_model", lambda _s, _m: None)
    return runs, running


def test_cpu_only_ollama_profile_starts_without_gpu_flags(cpu_only_host, tmp_path: Path):
    runs, running = cpu_only_host
    backend = OllamaBackend("ollama/ollama:test", endpoint_cfg={"base_url": "http://127.0.0.1:11434"})

    backend.begin_profile("llama3.2:3b", {"gpu_layers": 0}, {}, tmp_path)

    assert runs[0]["gpu"] is False
    assert running == {backend.container_name}
    backend.end_profile()
    assert running == set()


def test_gpu_profile_on_host_without_nvidia_reports_docker_reason_and_leaves_no_container(cpu_only_host, tmp_path: Path):
    _runs, running = cpu_only_host
    backend = OllamaBackend("ollama/ollama:test", endpoint_cfg={"base_url": "http://127.0.0.1:11434"})

    with pytest.raises(RuntimeError, match="could not select device driver"):
        backend.begin_profile("llama3.2:3b", {"gpu_layers": -1}, {}, tmp_path)

    assert running == set() and backend.container_id is None


# ------------------------------------------------ Proxy / Download-Fehler


def test_github_proxy_failure_is_reported_as_actionable_error(monkeypatch):
    def refuse(*_a, **_k):
        raise URLError("Tunnel connection failed: 403 Forbidden")

    monkeypatch.setattr(llama_cpp_setup, "urlopen", refuse)
    with pytest.raises(RuntimeError, match="Tunnel connection failed"):
        llama_cpp_setup._github_get("https://api.github.com/repos/x/y/releases/latest")


def test_asset_download_proxy_failure_names_the_proxy_settings_and_leaves_no_file(monkeypatch, tmp_path: Path):
    def refuse(*_a, **_k):
        raise URLError("proxy unreachable")

    monkeypatch.setattr(llama_cpp_setup, "urlopen", refuse)
    dest = tmp_path / "asset.tar.gz"
    with pytest.raises(RuntimeError, match="HTTPS_PROXY"):
        llama_cpp_setup._download_file("https://example.invalid/asset.tar.gz", dest)
    assert not dest.exists()


def test_interrupted_asset_download_removes_the_partial_file(monkeypatch, tmp_path: Path):
    class _Response:
        def __init__(self):
            self.calls = 0

        def read(self, _n):
            self.calls += 1
            if self.calls == 1:
                return b"partial-bytes"
            raise KeyboardInterrupt

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return None

    monkeypatch.setattr(llama_cpp_setup, "urlopen", lambda *_a, **_k: _Response())
    dest = tmp_path / "asset.tar.gz"
    with pytest.raises(KeyboardInterrupt):
        llama_cpp_setup._download_file("https://example.invalid/asset.tar.gz", dest)
    assert not dest.exists()


def test_model_download_failure_is_reported_and_marks_models_missing(monkeypatch, tmp_path: Path):
    def fail(**_kwargs):
        raise ConnectionError("ProxyError: Cannot connect to proxy")

    monkeypatch.setattr(download, "snapshot_download", fail)
    with pytest.raises(RuntimeError, match="Modell-Download unvollstaendig.*Cannot connect to proxy"):
        download.download_models(tmp_path, suite="small")


# ------------------------------------------------ Unterbrochenes Setup


@pytest.fixture
def docker_setup(monkeypatch):
    state = {"images": set(), "pulls": 0, "interrupt": False}

    def pull_image(image, log=None):  # noqa: ARG001
        state["pulls"] += 1
        if state["interrupt"]:
            raise KeyboardInterrupt
        state["images"].add(image)

    monkeypatch.setattr(backend_setup.docker_backend, "docker_available", lambda: True)
    monkeypatch.setattr(backend_setup.docker_backend, "image_exists", lambda image: image in state["images"])
    monkeypatch.setattr(backend_setup.docker_backend, "image_digest", lambda image: image + "@sha256:abc")
    monkeypatch.setattr(backend_setup.docker_backend, "pull_image", pull_image)
    return state


def test_interrupted_pull_leaves_no_install_state_and_setup_can_resume(docker_setup, tmp_path: Path):
    docker_setup["interrupt"] = True
    with pytest.raises(KeyboardInterrupt):
        backend_setup.ensure_backend("tgi", tmp_path, "img:1")
    assert backend_setup.read_state("tgi", tmp_path) is None
    assert not backend_setup.state_file("tgi", tmp_path).exists()

    docker_setup["interrupt"] = False
    state = backend_setup.ensure_backend("tgi", tmp_path, "img:1")
    assert state["image"] == "img:1" and backend_setup.is_installed("tgi", tmp_path)
    assert docker_setup["pulls"] == 2


@pytest.mark.usefixtures("docker_setup")
def test_state_file_is_written_atomically(tmp_path: Path, monkeypatch):
    seen: list[str] = []
    original = backend_setup.write_text_atomic

    def spy(path, text, **kwargs):
        seen.append(str(path))
        return original(path, text, **kwargs)

    monkeypatch.setattr(backend_setup, "write_text_atomic", spy)
    backend_setup.ensure_backend("ollama", tmp_path, "img:2")
    assert seen == [str(backend_setup.state_file("ollama", tmp_path))]
    assert json.loads(backend_setup.state_file("ollama", tmp_path).read_text(encoding="utf-8"))["image"] == "img:2"
    assert not list(backend_setup.state_file("ollama", tmp_path).parent.glob("*.tmp"))


@pytest.mark.usefixtures("docker_setup")
def test_corrupt_state_file_counts_as_not_installed_and_is_repaired(tmp_path: Path):
    path = backend_setup.state_file("vllm", tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text('{"backend": "vllm", "image": ', encoding="utf-8")  # truncated by a crash

    assert backend_setup.is_installed("vllm", tmp_path) is False
    backend_setup.ensure_backend("vllm", tmp_path, "img:3")
    assert backend_setup.read_state("vllm", tmp_path)["image"] == "img:3"
