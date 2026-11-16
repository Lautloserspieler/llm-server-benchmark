"""Read-only prerequisite checks for the v1.7.0 hardware qualification."""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from llmbench import __version__
from llmbench import backend_setup
from llmbench.backend_setup import DEFAULT_OLLAMA_IMAGE, DEFAULT_VLLM_IMAGE
from llmbench.gpu_backend import runtime_gpu_apis
from llmbench.i18n import _
from llmbench.utils import file_fingerprint, utc_now_compact, utc_now_iso, write_json

ROOT = Path(__file__).resolve().parents[1]
BACKENDS = ("llama_cpp", "ollama", "vllm")
PINNED_IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}@sha256:[0-9a-f]{64}")


def _capture(argv: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _json_probe(argv: list[str]) -> dict[str, Any] | None:
    result = _capture(argv)
    if result is None or result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _executable(value: str, root: Path) -> str | None:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    if path.is_file() and os.access(path, os.X_OK):
        return str(path.resolve())
    # Explicit relative paths belong to root, not to the caller's working dir.
    if Path(value).name == value:
        for name in (value, value + ".exe"):
            installed = root / "tools" / "llama.cpp" / name
            if installed.is_file() and os.access(installed, os.X_OK):
                return str(installed.resolve())
        return shutil.which(value)
    return None


def _check(code: str, passed: bool, **evidence: Any) -> dict[str, Any]:
    return {"code": code, "status": "passed" if passed else "blocked", "evidence": evidence}


def _nvidia_probe() -> dict[str, Any]:
    executable = shutil.which("nvidia-smi")
    result = _capture([executable, "--query-gpu=name,driver_version", "--format=csv,noheader"]) if executable else None
    devices = []
    if result is not None and result.returncode == 0:
        for row in csv.reader(result.stdout.splitlines()):
            if len(row) == 2 and row[0].strip() and re.fullmatch(r"\d+(?:\.\d+){1,3}", row[1].strip()):
                devices.append({"name": row[0].strip(), "driver_version": row[1].strip()})
    # Failure to observe NVIDIA is not proof of CPU-only execution or no GPU.
    return _check("nvidia_driver_observed", bool(devices), devices=devices)


def _binary_probe(value: str, root: Path, device: str) -> dict[str, Any]:
    executable = _executable(value, root)
    if not executable:
        return _check("native_binary", False, name=Path(value).name, reason="unavailable")
    try:
        fingerprint = file_fingerprint(executable, with_hash=True)
    except OSError:
        fingerprint = {}
    evidence = {"name": Path(executable).name, "sha256": fingerprint.get("sha256")}
    if device == "cpu":
        return _check("native_binary", bool(evidence["sha256"]), **evidence)
    result = _capture([executable, "--list-devices"])
    apis = runtime_gpu_apis(result.stdout + "\n" + result.stderr) if result and result.returncode == 0 else []
    # An installer marker or a Vulkan device cannot satisfy a CUDA preflight.
    return _check("native_cuda_device", bool(evidence["sha256"]) and "cuda" in apis, runtime_apis=apis, **evidence)


def _model_probe(value: str | None, root: Path, with_hash: bool) -> dict[str, Any]:
    if not value:
        return _check("local_gguf", False, reason="not_selected")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    try:
        if not path.is_file():
            return _check("local_gguf", False, reason="unavailable")
        fingerprint = file_fingerprint(path, with_hash=with_hash)
        logical = Path(fingerprint.get("path", path))
        with logical.open("rb") as stream:
            header_ok = stream.read(4) == b"GGUF"
    except OSError:
        return _check("local_gguf", False, reason="unreadable")
    passed = bool(fingerprint.get("exists") and header_ok and fingerprint.get("size_bytes", 0) > 4)
    passed = passed and (not with_hash or bool(fingerprint.get("sha256")))
    return _check("local_gguf", passed, name=logical.name,
                  size_bytes=fingerprint.get("size_bytes"), shard_count=fingerprint.get("shard_count", 1),
                  sha256=fingerprint.get("sha256"), hash_requested=with_hash,
                  validation="header_and_local_files_only")


def _image_probe(docker: str, image: str) -> dict[str, Any]:
    if not PINNED_IMAGE.fullmatch(image):
        # Do not echo invalid references, which could contain credentials.
        return _check("pinned_local_image", False, reason="digest_pin_required")
    data = _json_probe([docker, "image", "inspect", image, "--format", "{{json .}}"])
    expected = image.rsplit("@", 1)[-1]
    digests = data.get("RepoDigests") if data else None
    observed_os = data.get("Os") if data else None
    known_os = observed_os if isinstance(observed_os, str) and observed_os in {"linux", "windows"} else None
    matched = isinstance(digests, list) and any(
        isinstance(item, str) and item.endswith("@" + expected) for item in digests
    )
    return _check("pinned_local_image", bool(matched and data and data.get("Os") == "linux"),
                  reference=image, digest=expected, locally_observed=bool(data),
                  digest_matched=matched, os=known_os)


def inspect_prerequisites(
    *, root: Path, backends: list[str], device: str,
    llama_bench: str = "llama-bench", llama_server: str = "llama-server",
    gguf: str | None = None, hash_model: bool = False,
    ollama_image: str = DEFAULT_OLLAMA_IMAGE, vllm_image: str = DEFAULT_VLLM_IMAGE,
) -> dict[str, Any]:
    """Collect prerequisites only; never install, start, stop or qualify a runtime."""
    if not backends or any(backend not in BACKENDS for backend in backends) or device not in {"cpu", "cuda"}:
        raise ValueError("invalid_preflight_target")
    selected = list(dict.fromkeys(backends))
    needs_docker = any(name != "llama_cpp" and not (name == "vllm" and device == "cpu") for name in selected)
    docker = shutil.which("docker") if needs_docker else None
    docker_info = _json_probe([docker, "info", "--format", "{{json .}}"]) if docker else None
    server_version = docker_info.get("ServerVersion") if docker_info else None
    if not isinstance(server_version, str):
        server_version = None
    nvidia = _nvidia_probe() if device == "cuda" else None
    results: list[dict[str, Any]] = []
    for name in selected:
        checks = []
        if name == "vllm" and device == "cpu":
            results.append({"backend": name, "status": "not_applicable", "reason": "vllm_cpu_not_supported", "checks": []})
            continue
        if nvidia:
            checks.append(nvidia)
        if name == "llama_cpp":
            checks.extend([_binary_probe(llama_bench, root, device), _binary_probe(llama_server, root, device),
                           _model_probe(gguf, root, hash_model)])
        else:
            image = ollama_image if name == "ollama" else vllm_image
            state = backend_setup.read_state(name, root)
            checks.append(_check("backend_install_state", isinstance(state, dict) and state.get("image") == image))
            checks.append(_check("linux_docker_engine", bool(docker_info and docker_info.get("OSType") == "linux"),
                                 reachable=docker_info is not None, version=server_version))
            if docker and docker_info and docker_info.get("OSType") == "linux":
                checks.append(_image_probe(docker, image))
                if device == "cuda" and sys.platform.startswith("linux"):
                    runtimes = docker_info.get("Runtimes")
                    checks.append(_check("docker_nvidia_runtime_declared", isinstance(runtimes, dict) and "nvidia" in runtimes))
        results.append({"backend": name, "status": "ready" if all(c["status"] == "passed" for c in checks) else "blocked",
                        "checks": checks, "model_load": "not_tested", "gpu_passthrough": "not_tested"})

    statuses = {result["status"] for result in results}
    readiness = "blocked" if "blocked" in statuses else "partial" if "not_applicable" in statuses else "ready"
    commit = _capture(["git", "-C", str(root), "rev-parse", "HEAD"])
    dirty = _capture(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=normal"])
    commit_sha = commit.stdout.strip() if commit and commit.returncode == 0 else None
    if commit_sha is not None and not re.fullmatch(r"[a-f0-9]{40,64}", commit_sha):
        commit_sha = None
    return {
        "schema_version": 1, "scope": "prerequisites_only", "release": "1.7.0",
        "captured_at": utc_now_iso(), "qualification_status": "not_run", "readiness_status": readiness,
        "source": {"commit": commit_sha, "dirty": bool(dirty.stdout) if dirty and dirty.returncode == 0 else None,
                   "llmbench_version": __version__},
        "host": {"system": platform.system(), "architecture": platform.machine(), "python": platform.python_version()},
        "target": {"device": device, "backends": selected}, "backends": results,
        "remaining_evidence": ["model_identity_and_revision", "actual_backend_execution", "start_stop_cycles",
                               "ollama_versions_and_context", "vendor_telemetry", "five_reference_repeats", "eight_hour_soak"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=_("Voraussetzungen fuer die Hardwarequalifikation pruefen; keine Installation oder Benchmarks."))
    parser.add_argument("--backends", nargs="+", choices=BACKENDS, default=list(BACKENDS))
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--root", type=Path, default=ROOT, help=_("Projektwurzel fuer relative Werkzeug- und Modellpfade"))
    parser.add_argument("--output", type=Path, help=_("Neues Ausgabeverzeichnis; vorhandene Verzeichnisse bleiben unveraendert"))
    parser.add_argument("--llama-bench", default="llama-bench")
    parser.add_argument("--llama-server", default="llama-server")
    parser.add_argument("--gguf", help=_("Vorhandenes lokales GGUF fuer llama.cpp; kein Download"))
    parser.add_argument("--hash-model", action="store_true", help=_("Optional SHA-256 des lokalen GGUF-Satzes berechnen"))
    parser.add_argument("--ollama-image", default=DEFAULT_OLLAMA_IMAGE)
    parser.add_argument("--vllm-image", default=DEFAULT_VLLM_IMAGE)
    args = parser.parse_args(argv)
    output = args.output or args.root / "results" / "qualification" / f"preflight-{utc_now_compact()}-{uuid.uuid4().hex[:8]}"
    if output.exists() or output.is_symlink():
        parser.error(_("Das Ausgabeverzeichnis existiert bereits; einen neuen Pfad waehlen."))
    try:
        report = inspect_prerequisites(root=args.root.resolve(), backends=args.backends, device=args.device,
                                       llama_bench=args.llama_bench, llama_server=args.llama_server,
                                       gguf=args.gguf, hash_model=args.hash_model,
                                       ollama_image=args.ollama_image, vllm_image=args.vllm_image)
        # Own a fresh directory before atomically writing the report; never
        # replace an earlier run, even when two callers choose the same output.
        output.mkdir(parents=True, exist_ok=False)
        write_json(output / "report.json", report)
    except OSError:
        print(_("Vorpruefung oder Bericht konnte nicht abgeschlossen werden."), file=sys.stderr)
        return 1
    labels = {"ready": _("bereit"), "blocked": _("blockiert"), "partial": _("teilweise pruefbar")}
    print(_("Vorpruefung: {status}. Bericht: {path}").format(status=labels[report["readiness_status"]], path=output / "report.json"))
    print(_("Hardwarequalifikation wurde nicht ausgefuehrt; keine Freigabe durch diese Vorpruefung."))
    return 0 if report["readiness_status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
