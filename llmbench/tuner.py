from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any

from .capacity import total_gpu_vram_bytes
from .endpoint import run_endpoint_load, start_llama_server, stop_llama_server, wait_health
from .hardware import collect_hardware
from .utils import ensure_dir, print_err


def _max_vram_used_bytes(endpoint_result: dict[str, Any]) -> float | None:
    """Liest die tatsaechliche VRAM-Telemetrie aus dem Endpoint-Ergebnis.

    Die Telemetrie liegt auf Top-Level unter ``telemetry.gpus``. Bei mehreren
    GPUs werden die Maximalbelegungen addiert, passend zum ebenfalls summierten
    Gesamt-VRAM im Tuner.
    """
    gpus = (endpoint_result.get("telemetry") or {}).get("gpus") or []
    values = []
    for gpu in gpus:
        value = gpu.get("max_memory_used_bytes")
        if value is None:
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return sum(values) if values else None


def _measure_performance(
    exe: str,
    model_path: str,
    layers: int,
    endpoint_cfg: dict[str, Any],
    bench_cfg: dict[str, Any],
    out_dir: Path,
) -> tuple[float | None, float | None]:
    """Startet den Server mit x Layers und misst Performance sowie VRAM."""
    profile = {"name": f"tune_{layers}", "gpu_layers": layers}
    endpoint_dir = ensure_dir(out_dir / "tuner_logs")

    proc = None
    try:
        proc, _ = start_llama_server(
            exe,
            model_path,
            profile,
            endpoint_cfg,
            bench_cfg,
            endpoint_dir / f"server_{layers}.log",
        )
        wait_health(
            endpoint_cfg["base_url"],
            float(endpoint_cfg.get("startup_timeout_seconds", 300)),
        )

        ep = run_endpoint_load(
            endpoint_cfg["base_url"],
            endpoint_cfg,
            float(bench_cfg.get("resource_sample_interval", 0.5)),
            endpoint_dir,
            target_pid=proc.pid if proc else None,
        )

        levels = ep.get("levels", [])
        if levels:
            tps = levels[0].get("system_tps")
            return tps, _max_vram_used_bytes(ep)
    except Exception as exc:
        print_err(f"Tuning bei {layers} Layers fehlgeschlagen: {exc}")
    finally:
        if proc is not None:
            stop_llama_server(proc)

    return None, None


def tune_gpu_layers(
    exe: str,
    model_path: str,
    endpoint_cfg: dict[str, Any],
    bench_cfg: dict[str, Any],
    out_dir: Path,
    start_layers: int = 0,
    step: int = 10,
    max_layers: int = 128,
) -> int:
    """Sucht die schnellste stabile gpu_layers-Einstellung bis zum VRAM-Limit."""
    best_layers = start_layers
    best_tps = 0.0

    hw = collect_hardware()
    total_vram = total_gpu_vram_bytes(hw)

    current_layers = start_layers
    while current_layers <= max_layers:
        tps, vram = _measure_performance(
            exe,
            model_path,
            current_layers,
            endpoint_cfg,
            bench_cfg,
            out_dir,
        )

        if tps is None:
            break

        if tps > best_tps:
            best_tps = tps
            best_layers = current_layers

        # Beide Werte sind Bytes. Vorher wurde MiB mit Bytes verglichen und die
        # VRAM-Grenze konnte deshalb nicht korrekt greifen.
        if vram and total_vram > 0 and vram / total_vram > 0.95:
            break

        current_layers += step

    return best_layers
