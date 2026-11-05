from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from . import model_catalog
from .config import config_fingerprint, resolve_path
from .hardware import collect_hardware, linux_power_state
from .llama_bench import probe_build
from .utils import command_exists, file_fingerprint, resolve_executable, run_capture

REQUIRED_BENCH_FLAGS = {
    "-fa": "--flash-attn",
    "-ctk": "--cache-type-k",
    "-ctv": "--cache-type-v",
    "-d": "--n-depth",
    "-b": "--batch-size",
    "-ub": "--ubatch-size",
    "-ngl": "--n-gpu-layers",
    "-r": "--repetitions",
}
OPTIONAL_BENCH_FLAGS = {
    "-ncmoe": "--n-cpu-moe",
    "-nkvo": "--no-kv-offload",
    "-ts": "--tensor-split",
    "-dev": "--device",
}


def _check_flags(exe: str) -> dict[str, Any]:
    try:
        cp = run_capture([exe, "--help"], timeout=30)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    text = (cp.stdout or "") + (cp.stderr or "")
    if not text.strip():
        return {"ok": True, "note": "Hilfetext leer, Flags nicht pruefbar"}
    missing = [short for short, long in REQUIRED_BENCH_FLAGS.items() if long not in text]
    missing_optional = [short for short, long in OPTIONAL_BENCH_FLAGS.items() if long not in text]
    result = {
        "ok": not missing,
        "missing_required": missing,
        "missing_optional": missing_optional,
    }
    if "--flash-attn" in text:
        result["flash_attn_values"] = "on|off|auto" if "on|off|auto" in text else "unbekannt"
    return result


def _looks_like_ollama_tag(value: str) -> bool:
    return ":" in value and "/" not in value.split(":", 1)[0] and not value.lower().endswith(".gguf") and "\\" not in value


def _looks_like_hf_repo(value: str) -> bool:
    return value.count("/") == 1 and not value.startswith((".", "~", "/")) and not value.lower().endswith(".gguf")


def check_model_reference(backend: str, raw_path: str, exists: bool) -> dict[str, str] | None:
    """Does the configured model reference fit the configured backend?

    Typical mistake: a backend switched to llama.cpp while the config still holds an
    Ollama tag (``gemma3:1b``) - llama-server then fails at start with "file not found",
    although everything looked fine before.
    """
    value = raw_path.strip()
    if backend == "llama_cpp":
        if not exists and (_looks_like_ollama_tag(value) or _looks_like_hf_repo(value)):
            kind = "Ollama-Modell-ID" if _looks_like_ollama_tag(value) else "Hugging-Face-Repo-ID"
            return {
                "level": "error",
                "message": (
                    f"'{value}' ist eine {kind}, llama.cpp braucht aber eine GGUF-Datei. "
                    "`llmbench setup` waehlt das passende Modell fuer dieses Backend."
                ),
            }
        if exists and not value.lower().endswith(".gguf") and not Path(value).is_dir():
            return {"level": "warning", "message": f"'{value}' ist keine .gguf-Datei."}
    elif backend == "ollama":
        # Ollama also accepts namespaced tags (`user/model:tag`) and `hf.co/...`, so this is only a hint.
        if _looks_like_hf_repo(value) and ":" not in value and not value.lower().startswith("hf.co/"):
            return {
                "level": "warning",
                "message": (
                    f"'{value}' sieht wie eine Hugging-Face-Repo-ID aus, Ollama erwartet ein Library-Tag "
                    "wie `qwen3:8b` oder eine lokale GGUF-Datei. `llmbench setup` waehlt das passende Modell."
                ),
            }
    elif backend in {"vllm", "tgi"} and _looks_like_ollama_tag(value) and not exists:
        return {
            "level": "error",
            "message": (
                f"'{value}' ist eine Ollama-Modell-ID, {backend} braucht eine Hugging-Face-Repo-ID (org/name) "
                "oder ein Transformers-Verzeichnis. `llmbench setup` waehlt das passende Modell."
            ),
        }
    return None


def catalog_warning(backend: str, model: dict[str, Any]) -> str | None:
    """Warn when a model is not part of the shared catalog (not comparable across backends)."""
    reference = str(model.get("path") or "")
    if model.get("catalog_id") or model_catalog.identify(reference, backend) is not None:
        return None
    return (
        f"Modell '{model.get('name')}' ist nicht im gemeinsamen Modellkatalog. Ergebnisse lassen sich nur mit "
        "Laeufen vergleichen, die genau dieses Modell nutzen; auf anderen Backends ist es ggf. nicht verfuegbar."
    )


def _vram_total_bytes(hardware: dict[str, Any]) -> int | None:
    total = 0
    for gpu in hardware.get("gpus", []):
        value = gpu.get("memory.total")
        if value:
            try:
                total += int(float(value)) * 1024 * 1024
            except (TypeError, ValueError):
                continue
    return total or None


def _power_state_warning() -> str | None:
    """Warnt, wenn der aktive Energiesparmodus unter Linux die Messwerte verfaelscht.

    Ubuntu Desktop (z. B. 24.04 LTS) laeuft standardmaessig ueber
    `power-profiles-daemon` im Profil "balanced", nicht "performance" -
    im Unterschied zu vielen Headless-Servern mit festem `cpupower`-Governor.
    Das kostet reproduzierbar Tokens/s und wird beim Serververgleich leicht
    uebersehen.
    """
    if not sys.platform.startswith("linux"):
        return None
    state = linux_power_state()
    profile = state.get("profile")
    if profile:
        if profile == "performance":
            return None
        return (
            f"power-profiles-daemon-Profil ist '{profile}', nicht 'performance'. "
            "Das kostet Tokens/s und verfaelscht Serververgleiche. "
            "Vor dem Benchmark: sudo powerprofilesctl set performance "
            "(oder `llmbench performance on`; `llmbench run` stellt das automatisch um)."
        )
    governors = state.get("governors")
    if governors and "performance" not in governors:
        return (
            "CPU-Governor ist " + ",".join(governors) + ", nicht 'performance'. "
            "Das kostet Tokens/s und verfaelscht Serververgleiche. "
            "Vor dem Benchmark: sudo cpupower frequency-set -g performance "
            "(oder `llmbench performance on`; `llmbench run` stellt das automatisch um)."
        )
    return None


