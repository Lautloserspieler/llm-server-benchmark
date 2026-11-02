"""Sequential backend compatibility checks, with live progress and durable results.

This is a functional smoke test, not a comparable performance benchmark.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import copy
import ipaddress
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import httpx
from huggingface_hub import hf_hub_download
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

# Allow `python scripts/smoke_all_backends.py` from a source checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llmbench import backend_setup, docker_backend, llama_cpp_setup  # noqa: E402
from llmbench.backends import get_backend  # noqa: E402
from llmbench.config import load_config, resolve_path  # noqa: E402
from llmbench.endpoint import api_style_for  # noqa: E402
from llmbench.http_bench import sanity_completion_async  # noqa: E402
from llmbench.utils import auth_headers  # noqa: E402

BACKENDS = ("llama_cpp", "ollama", "vllm", "tgi")
HF_TINY = "Qwen/Qwen2.5-0.5B-Instruct"
PHASES = {
    "prerequisites": "Voraussetzungen pruefen",
    "setup": "Backend automatisch vorbereiten / installieren",
    "model": "Modell vorbereiten (Download beim ersten Lauf)",
    "start": "Server starten / Modell bereitstellen",
    "health": "Auf Serverbereitschaft warten",
    "generation": "Text generieren",
    "cleanup": "Logs sichern und Server aufraeumen",
}
ProgressFn = Callable[[str, str], None]


class MissingPrerequisite(Exception):
    """A backend cannot be tested until a local prerequisite is provided."""


class SmokeProgress:
    """Animate elapsed time even while a blocking backend call is running.

    Phase counts are steps, never an estimate of download or startup duration.
    Redirected output and --no-progress produce stable, readable lines.
    """

    def __init__(self, console: Console, total: int, enabled: bool = True):
        self.console = console
        self.live = enabled and console.is_interactive
        self.progress = Progress(
            SpinnerColumn(), TextColumn("{task.description}"), BarColumn(),
            TextColumn("{task.completed:.0f}/{task.total:.0f}"), TimeElapsedColumn(),
            console=console, disable=not self.live, refresh_per_second=4,
        )
        self.overall = self.progress.add_task("Backends", total=total)
        self.current = None
        self.started = 0.0

    def __enter__(self):
        self.progress.start()
        return self

    def __exit__(self, *_args):
        self.progress.stop()

    def begin(self, name: str) -> None:
        self.started = time.monotonic()
        if self.current is not None:
            self.progress.remove_task(self.current)
        self.current = self.progress.add_task(name, total=len(PHASES))

    def phase(self, name: str, phase: str) -> None:
        index = list(PHASES).index(phase)
        label = f"{name}: {PHASES[phase]}"
        if self.live:
            self.progress.update(self.current, completed=index, description=label)
        else:
            elapsed = time.monotonic() - self.started
            self.console.print(f"[{name}] {index + 1}/{len(PHASES)} {PHASES[phase]} ({elapsed:.1f}s)", markup=False)

    def finish(self, row: dict) -> None:
        # A skipped/failed backend is finished, without claiming all phases passed.
        self.progress.update(self.current, visible=False)
        self.progress.advance(self.overall)
        self.console.print(
            f"[{row['backend']}] {row['status'].upper()} ({row['seconds']:.1f}s): {row['detail']}",
            markup=False,
        )
        if row.get("log"):
            self.message(f"[{row['backend']}] Log: {row['log']}")

    def message(self, message: str) -> None:
        self.console.print(message, markup=False)


def _smallest_catalog_gguf(cfg: dict) -> str:
    custom = cfg.get("_smoke_gguf")
    if custom:
        path = Path(custom).expanduser().resolve()
        if not path.is_file():
            raise MissingPrerequisite(f"GGUF fehlt: {path}")
        return str(path)
    directory = Path(cfg["_config_dir"]) / "models" / "smoke-gemma3-1b"
    cached = directory / "gemma-3-1b-it-Q4_K_M.gguf"
    if cached.is_file() and cached.stat().st_size > 0:
        return str(cached)
    return str(hf_hub_download(
        repo_id="ggml-org/gemma-3-1b-it-GGUF",
        filename="gemma-3-1b-it-Q4_K_M.gguf",
        local_dir=directory,
    ))


def _case(cfg: dict, name: str) -> tuple[str, dict]:
    gpu = _use_gpu(cfg, name)
    if name == "llama_cpp":
        raw = str(cfg["tools"]["llama_server"])
        server = Path(resolve_path(raw, cfg))
        if not server.is_file():
            found = shutil.which(raw)
            if not found:
                raise MissingPrerequisite(f"llama-server fehlt: {server}")
            server = Path(found)
        if not os.access(server, os.X_OK):
            raise MissingPrerequisite(f"llama-server ist nicht ausfuehrbar: {server}")
        if gpu and not _llama_gpu_available(server):
            raise RuntimeError(f"llama-server stellt kein GPU-Geraet bereit: {server}")
        cfg["tools"]["llama_server"] = str(server)
        return _smallest_catalog_gguf(cfg), {"name": "Smoke-GPU" if gpu else "Smoke-CPU",
                                           "gpu_layers": -1 if gpu else 0, "threads": "auto"}
    if name == "ollama":
        profile = {"name": "Smoke-GPU" if gpu else "Smoke-CPU", "gpu_layers": -1 if gpu else 0,
                   "ollama_num_ctx": 2048}
        if not gpu:
            profile["ollama_num_gpu"] = 0
        return "gemma3:1b", profile
    if name == "vllm":
        return HF_TINY, {
            "name": "Smoke-GPU", "gpu_layers": -1, "tensor_parallel_size": 1,
            "gpu_memory_utilization": cfg.get("_smoke_gpu_memory_utilization", 0.5),
            "additional_args": ["--enforce-eager", "--max-num-seqs", "1"],
        }
    return HF_TINY, {
        "name": "Smoke-GPU", "gpu_layers": -1, "tensor_parallel_size": 1,
        "dtype": "float16", "max_input_length": 128, "max_total_tokens": 256,
        "container_memory_gib": 12, "compilation_jobs": 1, "tgi_attention": "torch",
        "additional_args": [
            "--max-concurrent-requests", "1", "--max-best-of", "1",
            "--max-client-batch-size", "1", "--max-batch-size", "1",
            "--max-batch-prefill-tokens", "256", "--max-batch-total-tokens", "256",
            "--cuda-graphs", "0", "--cuda-memory-fraction", "0.5", "--disable-custom-kernels",
        ],
    }


def _use_gpu(cfg: dict, name: str) -> bool:
    device = cfg.get("_smoke_device", "auto")
    if name in {"vllm", "tgi"}:
        if device == "cpu":
            raise MissingPrerequisite(f"{name} braucht in diesem Adapter eine NVIDIA-GPU; CPU-Modus ist nicht verfuegbar")
        return True
    if device == "cpu":
        return False
    available = (docker_backend.nvidia_runtime_available() if name == "ollama"
                 else sys.platform == "darwin" or llama_cpp_setup.looks_like_gpu_present())
    if device == "gpu" and not available:
        raise MissingPrerequisite(f"GPU fuer {name} nicht verfuegbar")
    return available


def _llama_gpu_available(server: Path) -> bool:
    result = subprocess.run([str(server), "--list-devices"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=30, check=False)
    devices = result.stdout + result.stderr
    return result.returncode == 0 and bool(re.search(r"^\s*(?:CUDA|Vulkan|Metal|ROCm|HIP|SYCL)\d*:", devices, re.MULTILINE))


def _prepare_backend(cfg: dict, name: str, log: Callable[[str], None]) -> None:
    root = Path(cfg["_config_dir"])
    gpu = _use_gpu(cfg, name)
    if name != "llama_cpp":
        image = cfg["tools"].get(f"{name}_image") or backend_setup.default_image(name)
        backend_setup.ensure_backend(name, root, image, log=log)
        return
    raw = str(cfg["tools"]["llama_server"])
    server = Path(resolve_path(raw, cfg))
    located = shutil.which(raw)
    if not server.is_file() and located:
        server = Path(located)
    existing = server.is_file() and os.access(server, os.X_OK)
    if existing and (not gpu or _llama_gpu_available(server)):
        log(f"llama-server vorhanden: {server}")
        return
    if existing:
        log("Vorhandener llama-server bietet kein GPU-Geraet; bereite GPU-Build vor...")
    # On Linux, require a GPU build instead of silently installing a CPU fallback.
    key = "LLMBENCH_LLAMACPP_BUILD_BACKEND"
    previous = os.environ.get(key)
    if gpu and sys.platform.startswith("linux") and previous not in {"cuda", "vulkan"}:
        platform = llama_cpp_setup.target_platform()
        os.environ[key] = "cuda" if llama_cpp_setup._prefer_cuda_source(*platform) else "vulkan"
    try:
        if sys.platform == "win32":
            installer = Path(__file__).resolve().parent / "START_BENCHMARK_CORE.ps1"
            log("Starte Windows-Installation fuer llama.cpp...")
            subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-File", str(installer), "-LlamaCppOnly"], check=True)
            state = {"backend": "auto"}
            # The bundled Windows installer prepares the source checkout.
            root = Path(__file__).resolve().parents[1]
        else:
            state = llama_cpp_setup.ensure_llama_cpp(root, force=existing, log=log)
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous
    directory = root / "tools" / "llama.cpp"
    suffix = ".exe" if os.name == "nt" else ""
    cfg["tools"]["llama_server"] = str(directory / f"llama-server{suffix}")
    cfg["tools"]["llama_bench"] = str(directory / f"llama-bench{suffix}")
    log(f"llama.cpp bereit ({state.get('backend', 'auto')})")


def _prerequisite(
    name: str, root: Path, image: str | None = None, *, require_installed: bool = True,
) -> str | None:
    if name == "llama_cpp":
        return None
    if not docker_backend.docker_available():
        return "Docker nicht erreichbar"
    if docker_backend.container_exists(backend_setup.container_name(name)):
        return "Benchmark-Container existiert bereits; bleibt unberuehrt"
    if name in {"vllm", "tgi"} and not docker_backend.nvidia_runtime_available():
        return "NVIDIA-GPU in Docker nicht verfuegbar"
    if not require_installed:
        return None
    state = backend_setup.read_state(name, root)
    install = f"llmbench install-backend --backend {name}"
    if not state:
        return f"Backend nicht installiert ({install})"
    image = image or backend_setup.default_image(name)
    if state.get("image") != image or not docker_backend.image_exists(image):
        return f"Konfiguriertes Image nicht lokal installiert: {image} ({install} --image {image})"
    return None


def _local_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    try:
        local = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = False
    if (parsed.scheme != "http" or not local or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("Smoke-Server brauchen eine lokale HTTP-Adresse, z. B. http://127.0.0.1:8080")
    port = parsed.port if parsed.port is not None else 8080
    if not 1 <= port <= 65535:
        raise ValueError("Port muss zwischen 1 und 65535 liegen")
    return f"http://{'[' + host + ']' if ':' in host else host}:{port}"


def _free_port(base_url: str) -> bool:
    # Binding detects listeners on wildcard interfaces as well as loopback.
    parsed = urlparse(base_url)
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port, type=socket.SOCK_STREAM)
        for family, socktype, proto, _canon, address in addresses:
            with socket.socket(family, socktype, proto) as probe:
                if os.name != "nt":
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                elif hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                probe.bind(address)
        return True
    except OSError:
        return False


def _available_url(base_url: str, fixed: bool = False) -> str:
    if _free_port(base_url):
        return base_url
    if fixed:
        raise RuntimeError(f"Port belegt oder nicht bindbar: {base_url}")
    host = urlparse(base_url).hostname
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        port = probe.getsockname()[1]
    return f"http://{'[' + host + ']' if ':' in host else host}:{port}"


def run_one(
    source: dict, name: str, out: Path, on_progress: ProgressFn | None = None,
    on_message: Callable[[str], None] | None = None,
) -> dict:
    started = time.monotonic()
    row = {
        "backend": name, "status": "failed", "model": None, "detail": "", "seconds": 0.0,
        "phase": "prerequisites", "phases": {}, "log": None, "container": None, "cleanup_error": None,
        "profile": None, "error": None,
    }
    active_phase = None
    phase_started = started

    def phase(key: str) -> None:
        nonlocal active_phase, phase_started
        now = time.monotonic()
        if active_phase:
            row["phases"][active_phase] = round(now - phase_started, 3)
        active_phase, phase_started = key, now
        row["phase"] = key
        if on_progress:
            # Presentation failures (e.g. a closed output pipe) must never
            # prevent server cleanup or recording the backend result.
            with contextlib.suppress(Exception):
                on_progress(name, key)

    cfg = None
    proc = None
    backend = None
    start_attempted = False
    container = None
    log_path = out / f"{name}.log"
    try:
        phase("prerequisites")
        if name not in BACKENDS:
            raise ValueError(f"Unbekanntes Backend: {name}")
        cfg = copy.deepcopy(source)
        cfg["tools"]["backend"] = name
        root = Path(cfg["_config_dir"])
        image = cfg["tools"].get(f"{name}_image") if name != "llama_cpp" else None
        auto_install = cfg.get("_smoke_auto_install", True)
        reason = _prerequisite(name, root, image, require_installed=not auto_install)
        if reason:
            raise MissingPrerequisite(reason)
        original = cfg["endpoint"]
        request_timeout = float(cfg.get("_smoke_request_timeout", 120))
        startup_timeout = float(cfg.get("_smoke_startup_timeout", 600))
        # A smoke test must not inherit chat dialects, min_tokens, server flags,
        # huge batches or cache quantizations from a performance experiment.
        endpoint = {
            "base_url": _local_url(str(original["base_url"])), "api_key": original.get("api_key"),
            "context_size": 2048, "parallel_slots": 1, "timeout_seconds": startup_timeout,
            "max_tokens": 16, "temperature": 0.0, "seed": 42, "ignore_eos": False,
            "chat_format": False, "api_style": "llama_cpp",
        }
        cfg["endpoint"] = endpoint
        bench = {"batch_size": 128, "ubatch_size": 128, "flash_attention": "auto",
                 "cache_type_k": "f16", "cache_type_v": "f16"}
        requested_url = endpoint["base_url"]
        endpoint["base_url"] = _available_url(requested_url, fixed=cfg.get("_smoke_fixed_port", False))
        row["base_url"] = endpoint["base_url"]
        if on_message and endpoint["base_url"] != requested_url:
            on_message(f"[{name}] Standardport belegt; verwende automatisch {endpoint['base_url']}")
        phase("setup")
        if auto_install:
            _prepare_backend(cfg, name, on_message or (lambda message: print(message, flush=True)))
        phase("model")
        model, profile = _case(cfg, name)
        row["model"] = model
        row["profile"] = profile
        row["device"] = "CPU" if profile.get("gpu_layers") == 0 else "GPU"
        if on_message:
            on_message(f"[{name}] Testgeraet: {row['device']}")
        endpoint["model"] = model
        backend = get_backend(cfg)
        if name != "llama_cpp":
            # Adapter startup removes an old container with its own name. Use a
            # unique name so it can never remove a concurrently started benchmark.
            container = f"llmbench-smoke-{name}-{uuid.uuid4().hex[:12]}"
            backend.container_name = container
            row["container"] = container
            if on_message:
                with contextlib.suppress(Exception):
                    on_message(f"[{name}] Container: {container}\nLive-Logs: docker logs -f --tail 100 {container}")
        out.mkdir(parents=True, exist_ok=True)
        log_path.write_text("", encoding="utf-8")
        row["log"] = str(log_path.resolve())
        phase("start")
        start_attempted = True
        proc, _command = backend.start_server(model, profile, endpoint, bench, log_path)
        phase("health")
        backend.wait_health(endpoint["base_url"], startup_timeout, auth_headers(endpoint), proc)
        phase("generation")
        endpoint["timeout_seconds"] = request_timeout
        request_cfg = backend.prepare_endpoint_config(endpoint)

        async def check() -> str:
            async with httpx.AsyncClient(headers=auth_headers(request_cfg), trust_env=False) as client:
                return await asyncio.wait_for(sanity_completion_async(
                    client, endpoint["base_url"], "Antworte mit einem kurzen Satz.",
                    request_cfg, api_style=api_style_for(request_cfg),
                ), timeout=request_timeout)

        answer = asyncio.run(check())
        if not answer.strip():
            raise RuntimeError("API antwortete ohne Text")
        row.update(status="passed", detail="Start, Health und Generierung erfolgreich")
    except MissingPrerequisite as exc:
        row.update(status="skipped", detail=str(exc))
    except KeyboardInterrupt:
        row.update(status="aborted", detail="Vom Benutzer abgebrochen")
    except Exception as exc:
        message = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(exc))
        row["error"] = f"{type(exc).__name__}: {message}"[:16000]
        row["detail"] = f"{type(exc).__name__}: {message.splitlines()[0] if message else 'Unbekannter Fehler'}"[:700]
        if "OOMKilled=true" in message:
            row["detail"] += "; Container wegen Arbeitsspeichermangel beendet"
        else:
            cause = next((line for line in message.splitlines()[1:]
                          if "Free memory on device" in line or "CUDA out of memory" in line), None)
            if cause:
                row["detail"] += "; " + cause[:500]
    finally:
        failed_phase = row["phase"]
        if start_attempted and backend is not None:
            phase("cleanup")
            cleanup_errors = []
            captured_logs = None
            if container:
                try:
                    # Capture before removal, including failures inside start_server.
                    captured_logs = docker_backend.container_logs(container)
                except Exception as exc:
                    cleanup_errors.append(f"Logs sichern: {exc}")
            if proc is not None or container:
                try:
                    backend.stop_server(proc if proc is not None else SimpleNamespace(name=container))
                except Exception as exc:
                    cleanup_errors.append(f"Server stoppen: {exc}")
                    if container:
                        try:
                            docker_backend.stop_container(container)
                        except Exception as retry_exc:
                            cleanup_errors.append(f"Container entfernen: {retry_exc}")
            if captured_logs is not None:
                try:
                    # Adapters also capture logs while stopping. Preserve the
                    # snapshot taken before removal if their later capture fails.
                    log_path.write_text(captured_logs + "\n", encoding="utf-8")
                except Exception as exc:
                    cleanup_errors.append(f"Logs schreiben: {exc}")
            if container:
                try:
                    docker_backend.verify_container_removed(container)
                except Exception as exc:
                    cleanup_errors.append(str(exc))
            if cleanup_errors:
                if row["status"] == "passed":
                    failed_phase = "cleanup"
                row["cleanup_error"] = "; ".join(cleanup_errors)
                row["detail"] += "; Aufraeumen fehlgeschlagen: " + row["cleanup_error"]
                if row["status"] != "aborted":
                    row["status"] = "failed"
        if active_phase:
            row["phases"][active_phase] = round(time.monotonic() - phase_started, 3)
        row["phase"] = "done" if row["status"] == "passed" else failed_phase
        row["seconds"] = round(time.monotonic() - started, 3)
        # Errors from authenticated clients can contain URLs or response bodies.
        secret = (cfg or source).get("endpoint", {}).get("api_key")
        if secret:
            for key in ("detail", "cleanup_error", "error"):
                if row[key]:
                    row[key] = row[key].replace(str(secret), "***")
    return row


def _write_report(report: Path, rows: list[dict]) -> None:
    temporary = report.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(report)


def _summary(console: Console, rows: list[dict]) -> None:
    table = Table(title="Backend-Smoke-Test")
    for column in ("Backend", "Geraet", "Status", "Dauer", "Phase", "Ergebnis"):
        table.add_column(column)
    for row in rows:
        table.add_row(*(Text(str(value)) for value in (
            row["backend"], row.get("device", "—"), row["status"].upper(), f"{row['seconds']:.1f}s", row["phase"], row["detail"],
        )))
    console.print(table)
    counts = {status: sum(row["status"] == status for row in rows) for status in ("passed", "failed", "skipped", "aborted")}
    console.print(" | ".join(f"{status}: {count}" for status, count in counts.items()), markup=False)


def _positive_seconds(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Zeitlimit muss eine positive, endliche Zahl sein")
    return number


def _memory_fraction(value: str) -> float:
    number = _positive_seconds(value)
    if number > 1:
        raise argparse.ArgumentTypeError("GPU-Speicheranteil muss groesser als 0 und hoechstens 1 sein")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backends automatisch vorbereiten und mit Fortschrittsanzeige testen")
    parser.add_argument("--config", default="benchmark.yaml")
    parser.add_argument("--output", default="results/backend-smoke")
    parser.add_argument("--backends", nargs="+", choices=BACKENDS, default=list(BACKENDS))
    parser.add_argument("--base-url", help="Lokale HTTP-Adresse; Standard: endpoint.base_url aus der Konfiguration")
    parser.add_argument("--gguf", help="Vorhandenes GGUF fuer llama.cpp statt automatischem Gemma-Download")
    parser.add_argument("--startup-timeout", type=_positive_seconds, default=600, help="Zeitlimit fuer Bereitschaft/Modell-Pull (Sekunden, Standard: 600)")
    parser.add_argument("--request-timeout", type=_positive_seconds, default=120, help="Zeitlimit fuer Generierung (Sekunden, Standard: 120)")
    parser.add_argument("--gpu-memory-utilization", type=_memory_fraction, default=0.5,
                        help="vLLM-Anteil am gesamten GPU-Speicher (Standard: 0.5)")
    parser.add_argument("--no-progress", action="store_true", help="Einfache Phasenmeldungen statt animierter Anzeige")
    parser.add_argument("--strict", action="store_true", help="Auch uebersprungene Backends als Fehler werten")
    parser.add_argument("--device", choices=("auto", "gpu", "cpu"), default="auto",
                        help="Standard: GPU verwenden, wenn verfuegbar; CPU mit --device cpu erzwingen")
    parser.add_argument("--no-install", action="store_true", help="Fehlende Backends ueberspringen statt installieren")
    args = parser.parse_args(argv)
    console = Console(highlight=False)
    rows = []
    try:
        cfg = load_config(args.config)
        if args.base_url:
            cfg["endpoint"]["base_url"] = args.base_url
        cfg["_smoke_gguf"] = args.gguf
        cfg["_smoke_startup_timeout"] = args.startup_timeout
        cfg["_smoke_request_timeout"] = args.request_timeout
        cfg["_smoke_gpu_memory_utilization"] = args.gpu_memory_utilization
        cfg["_smoke_device"] = args.device
        cfg["_smoke_auto_install"] = not args.no_install
        cfg["_smoke_fixed_port"] = bool(args.base_url)
        out = Path(args.output).resolve()
        out.mkdir(parents=True, exist_ok=True)
        report = out / "report.json"
        _write_report(report, rows)
        names = list(dict.fromkeys(args.backends))
        console.print(f"Funktionscheck: Geraet={args.device} (auto bevorzugt GPU). Keine vergleichbaren Performancewerte.")
        console.print("Fehlende Backends werden automatisch installiert." if not args.no_install else "Automatische Installation deaktiviert.")
        console.print("Modelle werden beim ersten Lauf heruntergeladen und im Cache behalten. Strg+C bricht nach Aufraeumen ab.")
        with SmokeProgress(console, len(names), enabled=not args.no_progress) as progress:
            for name in names:
                progress.begin(name)
                row = run_one(cfg, name, out, on_progress=progress.phase, on_message=progress.message)
                rows.append(row)
                _write_report(report, rows)
                progress.finish(row)
                if row["status"] == "aborted":
                    break
        _summary(console, rows)
        console.print(f"Bericht: {report}", markup=False)
        if any(row["status"] == "aborted" for row in rows):
            return 130
        if any(row["status"] == "failed" for row in rows):
            return 1
        if not any(row["status"] == "passed" for row in rows):
            console.print("Kein Backend konnte getestet werden.")
            return 2
        return 1 if args.strict and any(row["status"] == "skipped" for row in rows) else 0
    except KeyboardInterrupt:
        console.print("Abgebrochen. Bereits gespeicherte Ergebnisse bleiben erhalten.")
        return 130
    except Exception as exc:
        console.print(f"Smoke-Test konnte nicht abgeschlossen werden: {type(exc).__name__}: {exc}", markup=False)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
