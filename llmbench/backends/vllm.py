"""vLLM-Backend: der Server laeuft als Docker-Container.

Bewusst kein lokaler pip/venv-Pfad: mit dem offiziellen Image reduziert sich die
Installation auf einen Image-Pull und die Deinstallation auf das Entfernen von
Container, Image und Volume. Nebenbei laeuft unter Windows (Docker Desktop mit
WSL2) und unter Linux exakt derselbe Container, ohne die Plattform-Sonderfaelle,
die ``llama_cpp_setup.py::target_platform()`` fuer llama.cpp braucht.
"""

from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .base import BenchmarkBackend
from .. import backend_setup, docker_backend
from ..endpoint import wait_health
from ..http_bench import run_http_bench
from ..kv_cache import KvCacheObservation
from ..utils import auth_headers

# Innerhalb des Containers lauscht vLLM immer auf diesem Port; nach aussen wird
# der Port aus endpoint.base_url veroeffentlicht.
CONTAINER_PORT = 8000
DEFAULT_HOST_PORT = 8000
DEFAULT_BASE_URL = f"http://127.0.0.1:{DEFAULT_HOST_PORT}"

# Modelle werden schreibgeschuetzt eingehaengt, der HF-Cache in ein benanntes
# Volume - damit `uninstall-backend --purge-models` genau eine Stelle aufraeumen
# muss und ein Lauf nicht versehentlich Modelldateien veraendert.
MODEL_MOUNT = "/models"
HF_CACHE_MOUNT = "/root/.cache/huggingface"

# vLLM braucht fuer Tensor-Parallelitaet deutlich mehr Shared Memory als die
# 64 MB, die Docker vorgibt.
SHM_SIZE = "8g"

STARTUP_TIMEOUT_SECONDS = 1800.0


def _prometheus_labels(text: str) -> dict[str, str] | None:
    """Parse Prometheus labels without splitting escaped commas/quotes."""
    labels: dict[str, str] = {}
    index = 0
    while index < len(text):
        while index < len(text) and text[index] in " ,":
            index += 1
        match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)=\"", text[index:])
        if not match:
            return None
        key = match.group(1)
        index += match.end()
        value: list[str] = []
        while index < len(text):
            char = text[index]
            if char == "\\" and index + 1 < len(text):
                escaped = text[index + 1]
                value.append({"n": "\n", "\\": "\\", '"': '"'}.get(escaped, escaped))
                index += 2
                continue
            if char == '"':
                index += 1
                break
            value.append(char)
            index += 1
        else:
            return None
        labels[key] = "".join(value)
    return labels


def parse_vllm_cache_metrics(text: str, *, phase: str = "benchmark") -> list[KvCacheObservation]:
    """Extract documented ``vllm:cache_config_info`` values from metrics text."""
    observations: list[KvCacheObservation] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"vllm:cache_config_info\{(.*)\}\s+([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", line)
        if not match:
            continue
        labels = _prometheus_labels(match.group(1))
        if labels is None:
            continue
        provider = "vllm"
        cache_dtype = labels.get("cache_dtype")
        # ``auto`` is a selector, never evidence of a resolved effective dtype.
        if cache_dtype and cache_dtype.lower() != "auto":
            observations.append(KvCacheObservation("kv_dtype", cache_dtype, method="backend_runtime_introspection", provider=provider, phase=phase))
        prefix = labels.get("enable_prefix_caching")
        if prefix is not None and prefix.lower() in {"true", "false"}:
            observations.append(KvCacheObservation("prefix_caching", prefix.lower() == "true", method="backend_runtime_introspection", provider=provider, phase=phase))
        budget = labels.get("gpu_memory_utilization")
        if budget is not None:
            try:
                value = float(budget)
            except ValueError:
                continue
            observations.append(KvCacheObservation("memory_budget_fraction", value, unit="fraction", method="backend_runtime_introspection", provider=provider, phase=phase))
    return observations


def parse_vllm_cache_logs(text: str, *, phase: str = "benchmark") -> list[KvCacheObservation]:
    """Parse explicit vLLM startup/cache lines; never requested serve args."""
    observations: list[KvCacheObservation] = []
    for pattern, field, unit in (
        (r"GPU KV cache size:\s*([0-9][0-9,]*)\s+tokens", "token_capacity", "tokens"),
        (r"KV cache memory(?: allocation)?:\s*([0-9][0-9,]*)\s*(?:bytes|B)", "memory_allocation", "bytes"),
    ):
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            observations.append(KvCacheObservation(field, int(match.group(1).replace(",", "")), unit=unit, method="backend_log_parsing", provider="vllm", phase=phase))
    for match in re.finditer(r"\bvLLM\s+(?:API server )?version\s+([A-Za-z0-9._+-]+)", text, flags=re.IGNORECASE):
        observations.append(KvCacheObservation("runtime_version", match.group(1), method="backend_log_parsing", provider="vllm", phase=phase))
    return observations


