from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .endpoint import run_endpoint_load, start_llama_server, stop_llama_server, wait_health
from .hardware import collect_hardware
from .utils import ensure_dir

def _measure_performance(
    exe: str,
    model_path: str,
    layers: int,
    endpoint_cfg: dict[str, Any],
    bench_cfg: dict[str, Any],
    out_dir: Path,
) -> tuple[float | None, float | None]:
    """Startet den Server mit x Layers und misst die Performance."""
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

        # Kurzer Testlauf fuer TPS-Messung
        ep = run_endpoint_load(
            endpoint_cfg["base_url"],
            endpoint_cfg,
            float(bench_cfg.get("resource_sample_interval", 0.5)),
            endpoint_dir,
            target_pid=proc.pid if proc else None,
        )

        # System TPS aus dem ersten Level (concurrency 1)
        levels = ep.get("levels", [])
        if levels:
            tps = levels[0].get("system_tps")
            vram_max = levels[0].get("telemetry", {}).get("max_memory_used_bytes")
            return tps, vram_max

    except Exception:
        pass
    finally:
        if proc:
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
    """
    Sucht die optimalen gpu_layers durch inkrementelles Erhoehen,
    bis OOM auftritt oder max_layers erreicht ist.
    """
    best_layers = start_layers
    best_tps = 0.0

    # Hardware-Info fuer VRAM-Limit
    hw = collect_hardware()
    total_vram = 0
    for g in hw.get("gpus", []):
        total_vram += g.get("memory.total", 0)

    current_layers = start_layers
    while current_layers <= max_layers:
        tps, vram = _measure_performance(
            exe, model_path, current_layers, endpoint_cfg, bench_cfg, out_dir
        )

        if tps is None:
            # OOM oder Startfehler
            break

        if tps > best_tps:
            best_tps = tps
            best_layers = current_layers

        # Wenn VRAM fast voll ist (95%), stoppen
        if vram and total_vram > 0 and vram / total_vram > 0.95:
            break

        current_layers += step

    return best_layers
