"""Install-/Uninstall-Zyklus der Container-Backends gegen gemockte Docker-Aufrufe."""

import json
from pathlib import Path

import pytest

from llmbench import backend_setup


@pytest.fixture
def docker(monkeypatch):
    """Ersetzt alle docker_backend-Funktionen und protokolliert die Aufrufe."""

    class _Fake:
        def __init__(self):
            self.available = True
            self.images: set[str] = set()
            self.calls: list[tuple] = []

        def docker_available(self):
            return self.available

        def image_exists(self, image):
            return image in self.images

        def image_digest(self, image):
            return f"{image}@sha256:deadbeef"

        def pull_image(self, image, log=None):  # noqa: ARG002
            self.calls.append(("pull", image))
            self.images.add(image)

        def stop_container(self, name, log=None):  # noqa: ARG002
            self.calls.append(("stop", name))

        def remove_image(self, image, log=None):  # noqa: ARG002
            self.calls.append(("rmi", image))
            self.images.discard(image)

        def remove_volume(self, name, log=None):  # noqa: ARG002
            self.calls.append(("rmvol", name))

    fake = _Fake()
    for name in (
        "docker_available", "image_exists", "image_digest",
        "pull_image", "stop_container", "remove_image", "remove_volume",
    ):
        monkeypatch.setattr(backend_setup.docker_backend, name, getattr(fake, name))
    return fake


# --------------------------------------------------------------- Namensraum


def test_unknown_backend_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="Unbekanntes Backend"):
        backend_setup.ensure_backend("ollama", tmp_path)


def test_supported_backends_currently_only_vllm():
    assert backend_setup.SUPPORTED_BACKENDS == ("vllm",)


def test_state_file_path_follows_runtime_convention(tmp_path: Path):
    path = backend_setup.state_file("vllm", tmp_path)
    assert path == tmp_path / ".runtime" / "vllm" / ".install-state.json"


# ------------------------------------------------------------ ensure_backend


def test_ensure_backend_pulls_and_writes_state(docker, tmp_path: Path):
    state = backend_setup.ensure_backend("vllm", tmp_path)

    assert ("pull", "vllm/vllm-openai:latest") in docker.calls
    path = backend_setup.state_file("vllm", tmp_path)
    assert path.exists()

    written = json.loads(path.read_text(encoding="utf-8"))
    assert written == state
    assert written["backend"] == "vllm"
    assert written["image"] == "vllm/vllm-openai:latest"
    assert written["tag"] == "latest"
    assert written["digest"] == "vllm/vllm-openai:latest@sha256:deadbeef"
    assert written["container"] == "llmbench-vllm"
    assert written["volume"] == "llmbench-vllm-cache"
    assert written["installed_at"]


def test_ensure_backend_honours_image_override(docker, tmp_path: Path):
    state = backend_setup.ensure_backend("vllm", tmp_path, image="vllm/vllm-openai:v0.6.0")
    assert state["image"] == "vllm/vllm-openai:v0.6.0"
    assert state["tag"] == "v0.6.0"
    assert ("pull", "vllm/vllm-openai:v0.6.0") in docker.calls


def test_ensure_backend_is_idempotent_and_skips_second_pull(docker, tmp_path: Path):
    backend_setup.ensure_backend("vllm", tmp_path)
    first = len([c for c in docker.calls if c[0] == "pull"])
    backend_setup.ensure_backend("vllm", tmp_path)
    second = len([c for c in docker.calls if c[0] == "pull"])
    assert first == 1
    assert second == 1


def test_ensure_backend_repulls_when_image_changed(docker, tmp_path: Path):
    backend_setup.ensure_backend("vllm", tmp_path)
    backend_setup.ensure_backend("vllm", tmp_path, image="vllm/vllm-openai:v0.6.0")
    pulls = [c[1] for c in docker.calls if c[0] == "pull"]
    assert pulls == ["vllm/vllm-openai:latest", "vllm/vllm-openai:v0.6.0"]


def test_ensure_backend_repulls_when_image_vanished_locally(docker, tmp_path: Path):
    backend_setup.ensure_backend("vllm", tmp_path)
    docker.images.clear()  # Image wurde ausserhalb von llmbench entfernt
    backend_setup.ensure_backend("vllm", tmp_path)
    assert len([c for c in docker.calls if c[0] == "pull"]) == 2


