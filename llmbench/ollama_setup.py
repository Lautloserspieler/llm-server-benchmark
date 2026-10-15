"""Ollama-Modelle direkt waehrend Setup/Modellauswahl vorbereiten."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from . import backend_setup, docker_backend
from .i18n import _

LogFn = Callable[[str], None]

PULL_CONTAINER_NAME = "llmbench-ollama-pull"
OLLAMA_DATA_MOUNT = "/root/.ollama"
STARTUP_TIMEOUT_SECONDS = 60.0
MODEL_PULL_TIMEOUT_SECONDS = 12 * 3600.0


def _noop(_msg: str) -> None:
    return None


def _is_local_gguf(reference: str) -> bool:
    path = Path(reference)
    return path.exists() and path.suffix.lower() == ".gguf"


def _registry_models(references: list[str]) -> list[str]:
    result: list[str] = []
    for reference in references:
        value = str(reference).strip()
        if not value or _is_local_gguf(value):
            continue
        if value not in result:
            result.append(value)
    return result


def _wait_until_ready(container_name: str, timeout: float = STARTUP_TIMEOUT_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        proc = docker_backend.exec_container(
            container_name,
            ["ollama", "list"],
            timeout=10.0,
            check=False,
        )
        if proc.returncode == 0:
            return
        time.sleep(0.5)
    raise RuntimeError(_("Ollama-Download-Container wurde nicht rechtzeitig bereit."))


def pull_selected_models(
    root: Path | str,
    references: list[str],
    *,
    log: LogFn | None = None,
) -> list[str]:
    """Laedt ausgewaehlte Ollama-Library-Modelle in das persistente Backend-Volume."""
    log = log or _noop
    models = _registry_models(references)
    if not models:
        return []

    root = Path(root)
    state = backend_setup.ensure_backend("ollama", root, log=log)
    image = str(state.get("image") or backend_setup.default_image("ollama"))
    volume = str(state.get("volume") or backend_setup.volume_name("ollama"))

    docker_backend.stop_container(PULL_CONTAINER_NAME, log=log)
    docker_backend.run_container(
        PULL_CONTAINER_NAME,
        image,
        [],
        gpu=False,
        volumes={volume: OLLAMA_DATA_MOUNT},
        log=log,
    )

    try:
        _wait_until_ready(PULL_CONTAINER_NAME)
        total = len(models)
        for index, model in enumerate(models, start=1):
            log(
                _("Ollama-Modell {index}/{total} herunterladen: {model}").format(
                    index=index,
                    total=total,
                    model=model,
                )
            )
            docker_backend.exec_container_live(
                PULL_CONTAINER_NAME,
                ["ollama", "pull", model],
                timeout=MODEL_PULL_TIMEOUT_SECONDS,
            )
            log(_("Ollama-Modell bereit: {model}").format(model=model))
    finally:
        docker_backend.stop_container(PULL_CONTAINER_NAME, log=log)

    return models