def doctor(cfg: dict[str, Any]) -> dict[str, Any]:
    hardware = collect_hardware(resolve_path(cfg["project"]["output_dir"], cfg))
    checks: list[dict[str, Any]] = []
    backend = str((cfg.get("tools") or {}).get("backend") or "llama_cpp")

    if backend == "llama_cpp":
        for key in ("llama_bench", "llama_server"):
            value = cfg.get("tools", {}).get(key)
            ok = command_exists(value)
            item: dict[str, Any] = {"name": key, "configured": value, "ok": ok}
            if ok:
                try:
                    exe = resolve_executable(value)
                    item["resolved"] = exe
                    if key == "llama_bench":
                        flags = _check_flags(exe)
                        item["flags"] = flags
                        if not flags.get("ok"):
                            item["ok"] = False
                            item["error"] = (
                                "Der installierte Build kennt folgende benoetigte Optionen nicht: "
                                + ", ".join(flags.get("missing_required", []))
                            )
                        item["build"] = probe_build(exe, with_hash=False)
                except Exception as exc:
                    item["ok"] = False
                    item["error"] = str(exc)
            checks.append(item)
    else:
        from . import backend_setup, docker_backend

        docker_ok = docker_backend.docker_available()
        installed = backend in backend_setup.SUPPORTED_BACKENDS and backend_setup.is_installed(
            backend, cfg.get("_config_dir") or "."
        )
        checks.append({
            "name": f"{backend}_backend",
            "configured": backend,
            "resolved": backend_setup.default_image(backend) if backend in backend_setup.SUPPORTED_BACKENDS else None,
            "ok": docker_ok and installed,
            "error": None if docker_ok and installed else (
                "Docker ist nicht verfuegbar." if not docker_ok else
                f"Backend '{backend}' ist nicht installiert."
            ),
        })

    vram = _vram_total_bytes(hardware)
    ram = (hardware.get("memory") or {}).get("total_bytes")
    models = []
    for model in cfg.get("models", []):
        raw_path = str(model["path"])
        path_obj = Path(raw_path)
        is_runtime_reference = (
            backend != "llama_cpp"
            and not path_obj.exists()
            and not path_obj.is_absolute()
            and not raw_path.startswith((".", "~"))
            and "\\" not in raw_path
        )
        if is_runtime_reference:
            fingerprint = {"exists": True, "path": raw_path, "size_bytes": None}
            configured_path = raw_path
        else:
            configured_path = resolve_path(raw_path, cfg)
            fingerprint = file_fingerprint(configured_path, with_hash=False)
        exists = bool(fingerprint.get("exists"))
        raw_size = fingerprint.get("size_bytes")
        size = int(raw_size) if isinstance(raw_size, (int, float)) else None
        entry: dict[str, Any] = {
            "name": model.get("name"),
            "path": str(fingerprint.get("path") or configured_path),
            "exists": exists,
            "size_bytes": size,
        }
        if is_runtime_reference:
            entry["hint"] = "Runtime-Modellreferenz; Verfuegbarkeit wird beim Backend-Start geprueft."
        if fingerprint.get("shard_count"):
            entry["shard_count"] = fingerprint["shard_count"]
        if fingerprint.get("error"):
            entry["hint"] = str(fingerprint["error"])

        problem = check_model_reference(backend, raw_path, exists)
        if problem:
            entry["problem"] = problem
            entry["hint"] = problem["message"]
        if size and vram:
            entry["fits_in_vram"] = size * 1.2 <= vram
            if not entry["fits_in_vram"]:
                entry["hint"] = (
                    "Passt vermutlich nicht vollstaendig in den VRAM. Full-GPU-Profil "
                    "wird auf CPU ausweichen oder scheitern."
                )
        if size and ram and size * 1.2 > ram and not (vram and size * 1.2 <= vram):
            entry["hint"] = "Modell ist groesser als der verfuegbare Arbeitsspeicher."
        models.append(entry)

    disk = hardware.get("disk") or {}
    free = disk.get("free_bytes")
    warnings: list[str] = []
    for model in cfg.get("models", []):
        warning = catalog_warning(backend, model)
        if warning:
            warnings.append(warning)
    if free is not None and free < 2 * 1024**3:
        warnings.append(
            f"Nur noch {free / 1024**3:.1f} GiB frei unter {disk.get('root')}. "
            "Rohdaten und Telemetrie eines Laufs brauchen mehrere hundert Megabyte."
        )
    if not hardware.get("gpus"):
        warnings.append("Keine GPU erkannt. Es wird ausschliesslich auf der CPU gemessen.")
    for gpu in hardware.get("gpus", []):
        if gpu.get("telemetry") == "none":
            warnings.append(
                f"Fuer {gpu.get('vendor')} {gpu.get('name')} gibt es keine Telemetrie. "
                "Auslastung, VRAM und Leistungsaufnahme bleiben leer."
            )
    power_warning = _power_state_warning()
    if power_warning:
        warnings.append(power_warning)

    return {
        "checks": checks,
        "models": models,
        "hardware": hardware,
        "warnings": warnings,
        "config_fingerprint": config_fingerprint(cfg["benchmark"]),
    }
