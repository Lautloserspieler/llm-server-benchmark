from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import config_fingerprint, resolve_path
from .hardware import collect_hardware
from .llama_bench import probe_build
from .utils import command_exists, resolve_executable, run_capture

# Flags, die llmbench an llama-bench uebergibt. Fehlt eines im installierten
# Build, scheitert der Lauf erst nach der ersten langen Messung.
REQUIRED_BENCH_FLAGS = ["-fa", "-ctk", "-ctv", "-d", "-ub", "-ngl"]
OPTIONAL_BENCH_FLAGS = ["-ncmoe", "-nkvo", "-ts", "-dev"]


def _check_flags(exe: str) -> dict[str, Any]:
    try:
        cp = run_capture([exe, "--help"], timeout=30)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    text = (cp.stdout or "") + (cp.stderr or "")
    if not text.strip():
        return {"ok": True, "note": "Hilfetext leer, Flags nicht pruefbar"}
    missing = [f for f in REQUIRED_BENCH_FLAGS if f not in text]
    missing_optional = [f for f in OPTIONAL_BENCH_FLAGS if f not in text]
    return {
        "ok": not missing,
        "missing_required": missing,
        "missing_optional": missing_optional,
    }


def _vram_total_bytes(hardware: dict[str, Any]) -> int | None:
    total = 0
    for gpu in hardware.get("gpus", []):
        value = gpu.get("memory.total")
        if value:
            try:
                total += int(float(value)) * 1024 * 1024  # nvidia-smi liefert MiB
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
    for m in cfg.get("models", []):
        p = Path(resolve_path(m["path"], cfg))
        exists = p.exists()
        size = p.stat().st_size if exists else None
        entry: dict[str, Any] = {
            "name": m.get("name"),
            "path": str(p),
            "exists": exists,
            "size_bytes": size,
        }
        if size and vram:
            # Faustregel: Gewichte plus KV-Cache und Overhead.
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
