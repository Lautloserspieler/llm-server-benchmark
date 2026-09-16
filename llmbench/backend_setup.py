"""Installation und restlose Deinstallation der Container-Backends.

Duenne Orchestrierungsschicht ueber ``docker_backend.py`` - im Geiste analog zu
``llama_cpp_setup.py``, nur dass die "Installation" hier aus einem Image-Pull
besteht statt aus Download/Build von Binaries.

Neue Backends (Ollama, TGI) brauchen spaeter nur einen weiteren Eintrag in
``BACKEND_IMAGES``/``BACKEND_VOLUMES``, keine Aenderung an der Logik.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import docker_backend

LogFn = Callable[[str], None]

DEFAULT_VLLM_IMAGE = "vllm/vllm-openai:latest"

# Standard-Image je Backend. Ueber ToolsConfig bzw. --image uebersteuerbar.
BACKEND_IMAGES: dict[str, str] = {
    "vllm": DEFAULT_VLLM_IMAGE,
}

# Container-Name je Backend. Fest vergeben, damit `uninstall-backend` auch nach
# einem Absturz von llmbench noch aufraeumen kann.
BACKEND_CONTAINERS: dict[str, str] = {
    "vllm": "llmbench-vllm",
}

# Benanntes Volume fuer heruntergeladene Modell-Gewichte / HF-Cache.
# Wird nur bei --purge-models entfernt: ein unangekuendigtes Loeschen mehrerer
# Gigabyte waere gegen die sonstige Praxis dieses Projekts.
BACKEND_VOLUMES: dict[str, str] = {
    "vllm": "llmbench-vllm-cache",
}

SUPPORTED_BACKENDS = tuple(sorted(BACKEND_IMAGES))


def _noop(_msg: str) -> None:
    return None


def _check_name(name: str) -> str:
    if name not in BACKEND_IMAGES:
        raise ValueError(
            f"Unbekanntes Backend: {name!r}. Erlaubt: " + ", ".join(SUPPORTED_BACKENDS)
        )
    return name


def default_image(name: str) -> str:
    return BACKEND_IMAGES[_check_name(name)]


def container_name(name: str) -> str:
    return BACKEND_CONTAINERS[_check_name(name)]


def volume_name(name: str) -> str:
    return BACKEND_VOLUMES[_check_name(name)]


def state_dir(name: str, root: Path | str) -> Path:
    return Path(root) / ".runtime" / _check_name(name)


def state_file(name: str, root: Path | str) -> Path:
    return state_dir(name, root) / ".install-state.json"


def read_state(name: str, root: Path | str) -> dict[str, Any] | None:
    """Installationszustand, oder None wenn das Backend nicht installiert ist."""
    path = state_file(name, root)
    if not path.exists():
        return None
    try:
        # utf-8-sig, gleiche Begruendung wie bei .llama-build.json.
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def is_installed(name: str, root: Path | str) -> bool:
    return read_state(name, root) is not None


def ensure_backend(
    name: str,
    root: Path | str,
    image: str | None = None,
    log: LogFn | None = None,
) -> dict[str, Any]:
    """Sorgt dafuer, dass das Image des Backends lokal bereitliegt.

    Schreibt denselben Zustandsdatei-Stil wie ``llama_cpp_setup.py``
    (`.llama-build.json`), nur unter `.runtime/<backend>/.install-state.json`.
    """
    log = log or _noop
    _check_name(name)
    root = Path(root)
    image = image or default_image(name)

    existing = read_state(name, root)
    if existing and existing.get("image") == image and docker_backend.image_exists(image):
        log(f"Backend '{name}' ist bereits installiert: {image}")
        return existing

    if not docker_backend.docker_available():
        raise RuntimeError(
            f"Backend '{name}' braucht einen erreichbaren Docker-Daemon. "
            "Pruefe, ob Docker laeuft (Linux: `systemctl status docker`, "
            "Windows/macOS: Docker Desktop starten)."
        )

    docker_backend.pull_image(image, log=log)

    state: dict[str, Any] = {
        "backend": name,
        "image": image,
        "tag": image.rsplit(":", 1)[-1] if ":" in image else "latest",
        "digest": docker_backend.image_digest(image),
        "container": container_name(name),
        "volume": volume_name(name),
        "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    target = state_file(name, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Backend '{name}' wurde installiert: {image}")
    return state


def describe_backend_removal(
    name: str,
    root: Path | str,
    purge_models: bool = False,
) -> dict[str, Any]:
    """Was `remove_backend` loeschen wuerde - fuer die Rueckfrage vor dem Loeschen."""
    _check_name(name)
    root = Path(root)
    state = read_state(name, root)
    image = (state or {}).get("image") or default_image(name)
    return {
        "backend": name,
        "installed": state is not None,
        "image": image,
        "container": container_name(name),
        "volume": volume_name(name) if purge_models else None,
        "volume_kept": None if purge_models else volume_name(name),
        "state_file": str(state_file(name, root)),
        "purge_models": bool(purge_models),
    }


def remove_backend(
    name: str,
    root: Path | str,
    purge_models: bool = False,
    log: LogFn | None = None,
) -> None:
    """Entfernt Container, Image, (optional) Volume und die Zustandsdatei.

    Muss auch dann sauber durchlaufen, wenn nichts installiert ist oder gar kein
    Docker verfuegbar ist - `uninstall` darf nie der Schritt sein, der scheitert.
    """
    log = log or _noop
    _check_name(name)
    root = Path(root)
    state = read_state(name, root)
    image = (state or {}).get("image") or default_image(name)
    container = (state or {}).get("container") or container_name(name)
    volume = (state or {}).get("volume") or volume_name(name)

    if docker_backend.docker_available():
        docker_backend.stop_container(container, log=log)
        docker_backend.remove_image(image, log=log)
        if purge_models:
            docker_backend.remove_volume(volume, log=log)
        else:
            log(
                f"Volume '{volume}' bleibt erhalten (heruntergeladene Modell-Gewichte). "
                "Mit --purge-models wird es ebenfalls entfernt."
            )
    else:
        log(
            "Docker ist nicht erreichbar - Container, Image und Volume koennen nicht "
            "entfernt werden. Es wird nur die lokale Zustandsdatei bereinigt."
        )

    path = state_file(name, root)
    if path.exists():
        path.unlink()
        log(f"Zustandsdatei entfernt: {path}")

    directory = state_dir(name, root)
    if directory.is_dir() and not any(directory.iterdir()):
        directory.rmdir()

    if state is None:
        log(f"Backend '{name}' war nicht installiert - es gab nichts zu entfernen.")
    else:
        log(f"Backend '{name}' wurde vollstaendig entfernt.")
