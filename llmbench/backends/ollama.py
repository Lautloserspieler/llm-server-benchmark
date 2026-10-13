"""Ollama-Backend: Docker-Container mit nativer /api/generate API.

Ollama kann entweder ein bereits heruntergeladenes Modellnamen-Skelett
verwenden oder ein lokales GGUF direkt aus dem Container heraus einlesen.
Im GGUF-Fall wird das Verzeichnis des GGUFs schreibgeschuetzt nach /models
gemountet, ein Modelfile generiert und das Modell ueber die Create-API
registriert, bevor der eigentliche Health-Check laeuft.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .base import BenchmarkBackend
from .capabilities import BackendCapabilities
from .. import backend_setup, docker_backend
from ..endpoint import wait_health
from ..http_bench import API_STYLE_OLLAMA_NATIVE, run_http_bench
from ..i18n import _
from ..utils import auth_headers

# Ollama lauscht im Container auf 11434.
CONTAINER_PORT = 11434
DEFAULT_HOST_PORT = 11434
DEFAULT_BASE_URL = f"http://127.0.0.1:{DEFAULT_HOST_PORT}"

# Lokale Modelle/Modelfiles landen in diesem Container-Pfad.
MODEL_MOUNT = "/models"

STARTUP_TIMEOUT_SECONDS = 1800.0


def _looks_like_gguf(model_path: str) -> bool:
    """True, wenn es sich um eine lokale GGUF-Datei handelt."""
    p = Path(model_path)
    return p.exists() and p.suffix.lower() == ".gguf"


def _model_name_for(model_path: str) -> str:
    """Eindeutiger Ollama-Modellname fuer ein lokales GGUF."""
    p = Path(model_path)
    return f"llmbench-{p.stem}"


def _build_modelfile(gguf_name: str) -> str:
    """Minimales Modelfile, das auf das gemountete GGUF verweist."""
    return (
        f'FROM "{MODEL_MOUNT}/{gguf_name}"\n'
        "PARAMETER temperature 0.0\n"
    )


class OllamaBackend(BenchmarkBackend):
    """Startet Ollama als Container und misst ueber die native Generate-API."""

    capabilities = BackendCapabilities(
        endpoint=True,
        streaming=True,
        concurrency=True,
        long_context=True,
        kv_cache_observation=False,
        oom_probe=False,
        quantization=False,
        multi_model=False,
    )

    def __init__(
        self,
        image: str,
        endpoint_cfg: dict[str, Any] | None = None,
        root: Path | str | None = None,
        container_name: str | None = None,
    ):
        self.image = image
        self.endpoint_cfg: dict[str, Any] = dict(endpoint_cfg or {})
        self.root = Path(root) if root else Path.cwd()
        self.container_name = container_name or backend_setup.container_name("ollama")
        self.volume_name = backend_setup.volume_name("ollama")
        self.container_id: str | None = None
        self.command: str | None = None
        self.base_url: str = str(self.endpoint_cfg.get("base_url") or DEFAULT_BASE_URL)
        self.target_pid: int | None = None
        self._log_path: Path | None = None
        self._created_model: str | None = None

    # ------------------------------------------------------------- Container

    def _host_port(self, endpoint_cfg: dict[str, Any]) -> int:
        parsed = urlparse(str(endpoint_cfg.get("base_url") or DEFAULT_BASE_URL))
        return parsed.port or DEFAULT_HOST_PORT

    def _base_url_for(self, endpoint_cfg: dict[str, Any]) -> str:
        return str(endpoint_cfg.get("base_url") or DEFAULT_BASE_URL)

    def _printable(self, args: list[str]) -> str:
        return f"docker run {self.image} " + " ".join(args)

    def _start(
        self,
        model_path: str,
        profile: dict[str, Any],  # noqa: ARG002 - Profil-Optionen folgen spaeter
        endpoint_cfg: dict[str, Any],
        log: Any = None,
    ) -> tuple[str, str]:
        """Container starten; bei lokalem GGUF wird das Modell vorab angelegt."""
        backend_setup.ensure_backend("ollama", self.root, self.image, log=log)

        # GGUF einmounten und Modelfile erzeugen, falls noetig.
        volumes: dict[str, str] = {}
        create_payload: dict[str, Any] | None = None
        if _looks_like_gguf(model_path):
            p = Path(model_path).resolve()
            volumes[f"{p.parent}"] = f"{MODEL_MOUNT}:ro"
            modelfile = _build_modelfile(p.name)
            modelfile_path = p.parent / "Modelfile"
            modelfile_path.write_text(modelfile, encoding="utf-8")
            self._created_model = _model_name_for(model_path)
            create_payload = {
                "name": self._created_model,
                "modelfile": modelfile,
                "stream": False,
            }

        docker_backend.stop_container(self.container_name, log=log)

        container_id = docker_backend.run_container(
            self.container_name,
            self.image,
            [],  # Ollama-Image startet den Server als Entrypoint/Command.
            gpu=True,
            port_map={self._host_port(endpoint_cfg): CONTAINER_PORT},
            volumes=volumes,
            log=log,
        )
        self.container_id = container_id
        self.command = self._printable([])
        self.base_url = self._base_url_for(endpoint_cfg)
        self.target_pid = docker_backend.container_pid(self.container_name)

        if create_payload is not None:
            self._create_model(create_payload)

        return container_id, self.command

    def _create_model(self, payload: dict[str, Any]) -> None:
        """Warte kurz, bis die API bereit ist, dann POST /api/create."""
        wait_health(self.base_url, 60.0, path="/api/tags")
        with contextlib.suppress(Exception):
            response = httpx.post(
                f"{self.base_url.rstrip('/')}/api/create",
                json=payload,
                timeout=600.0,
            )
            response.raise_for_status()

    def _stop(self) -> None:
        if self.container_id is None and not docker_backend.container_exists(self.container_name):
            return
        self._capture_logs()
        docker_backend.stop_container(self.container_name)
        self.container_id = None
        self.target_pid = None
        self._created_model = None

    def _capture_logs(self) -> None:
        if not self._log_path:
            return
        with contextlib.suppress(Exception):
            text = docker_backend.container_logs(self.container_name)
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_path.write_text(text, encoding="utf-8")

    def _headers(self) -> dict[str, str]:
        return auth_headers(self.endpoint_cfg)

    def _model_for_request(self, model_path: str) -> str:
        """Name, unter dem Ollama das Modell ansprechen kann."""
        if _looks_like_gguf(model_path):
            return self._created_model or _model_name_for(model_path)
        # Sonst handelt es sich um einen Ollama-Modellnamen.
        return str(model_path).strip()

    # -------------------------------------------------------- Profil-Hooks

    def begin_profile(
        self,
        model_path: str,
        profile: dict[str, Any],
        bench_cfg: dict[str, Any],  # noqa: ARG002
        out_dir: Path,
    ) -> None:
        """Startet den Server einmal pro Profil statt einmal pro Testart."""
        self._log_path = Path(out_dir) / "ollama-server.log"
        try:
            self._start(model_path, profile, self.endpoint_cfg)
            timeout = float(self.endpoint_cfg.get("startup_timeout_seconds") or STARTUP_TIMEOUT_SECONDS)
            self.wait_health(self.base_url, timeout, self._headers())
        except Exception as exc:
            logs = docker_backend.container_logs(self.container_name, tail=80)
            self._capture_logs()
            docker_backend.stop_container(self.container_name)
            self.container_id = None
            raise RuntimeError(
                _("Ollama-Container wurde nicht bereit: {exc}").format(exc=exc)
                + (f"\n{_('Container-Log (Ende):')}\n{logs[-2000:]}" if logs else "")
            ) from exc

    def end_profile(self) -> None:
        self._stop()

    # ------------------------------------------------------------ Messungen

    def run_benchmark(
        self,
        model_path: str,
        profile: dict[str, Any],  # noqa: ARG002
        kind: str,
        out_dir: Path,
        bench_cfg: dict[str, Any],
        on_progress=None,
    ) -> dict[str, Any]:
        if self.container_id is None:
            return {
                "kind": kind,
                "status": "failed",
                "error": _(
                    "Es laeuft kein Ollama-Container. run_benchmark erwartet, dass "
                    "begin_profile den Server bereits gestartet hat."
                ),
            }
        # Model-Name muss in jede Request-Payload gelangen.
        cfg = dict(bench_cfg)
        cfg["model"] = self._model_for_request(model_path)
        return run_http_bench(
            self.base_url,
            self._headers(),
            cfg,
            profile,
            kind,
            Path(out_dir),
            on_progress=on_progress,
            backend_name="ollama",
            target_pid=self.target_pid,
            api_style=API_STYLE_OLLAMA_NATIVE,
        )

    # --------------------------------------------------------- Endpoint-Pfad

    def prepare_endpoint_config(self, endpoint_cfg: dict[str, Any]) -> dict[str, Any]:
        cfg = dict(endpoint_cfg)
        cfg["api_style"] = API_STYLE_OLLAMA_NATIVE
        return cfg

    def start_server(
        self,
        model_path: str,
        profile: dict[str, Any],
        endpoint_cfg: dict[str, Any],
        bench_cfg: dict[str, Any],  # noqa: ARG002
        log_path: Path,
    ) -> tuple[Any, str]:
        """Fuer den Endpoint-Lasttest."""
        self.endpoint_cfg = dict(endpoint_cfg or {})
        self._log_path = Path(log_path)
        container_id, command = self._start(model_path, profile, self.endpoint_cfg)
        # Ollamas /api/generate braucht den Modellnamen in jeder Request.
        endpoint_cfg["model"] = self._model_for_request(model_path)
        return _ContainerHandle(self.container_name, container_id, self.target_pid), command

    def stop_server(self, proc: Any) -> None:
        name = getattr(proc, "name", None) or self.container_name
        if self._log_path:
            self._capture_logs()
        docker_backend.stop_container(name)
        self.container_id = None
        self.target_pid = None
        self._created_model = None

    def wait_health(
        self,
        base_url: str,
        timeout_s: float,
        headers: dict[str, str] | None = None,
        proc: Any = None,  # noqa: ARG002
    ) -> float:
        # Ollama hat keine dedizierte /health-Route; /api/tags ist ein
        # einfacher Liveness-Check, der erreichbar sein muss.
        return wait_health(base_url, timeout_s, headers, path="/api/tags")


class _ContainerHandle:
    """Steht im Endpoint-Pfad an der Stelle, an der llama.cpp ein Popen liefert."""

    def __init__(self, name: str, container_id: str, pid: int | None):
        self.name = name
        self.container_id = container_id
        self.pid = pid