def test_ensure_backend_requires_reachable_daemon(docker, tmp_path: Path):
    docker.available = False
    with pytest.raises(RuntimeError, match="Docker-Daemon"):
        backend_setup.ensure_backend("vllm", tmp_path)
    assert not backend_setup.state_file("vllm", tmp_path).exists()


# ------------------------------------------------------------ remove_backend


def test_remove_backend_removes_container_image_and_state(docker, tmp_path: Path):
    backend_setup.ensure_backend("vllm", tmp_path)
    backend_setup.remove_backend("vllm", tmp_path)

    assert ("stop", "llmbench-vllm") in docker.calls
    assert ("rmi", "vllm/vllm-openai:latest") in docker.calls
    assert not backend_setup.state_file("vllm", tmp_path).exists()
    assert not backend_setup.is_installed("vllm", tmp_path)


def test_remove_backend_keeps_model_volume_by_default(docker, tmp_path: Path):
    backend_setup.ensure_backend("vllm", tmp_path)
    backend_setup.remove_backend("vllm", tmp_path)
    assert not any(c[0] == "rmvol" for c in docker.calls)


def test_remove_backend_purges_volume_only_when_asked(docker, tmp_path: Path):
    backend_setup.ensure_backend("vllm", tmp_path)
    backend_setup.remove_backend("vllm", tmp_path, purge_models=True)
    assert ("rmvol", "llmbench-vllm-cache") in docker.calls


@pytest.mark.usefixtures("docker")
def test_remove_backend_is_safe_noop_when_nothing_installed(tmp_path: Path):
    # Darf nicht werfen und darf keine Zustandsdatei hinterlassen.
    backend_setup.remove_backend("vllm", tmp_path)
    assert not backend_setup.state_file("vllm", tmp_path).exists()


def test_remove_backend_survives_missing_docker(docker, tmp_path: Path):
    backend_setup.ensure_backend("vllm", tmp_path)
    docker.available = False
    backend_setup.remove_backend("vllm", tmp_path)
    # Ohne Docker bleibt nur die lokale Bereinigung - aber sie findet statt.
    assert not backend_setup.state_file("vllm", tmp_path).exists()


@pytest.mark.usefixtures("docker")
def test_remove_backend_leaves_no_runtime_directory(tmp_path: Path):
    backend_setup.ensure_backend("vllm", tmp_path)
    backend_setup.remove_backend("vllm", tmp_path, purge_models=True)
    assert not backend_setup.state_dir("vllm", tmp_path).exists()


def test_remove_backend_uses_image_recorded_in_state(docker, tmp_path: Path):
    """Auch ein per --image installiertes Backend muss restlos verschwinden."""
    backend_setup.ensure_backend("vllm", tmp_path, image="vllm/vllm-openai:v0.6.0")
    backend_setup.remove_backend("vllm", tmp_path)
    assert ("rmi", "vllm/vllm-openai:v0.6.0") in docker.calls


@pytest.mark.usefixtures("docker")
def test_install_uninstall_cycle_returns_to_clean_state(tmp_path: Path):
    backend_setup.ensure_backend("vllm", tmp_path)
    assert backend_setup.is_installed("vllm", tmp_path)
    backend_setup.remove_backend("vllm", tmp_path, purge_models=True)
    assert not backend_setup.is_installed("vllm", tmp_path)
    assert backend_setup.read_state("vllm", tmp_path) is None
    assert not (tmp_path / ".runtime" / "vllm").exists()


# ------------------------------------------------------- describe_backend_removal


def test_describe_removal_lists_volume_only_with_purge(tmp_path: Path):
    plan = backend_setup.describe_backend_removal("vllm", tmp_path, purge_models=True)
    assert plan["volume"] == "llmbench-vllm-cache"
    assert plan["volume_kept"] is None

    plan = backend_setup.describe_backend_removal("vllm", tmp_path, purge_models=False)
    assert plan["volume"] is None
    assert plan["volume_kept"] == "llmbench-vllm-cache"


@pytest.mark.usefixtures("docker")
def test_describe_removal_reports_installed_flag(tmp_path: Path):
    assert backend_setup.describe_backend_removal("vllm", tmp_path)["installed"] is False
    backend_setup.ensure_backend("vllm", tmp_path)
    assert backend_setup.describe_backend_removal("vllm", tmp_path)["installed"] is True


def test_read_state_tolerates_corrupt_file(tmp_path: Path):
    path = backend_setup.state_file("vllm", tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert backend_setup.read_state("vllm", tmp_path) is None
