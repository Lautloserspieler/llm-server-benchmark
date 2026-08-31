from __future__ import annotations

from typing import Any

from .config import config_fingerprint, resolve_path
from .hardware import collect_hardware
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


def doctor(cfg: dict[str, Any]) -> dict[str, Any]:
    hardware = collect_hardware(resolve_path(cfg["project"]["output_dir"], cfg))
    checks: list[dict[str, Any]] = []

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

    vram = _vram_total_bytes(hardware)
    ram = (hardware.get("memory") or {}).get("total_bytes")
    models = []
    for model in cfg.get("models", []):
        configured_path = resolve_path(model["path"], cfg)
        fingerprint = file_fingerprint(configured_path, with_hash=False)
        exists = bool(fingerprint.get("exists"))
        size = fingerprint.get("size_bytes")
        entry: dict[str, Any] = {
            "name": model.get("name"),
            "path": str(fingerprint.get("path") or configured_path),
            "exists": exists,
            "size_bytes": size,
        }
        if fingerprint.get("shard_count"):
            entry["shard_count"] = fingerprint["shard_count"]
        if fingerprint.get("error"):
            entry["hint"] = str(fingerprint["error"])

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

    return {
        "checks": checks,
        "models": models,
        "hardware": hardware,
        "warnings": warnings,
        "config_fingerprint": config_fingerprint(cfg["benchmark"]),
    }
