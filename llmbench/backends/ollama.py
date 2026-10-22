"""Ollama-Backend: Docker-Container mit nativer /api/generate API.

Ollama kann entweder ein bereits heruntergeladenes Modellnamen-Skelett
verwenden oder ein lokales GGUF direkt aus dem Container heraus einlesen.
Im GGUF-Fall wird das Verzeichnis des GGUFs schreibgeschuetzt nach /models
gemountet, ein Modelfile generiert und das Modell ueber die Create-API
registriert, bevor der eigentliche Health-Check laeuft.
"""

from __future__ import annotations

import contextlib
import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .base import BenchmarkBackend
from .capabilities import BackendCapabilities
from .http_probe import probe_context_http
from .. import backend_setup, docker_backend
from ..endpoint import wait_health
from ..bootstrap import model_shards, shard_set_complete
from ..http_bench import API_STYLE_OLLAMA_NATIVE, run_http_bench
from ..i18n import _
from ..utils import auth_headers

# Ollama lauscht im Container auf 11434. Der Host-Port kommt normalerweise aus
# endpoint.base_url der Config (Standard dort: 8080); DEFAULT_* gilt nur ohne base_url.
CONTAINER_PORT = 11434
DEFAULT_HOST_PORT = 11434
DEFAULT_BASE_URL = f"http://127.0.0.1:{DEFAULT_HOST_PORT}"

# Ollamas persistenter Modell-/Blob-Speicher. Das benannte Backend-Volume
# wird immer hier eingehängt, analog zur offiziellen Docker-Empfehlung.
OLLAMA_DATA_MOUNT = "/root/.ollama"
UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024

STARTUP_TIMEOUT_SECONDS = 1800.0


def _looks_like_gguf(model_path: str) -> bool:
    """True, wenn es sich um eine lokale GGUF-Datei handelt."""
    p = Path(model_path)
    return p.exists() and p.suffix.lower() == ".gguf"


def _model_name_for(model_path: str) -> str:
    """Eindeutiger Ollama-Modellname fuer ein lokales GGUF."""
    p = Path(model_path)
    return f"llmbench-{p.stem}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(UPLOAD_CHUNK_BYTES), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _file_chunks(path: Path) -> Iterator[bytes]:
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            yield chunk


def _raise_with_body(response: httpx.Response, context: str) -> None:
    """raise_for_status() mit Ollamas Fehlertext ({"error": ...}) in der Meldung."""
    if response.status_code < 400:
        return
    detail = ""
    try:
        data = response.json()
        detail = str(data.get("error") or data) if isinstance(data, dict) else str(data)
    except Exception:
        detail = response.text.strip()
    raise RuntimeError(f"{context}: HTTP {response.status_code} {detail[:500]}".strip())


def _use_gpu(profile: dict[str, Any]) -> bool:
    explicit = profile.get("ollama_num_gpu")
    if explicit is not None:
        return int(explicit) != 0
    return int(profile.get("gpu_layers", -1)) != 0