def _looks_like_path(model_path: str) -> bool:
    """Unterscheidet einen lokalen Pfad von einer HuggingFace-Repo-Kennung.

    ``mistralai/Mistral-7B`` ist ein Repo-Name und darf nicht als Verzeichnis
    eingehaengt werden; ``models/foo.gguf`` oder ein absoluter Pfad dagegen schon.
    """
    p = Path(model_path)
    if p.exists():
        return True
    if p.is_absolute():
        return True
    text = str(model_path)
    return text.startswith((".", "~")) or "\\" in text or text.count("/") > 1


class VllmBackend(BenchmarkBackend):
    """Startet vLLM als Container und misst pp/tg/long_context ueber HTTP."""

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
        self.container_name = container_name or backend_setup.container_name("vllm")
        self.volume_name = backend_setup.volume_name("vllm")
        self.container_id: str | None = None
        self.command: str | None = None
        self.base_url: str = str(self.endpoint_cfg.get("base_url") or DEFAULT_BASE_URL)
        self.target_pid: int | None = None
        self._log_path: Path | None = None

    # ------------------------------------------------------------- Container

    def _host_port(self, endpoint_cfg: dict[str, Any]) -> int:
        parsed = urlparse(str(endpoint_cfg.get("base_url") or DEFAULT_BASE_URL))
        return parsed.port or DEFAULT_HOST_PORT

    def _base_url_for(self, endpoint_cfg: dict[str, Any]) -> str:
        return str(endpoint_cfg.get("base_url") or DEFAULT_BASE_URL)

    def _model_reference(self, model_path: str) -> tuple[str, dict[str, str]]:
        """(Modellangabe im Container, Volume-Zuordnung)."""
        volumes: dict[str, str] = {self.volume_name: HF_CACHE_MOUNT}
        if not _looks_like_path(model_path):
            # HuggingFace-Repo-Kennung: vLLM laedt selbst in den Cache.
            return str(model_path), volumes

        p = Path(model_path)
        if p.is_dir():
            volumes[f"{p.resolve()}"] = f"{MODEL_MOUNT}:ro"
            return MODEL_MOUNT, volumes

        parent = p.parent.resolve()
        volumes[f"{parent}"] = f"{MODEL_MOUNT}:ro"
        return f"{MODEL_MOUNT}/{p.name}", volumes

    def _serve_args(
        self,
        model_ref: str,
        profile: dict[str, Any],
        endpoint_cfg: dict[str, Any],
    ) -> list[str]:
        """Argumente fuer ``vllm serve``.

        Das offizielle Image hat ``vllm serve`` als Entrypoint, deshalb werden
        hier nur noch die Optionen uebergeben. ``--model`` statt eines
        positionalen Arguments, damit die Reihenfolge egal ist.
        """
        args = [
            "--model", model_ref,
            "--host", "0.0.0.0",
            "--port", str(CONTAINER_PORT),
        ]
        context_size = endpoint_cfg.get("context_size")
        if context_size:
            args.extend(["--max-model-len", str(int(context_size))])

        tensor_parallel = profile.get("tensor_parallel_size")
        if tensor_parallel:
            args.extend(["--tensor-parallel-size", str(int(tensor_parallel))])
        if profile.get("quantization"):
            args.extend(["--quantization", str(profile["quantization"])])
        if profile.get("gpu_memory_utilization") is not None:
            args.extend(["--gpu-memory-utilization", str(float(profile["gpu_memory_utilization"]))])
        if profile.get("dtype"):
            args.extend(["--dtype", str(profile["dtype"])])

        api_key = endpoint_cfg.get("api_key")
        if api_key:
            args.extend(["--api-key", str(api_key)])
        for item in profile.get("additional_args", []) or []:
            args.append(str(item))
        return args

    def _printable(self, args: list[str]) -> str:
        out = list(args)
        if "--api-key" in out:
            out[out.index("--api-key") + 1] = "***"
        return f"docker run {self.image} " + " ".join(out)

    def _start(
        self,
        model_path: str,
        profile: dict[str, Any],
        endpoint_cfg: dict[str, Any],
        log: Any = None,
    ) -> tuple[str, str]:
        """Gemeinsamer Startpfad fuer begin_profile und start_server."""
        backend_setup.ensure_backend("vllm", self.root, self.image, log=log)

        model_ref, volumes = self._model_reference(model_path)
        args = self._serve_args(model_ref, profile, endpoint_cfg)

        # Ein Rest aus einem abgebrochenen Lauf wuerde den Namen blockieren.
        docker_backend.stop_container(self.container_name, log=log)

        container_id = docker_backend.run_container(
            self.container_name,
            self.image,
            args,
            gpu=True,
            port_map={self._host_port(endpoint_cfg): CONTAINER_PORT},
            volumes=volumes,
            log=log,
            extra_args=["--shm-size", SHM_SIZE],
        )
        self.container_id = container_id
        self.command = self._printable(args)
        self.base_url = self._base_url_for(endpoint_cfg)
        self.target_pid = docker_backend.container_pid(self.container_name)
        return container_id, self.command

    def _stop(self) -> None:
        if self.container_id is None and not docker_backend.container_exists(self.container_name):
            return
        self._capture_logs()
        docker_backend.stop_container(self.container_name)
        self.container_id = None
        self.target_pid = None

    def _capture_logs(self) -> None:
        """Containerausgabe sichern - das Gegenstueck zur llama-server.log."""
        if not self._log_path:
            return
        with contextlib.suppress(Exception):
            text = docker_backend.container_logs(self.container_name)
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_path.write_text(text, encoding="utf-8")

    def _headers(self) -> dict[str, str]:
        return auth_headers(self.endpoint_cfg)

    # -------------------------------------------------------- Profil-Hooks

    def begin_profile(
        self,
        model_path: str,
        profile: dict[str, Any],
        bench_cfg: dict[str, Any],  # noqa: ARG002 - Kontextgroesse kommt aus endpoint_cfg, nicht aus bench_cfg
        out_dir: Path,
    ) -> None:
        """Startet den Server einmal pro Profil statt einmal pro Testart."""
        self._log_path = Path(out_dir) / "vllm-server.log"
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
                f"vLLM-Container wurde nicht bereit: {exc}"
                + (f"\nContainer-Log (Ende):\n{logs[-2000:]}" if logs else "")
            ) from exc

    def end_profile(self) -> None:
        self._stop()

    def collect_kv_cache_observations(
        self,
        model_path: str,  # noqa: ARG002
        profile: dict[str, Any],  # noqa: ARG002
        bench_cfg: dict[str, Any],  # noqa: ARG002
        out_dir: Path,  # noqa: ARG002
        phase: str,
    ) -> list[KvCacheObservation]:
        """Best-effort local metrics/log capture while our container is alive."""
        if self.container_id is None or not docker_backend.container_exists(self.container_name):
            return []
        observations: list[KvCacheObservation] = []
        try:
            import httpx

            response = httpx.get(
                f"{self.base_url.rstrip('/')}/metrics",
                headers=self._headers(), timeout=2.0, follow_redirects=False,
            )
            if response.status_code == 200:
                observations.extend(parse_vllm_cache_metrics(response.text[:512_000], phase=phase))
        except Exception:
            # A metrics endpoint is optional and must never affect benchmark status.
            pass
        with contextlib.suppress(Exception):
            observations.extend(parse_vllm_cache_logs(
                docker_backend.container_logs(self.container_name, tail=400), phase=phase,
            ))
        return observations

    # ------------------------------------------------------------ Messungen

    def run_benchmark(
        self,
        model_path: str,  # noqa: ARG002 - das Modell ist bereits in begin_profile geladen worden
        profile: dict[str, Any],
        kind: str,
        out_dir: Path,
        bench_cfg: dict[str, Any],
        on_progress=None,
    ) -> dict[str, Any]:
        if self.container_id is None:
            return {
                "kind": kind,
                "status": "failed",
                "error": (
                    "Es laeuft kein vLLM-Container. run_benchmark erwartet, dass "
                    "begin_profile den Server bereits gestartet hat."
                ),
            }
        return run_http_bench(
            self.base_url,
            self._headers(),
            bench_cfg,
            profile,
            kind,
            Path(out_dir),
            on_progress=on_progress,
            backend_name="vllm",
            target_pid=self.target_pid,
        )

    # --------------------------------------------------------- Endpoint-Pfad

    def start_server(
        self,
        model_path: str,
        profile: dict[str, Any],
        endpoint_cfg: dict[str, Any],
        bench_cfg: dict[str, Any],  # noqa: ARG002 - vLLM batcht selbst, Batchgroessen sind llama.cpp-spezifisch
        log_path: Path,
    ) -> tuple[Any, str]:
        """Fuer den Endpoint-Lasttest. Liefert den Containernamen als "Prozess"."""
        self.endpoint_cfg = dict(endpoint_cfg or {})
        self._log_path = Path(log_path)
        container_id, command = self._start(model_path, profile, self.endpoint_cfg)
        return _ContainerHandle(self.container_name, container_id, self.target_pid), command

    def stop_server(self, proc: Any) -> None:
        name = getattr(proc, "name", None) or self.container_name
        if self._log_path:
            self._capture_logs()
        docker_backend.stop_container(name)
        self.container_id = None
        self.target_pid = None

    def wait_health(
        self,
        base_url: str,
        timeout_s: float,
        headers: dict[str, str] | None = None,
        proc: Any = None,  # noqa: ARG002 - Container-Status prueft start_server selbst
    ) -> float:
        # vLLMs OpenAI-Server hat /health, ueber das veroeffentlichte Port
        # genauso erreichbar wie bei llama-server - deshalb unveraendert.
        return wait_health(base_url, timeout_s, headers)


class _ContainerHandle:
    """Steht im Endpoint-Pfad an der Stelle, an der llama.cpp ein Popen liefert.

    ``runner.py`` liest von diesem Objekt nur ``pid`` (fuer die Telemetrie) und
    reicht es an ``stop_server`` zurueck.
    """

    def __init__(self, name: str, container_id: str, pid: int | None):
        self.name = name
        self.container_id = container_id
        self.pid = pid
