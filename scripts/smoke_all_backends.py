"""Run a small, sequential server/API smoke test for every available backend.

This is a compatibility check, not a comparable performance benchmark.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

# Allow `python scripts/smoke_all_backends.py` from a source checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llmbench import backend_setup, docker_backend  # noqa: E402
from llmbench.backends import get_backend  # noqa: E402
from llmbench.config import load_config, resolve_path  # noqa: E402
from huggingface_hub import hf_hub_download  # noqa: E402
from llmbench.endpoint import api_style_for  # noqa: E402
from llmbench.http_bench import sanity_completion_async  # noqa: E402
from llmbench.utils import auth_headers  # noqa: E402

BACKENDS = ("llama_cpp", "ollama", "vllm", "tgi")
HF_TINY = "Qwen/Qwen2.5-0.5B-Instruct"


class MissingPrerequisite(Exception):
    """A backend cannot be tested until a local prerequisite is provided."""


def _smallest_catalog_gguf(cfg: dict) -> str:
    # Gemma 3 1B is the smallest model in our Ollama selection.
    # Download exactly one matching GGUF; HF reuses completed cached files.
    print("[llama_cpp] Bereite Gemma 3 1B Q4_K_M vor (ca. 0.8 GB) ...", flush=True)
    return str(hf_hub_download(
        repo_id="ggml-org/gemma-3-1b-it-GGUF",
        filename="gemma-3-1b-it-Q4_K_M.gguf",
        local_dir=Path(cfg["_config_dir"]) / "models" / "smoke-gemma3-1b",
    ))


def _case(cfg: dict, name: str) -> tuple[str, dict]:
    if name == "llama_cpp":
        server = Path(resolve_path(str(cfg["tools"]["llama_server"]), cfg))
        if not server.is_file():
            raise MissingPrerequisite(f"llama-server fehlt: {server}")
        cfg["tools"]["llama_server"] = str(server)
        model = _smallest_catalog_gguf(cfg)
        return model, {"name": "Smoke-CPU", "gpu_layers": 0, "threads": "auto"}
    if name == "ollama":
        return "gemma3:1b", {"name": "Smoke-CPU", "gpu_layers": 0, "ollama_num_ctx": 2048, "ollama_num_gpu": 0}
    if name == "vllm":
        return HF_TINY, {"name": "Smoke-GPU", "gpu_layers": -1, "tensor_parallel_size": 1,
                         "gpu_memory_utilization": 0.50}
    return HF_TINY, {"name": "Smoke-GPU", "gpu_layers": -1, "tensor_parallel_size": 1}


def _prerequisite(name: str, root: Path) -> str | None:
    if name == "llama_cpp":
        return None
    if not docker_backend.docker_available():
        return "Docker nicht erreichbar"
    if not backend_setup.is_installed(name, root):
        return "Backend nicht installiert (llmbench install-backend --backend " + name + ")"
    if name in {"vllm", "tgi"} and not docker_backend.nvidia_runtime_available():
        return "NVIDIA-GPU in Docker nicht verfuegbar"
    if docker_backend.container_exists(backend_setup.container_name(name)):
        return "Benchmark-Container laeuft bereits; bleibt unberuehrt"
    return None


def _free_port(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return False
    except OSError:
        return True


def _wait_ready(backend, base_url: str, headers: dict, proc, timeout: float = 300) -> None:
    name = getattr(proc, "name", None)
    if not name:
        backend.wait_health(base_url, timeout, headers, proc)
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not docker_backend.container_running(name):
            logs = docker_backend.container_logs(name, tail=80)
            raise RuntimeError(f"Container {name} beim Start beendet.\n{logs}")
        try:
            backend.wait_health(base_url, min(5, deadline - time.monotonic()), headers, proc)
            return
        except TimeoutError:
            continue
    raise TimeoutError(f"Container {name} nach {timeout:g}s nicht bereit")


def run_one(source: dict, name: str, out: Path) -> dict:
    started = time.monotonic()
    row = {"backend": name, "status": "failed", "model": None, "detail": ""}
    root = Path(source["_config_dir"])
    reason = _prerequisite(name, root)
    if reason:
        row.update(status="skipped", detail=reason)
        return row
    cfg = {**source, "tools": {**source["tools"], "backend": name}, "endpoint": dict(source["endpoint"])}
    proc = None
    backend = None
    try:
        endpoint = cfg["endpoint"]
        if not _free_port(str(endpoint["base_url"])):
            raise RuntimeError(f"Port belegt: {endpoint['base_url']}")
        model, profile = _case(cfg, name)
        row["model"] = model
        endpoint["context_size"] = 2048
        endpoint["parallel_slots"] = 1
        endpoint["timeout_seconds"] = 120
        endpoint["max_tokens"] = 16
        if name in {"vllm", "tgi"}:
            endpoint["model"] = model
        backend = get_backend(cfg)
        log_path = out / f"{name}.log"
        proc, _command = backend.start_server(model, profile, endpoint, cfg["benchmark"], log_path)
        _wait_ready(backend, str(endpoint["base_url"]), auth_headers(endpoint), proc)
        request_cfg = backend.prepare_endpoint_config(endpoint)
        async def check() -> str:
            async with httpx.AsyncClient(headers=auth_headers(request_cfg)) as client:
                return await sanity_completion_async(
                    client, str(endpoint["base_url"]), "Antworte mit einem kurzen Satz.",
                    request_cfg, api_style=api_style_for(request_cfg),
                )
        answer = asyncio.run(check())
        if not answer:
            raise RuntimeError("API antwortete ohne Text")
        row.update(status="passed", detail="Start, Health und Generierung erfolgreich")
    except MissingPrerequisite as exc:
        row.update(status="skipped", detail=str(exc))
    except Exception as exc:
        row["detail"] = str(exc)[:500]
    finally:
        if proc is not None and backend is not None:
            try:
                backend.stop_server(proc)
            except Exception as exc:
                row.update(status="failed", detail=f"Aufraeumen fehlgeschlagen: {exc}")
        elif backend is not None and name != "llama_cpp":
            # A container may already exist when model download/startup fails.
            try:
                docker_backend.stop_container(backend_setup.container_name(name))
            except Exception as exc:
                row.update(status="failed", detail=f"Aufraeumen fehlgeschlagen: {exc}")
        row["seconds"] = round(time.monotonic() - started, 1)
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kleiner Start/API-Test aller installierten Backends")
    parser.add_argument("--config", default="benchmark.yaml")
    parser.add_argument("--output", default="results/backend-smoke")
    parser.add_argument("--backends", nargs="+", choices=BACKENDS, default=list(BACKENDS))
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in dict.fromkeys(args.backends):
        print(f"[{name}] Starte kleinen Test ...", flush=True)
        row = run_one(cfg, name, out)
        rows.append(row)
        print(f"[{name}] {row['status'].upper()}: {row['detail']}", flush=True)
    report = out / "report.json"
    report.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Bericht: {report}")
    return 1 if any(row["status"] == "failed" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