class OllamaBackend(BenchmarkBackend):
    """Startet Ollama als Container und misst ueber die native Generate-API."""

    capabilities = BackendCapabilities(
        endpoint=True,
        streaming=True,
        concurrency=True,
        long_context=True,
        kv_cache_observation=False,
        oom_probe=True,
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

        self._created_model = None
        volumes: dict[str, str] = {self.volume_name: OLLAMA_DATA_MOUNT}

        docker_backend.stop_container(self.container_name, log=log)

        container_id = docker_backend.run_container(
            self.container_name,
            self.image,
            [],  # Ollama-Image startet den Server als Entrypoint/Command.
            gpu=_use_gpu(profile),
            port_map={self._host_port(endpoint_cfg): CONTAINER_PORT},
            volumes=volumes,
            log=log,
        )
        self.container_id = container_id
        self.command = self._printable([])
        self.base_url = self._base_url_for(endpoint_cfg)
        self.target_pid = docker_backend.container_pid(self.container_name)

        # Das Modell muss vor dem ersten Benchmark-Request wirklich verfügbar sein.
        # Lokale GGUFs werden über Ollamas aktuelle Blob/Create-API importiert;
        # Registry-Modelle werden bei Bedarf in das persistente Volume gezogen.
        wait_health(self.base_url, 60.0, self._headers(), path="/api/tags")
        if _looks_like_gguf(model_path):
            self._created_model = _model_name_for(model_path)
            self._create_model(model_path)
        else:
            self._ensure_registry_model(str(model_path).strip())

        return container_id, self.command

    def _request_timeout(self) -> float:
        return float(self.endpoint_cfg.get("timeout_seconds") or 3600.0)

    def _create_model(self, model_path: str) -> None:
        """Importiert lokale GGUF-Dateien über Blob-Upload + /api/create."""
        path = Path(model_path).resolve()
        if not shard_set_complete(path):
            raise RuntimeError(f"GGUF-Shard-Satz ist unvollstaendig: {path}")

        shards = model_shards(path)
        if not shards:
            raise RuntimeError(f"GGUF-Datei nicht gefunden: {path}")

        files: dict[str, str] = {}
        timeout = self._request_timeout()
        with httpx.Client(headers=self._headers()) as client:
            for shard in shards:
                digest = _sha256_file(shard)
                blob_url = f"{self.base_url.rstrip('/')}/api/blobs/{digest}"
                head = client.head(blob_url, timeout=60.0)
                if head.status_code == 404:
                    headers = {"Content-Length": str(shard.stat().st_size)}
                    upload = client.post(
                        blob_url,
                        content=_file_chunks(shard),
                        headers=headers,
                        timeout=timeout,
                    )
                    upload.raise_for_status()
                else:
                    head.raise_for_status()
                files[shard.name] = digest

            response = client.post(
                f"{self.base_url.rstrip('/')}/api/create",
                json={
                    "model": self._created_model or _model_name_for(model_path),
                    "files": files,
                    "stream": False,
                },
                timeout=timeout,
            )
            response.raise_for_status()

    def _ensure_registry_model(self, model: str) -> None:
        """Nutzt ein persistiertes Modell oder zieht es einmal aus der Ollama-Library."""
        if not model:
            raise ValueError("Ollama-Modellname darf nicht leer sein.")

        timeout = self._request_timeout()
        with httpx.Client(headers=self._headers()) as client:
            show = client.post(
                f"{self.base_url.rstrip('/')}/api/show",
                json={"model": model},
                timeout=60.0,
            )
            if show.status_code == 200:
                return
            if show.status_code != 404:
                show.raise_for_status()

            pull = client.post(
                f"{self.base_url.rstrip('/')}/api/pull",
                json={"model": model, "stream": False},
                timeout=timeout,
            )
            _raise_with_body(pull, f"Ollama-Pull von '{model}'")
            check = client.post(
                f"{self.base_url.rstrip('/')}/api/show",
                json={"model": model},
                timeout=60.0,
            )
            _raise_with_body(check, f"Ollama kennt '{model}' nach dem Pull nicht")

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
        # Model-Name und Ollama-spezifische Profilwerte müssen in jede
        # Request-Payload gelangen.
        cfg = dict(bench_cfg)
        cfg["model"] = self._model_for_request(model_path)
        if profile.get("ollama_num_ctx") is not None:
            cfg["ollama_num_ctx"] = int(profile["ollama_num_ctx"])
        if profile.get("ollama_num_gpu") is not None:
            cfg["ollama_num_gpu"] = int(profile["ollama_num_gpu"])
        result = run_http_bench(
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
        self._attach_residency(result, cfg["model"], profile)
        return result

    def _attach_residency(self, result: dict[str, Any], model: str, profile: dict[str, Any]) -> None:
        """Belegt ueber /api/ps, wo das Modell lief (VRAM vs. RAM).

        Ollama entscheidet die Aufteilung selbst; ein GPU-Profil kann bei grossen
        Modellen still teilweise auf der CPU laufen und waere sonst nicht erkennbar.
        """
        try:
            response = httpx.get(
                f"{self.base_url.rstrip('/')}/api/ps", headers=self._headers(), timeout=10.0
            )
            response.raise_for_status()
            loaded = [m for m in response.json().get("models", []) if model in (m.get("name"), m.get("model"))]
        except Exception:
            return
        if not loaded:
            return
        size = int(loaded[0].get("size") or 0)
        size_vram = int(loaded[0].get("size_vram") or 0)
        context = loaded[0].get("context_length")
        info = {"size_bytes": size, "size_vram_bytes": size_vram, "context_length": context}
        result["ollama_residency"] = info
        if _use_gpu(profile) and size and size_vram < size * 0.99:
            share = 100.0 * size_vram / size
            result.setdefault("partial_errors", []).append(
                _("Ollama hat das Modell nur zu {share:.0f} % im VRAM gehalten; "
                  "der Rest lief auf der CPU. GPU-Werte sind nicht vergleichbar.").format(share=share)
            )

    # --------------------------------------------------------- Endpoint-Pfad

    async def probe_context(
        self,
        base_url: str,
        prompt_target: int,
        endpoint_cfg: dict[str, Any],
    ) -> dict[str, Any]:
        """Kontext-/OOM-Probe ueber den HTTP-Endpoint (siehe ``http_probe``)."""
        return await probe_context_http(base_url, prompt_target, endpoint_cfg, api_style=API_STYLE_OLLAMA_NATIVE)

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
        # Ollamas /api/generate braucht Modellname und Profiloptionen in jeder Request.
        endpoint_cfg["model"] = self._model_for_request(model_path)
        if profile.get("ollama_num_ctx") is not None:
            endpoint_cfg["ollama_num_ctx"] = int(profile["ollama_num_ctx"])
        if profile.get("ollama_num_gpu") is not None:
            endpoint_cfg["ollama_num_gpu"] = int(profile["ollama_num_gpu"])
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
