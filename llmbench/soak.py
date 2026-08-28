"""Dauerlast-Test: haelt einen CPU-Only- und einen GPU-Server gleichzeitig
unter Last, um thermisches Throttling sichtbar zu machen.

Die kurzen pp/tg-Tests (llama_bench.py) sind abgeschlossen, bevor die
Hardware ueberhaupt ins thermische Gleichgewicht kommt. Dieser Test laesst
beide Pfade parallel laufen - genau wie im echten Mehrbenutzerbetrieb, wenn
ein Server sowohl GPU- als auch CPU-Anfragen gleichzeitig bedient - und
sampelt Temperatur, Leistungsaufnahme und Tokens/s durchgehend ueber die
gesamte Laufzeit.
"""

from __future__ import annotations

import asyncio
import contextlib
import statistics
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from .monitor import ResourceMonitor, strip_samples
from .utils import ensure_dir, utc_now_iso, write_json

_REQUEST_TIMEOUT_SECONDS = 120.0
_TICK_INTERVAL_SECONDS = 2.0


async def _one_completion(client: httpx.AsyncClient, base_url: str, cfg: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prompt": cfg["prompt"],
        "n_predict": int(cfg["max_tokens"]),
        "temperature": float(cfg.get("temperature", 0.0)),
        "stream": False,
        "cache_prompt": False,
    }
    if cfg.get("seed") is not None:
        payload["seed"] = int(cfg["seed"])

    started = time.perf_counter()
    try:
        r = await client.post(
            base_url.rstrip("/") + "/completion", json=payload, timeout=_REQUEST_TIMEOUT_SECONDS
        )
        r.raise_for_status()
        data = r.json()
        duration = time.perf_counter() - started
        timings = data.get("timings") or {}
        tokens = timings.get("predicted_n") or timings.get("tokens_predicted") or 0
        tokens = int(tokens) if tokens else len((data.get("content") or "").split())
        return {
            "ok": True,
            "duration_seconds": duration,
            "output_tokens": tokens,
            "tps": (tokens / duration) if duration > 0 and tokens else 0.0,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "duration_seconds": time.perf_counter() - started}


async def _worker_loop(
    client: httpx.AsyncClient,
    base_url: str,
    cfg: dict[str, Any],
    deadline: float,
    start_ts: float,
    results: list[dict[str, Any]],
    lock: asyncio.Lock,
) -> None:
    while time.perf_counter() < deadline:
        result = await _one_completion(client, base_url, cfg)
        result["elapsed_seconds"] = time.perf_counter() - start_ts
        async with lock:
            results.append(result)
        # Kooperativer Yield-Punkt: eine sehr schnell antwortende Gegenstelle
        # (oder ein Mock in Tests) kann sonst die Event-Loop fuer sich behalten
        # und den parallel laufenden CPU- bzw. GPU-Pfad verhungern lassen.
        await asyncio.sleep(0)


async def _drive_load(base_url: str, cfg: dict[str, Any], duration_seconds: float) -> list[dict[str, Any]]:
    start_ts = time.perf_counter()
    deadline = start_ts + duration_seconds
    results: list[dict[str, Any]] = []
    lock = asyncio.Lock()
    async with httpx.AsyncClient() as client:
        workers = [
            _worker_loop(client, base_url, cfg, deadline, start_ts, results, lock)
            for _ in range(max(1, int(cfg.get("concurrency", 1))))
        ]
        await asyncio.gather(*workers)
    return results


async def _tick_loop(
    deadline: float, monitor: ResourceMonitor, on_tick: Callable[[float, dict[str, Any] | None], None] | None
) -> None:
    if not on_tick:
        return
    while time.perf_counter() < deadline:
        remaining = max(0.0, deadline - time.perf_counter())
        with contextlib.suppress(Exception):
            on_tick(remaining, monitor.latest())
        await asyncio.sleep(_TICK_INTERVAL_SECONDS)


async def _drive_both(
    cpu_url: str,
    gpu_url: str,
    soak_cfg: dict[str, Any],
    duration_seconds: float,
    monitor: ResourceMonitor,
    on_tick: Callable[[float, dict[str, Any] | None], None] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    deadline = time.perf_counter() + duration_seconds
    cpu_results, gpu_results, _ = await asyncio.gather(
        _drive_load(cpu_url, soak_cfg, duration_seconds),
        _drive_load(gpu_url, soak_cfg, duration_seconds),
        _tick_loop(deadline, monitor, on_tick),
    )
    return cpu_results, gpu_results


def _bucket_avg_tps(ok_results: list[dict[str, Any]], lo_frac: float, hi_frac: float, duration_seconds: float) -> float | None:
    lo, hi = duration_seconds * lo_frac, duration_seconds * hi_frac
    window = [r["tps"] for r in ok_results if lo <= r["elapsed_seconds"] <= hi and r.get("tps")]
    return statistics.fmean(window) if window else None


def _summarize_load(
    results: list[dict[str, Any]], duration_seconds: float, throttle_drop_fraction: float
) -> dict[str, Any]:
    ok = [r for r in results if r.get("ok")]
    summary: dict[str, Any] = {
        "requests": len(results),
        "successful": len(ok),
        "failed": len(results) - len(ok),
        "total_output_tokens": sum(r.get("output_tokens", 0) for r in ok),
        "throttling_suspected": False,
    }
    tps_values = [r["tps"] for r in ok if r.get("tps")]
    summary["avg_tps"] = statistics.fmean(tps_values) if tps_values else None
    if not ok:
        summary["note"] = "Keine erfolgreichen Anfragen."
        return summary

    # Erstes Zehntel als Aufwaermphase ausgenommen: frueh im Fenster [10%,30%)
    # gegen spaet im Fenster [70%,100%] vergleichen, um einen Leistungsabfall
    # ueber die Laufzeit zu erkennen, wie er bei Temperatur-Throttling auftritt.
    early = _bucket_avg_tps(ok, 0.1, 0.3, duration_seconds)
    late = _bucket_avg_tps(ok, 0.7, 1.0, duration_seconds)
    summary["early_window_avg_tps"] = early
    summary["late_window_avg_tps"] = late
    if early and late and early > 0:
        drop = (early - late) / early
        summary["tps_drop_fraction"] = drop
        if drop >= throttle_drop_fraction:
            summary["throttling_suspected"] = True
            summary["note"] = (
                f"Tokens/s sind von frueh ({early:.1f} t/s) zu spaet im Lauf ({late:.1f} t/s) "
                f"um {drop * 100:.0f}% gefallen - moeglicherweise thermisches Throttling."
            )
    return summary


def run_soak_test(
    backend: Any,
    model_path: str,
    cpu_profile: dict[str, Any],
    gpu_profile: dict[str, Any],
    soak_cfg: dict[str, Any],
    bench_cfg: dict[str, Any],
    out_dir: Path,
    duration_seconds: int,
    label: str,
    on_tick: Callable[[float, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    """Startet CPU- und GPU-Server gleichzeitig, haelt beide fuer
    `duration_seconds` unter Last und sampelt Telemetrie durchgehend."""
    host = soak_cfg.get("host", "127.0.0.1")
    cpu_url = f"http://{host}:{soak_cfg['cpu_port']}"
    gpu_url = f"http://{host}:{soak_cfg['gpu_port']}"
    log_dir = ensure_dir(out_dir / f"soak_{label}")
    started_at = utc_now_iso()
    started = time.perf_counter()

    cpu_proc = gpu_proc = None
    load_cfg = {
        "prompt": soak_cfg.get("prompt"),
        "max_tokens": soak_cfg.get("max_tokens", 256),
        "temperature": soak_cfg.get("temperature", 0.0),
        "seed": soak_cfg.get("seed"),
        "concurrency": soak_cfg.get("concurrency", 2),
    }
    try:
        cpu_endpoint_cfg = {
            "base_url": cpu_url,
            "context_size": soak_cfg.get("context_size", 8192),
            "parallel_slots": soak_cfg.get("concurrency", 2),
        }
        gpu_endpoint_cfg = {
            "base_url": gpu_url,
            "context_size": soak_cfg.get("context_size", 8192),
            "parallel_slots": soak_cfg.get("concurrency", 2),
        }
        cpu_proc, _cpu_cmd = backend.start_server(
            model_path, cpu_profile, cpu_endpoint_cfg, bench_cfg, log_dir / "cpu-server.log"
        )
        gpu_proc, _gpu_cmd = backend.start_server(
            model_path, gpu_profile, gpu_endpoint_cfg, bench_cfg, log_dir / "gpu-server.log"
        )
        startup_timeout = float(soak_cfg.get("startup_timeout_seconds", 300))
        backend.wait_health(cpu_url, startup_timeout)
        backend.wait_health(gpu_url, startup_timeout)

        monitor = ResourceMonitor(float(soak_cfg.get("sample_interval_seconds", 2.0)))
        monitor.set_target_pids([pid for pid in (getattr(cpu_proc, "pid", None), getattr(gpu_proc, "pid", None)) if pid])
        monitor.start()

        cpu_results, gpu_results = asyncio.run(
            _drive_both(cpu_url, gpu_url, load_cfg, float(duration_seconds), monitor, on_tick)
        )
        wall = time.perf_counter() - started
        telemetry = monitor.stop()
    except Exception as exc:
        return {
            "kind": "soak",
            "label": label,
            "status": "failed",
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "started_at": started_at,
            "duration_seconds": time.perf_counter() - started,
        }
    finally:
        if gpu_proc is not None:
            backend.stop_server(gpu_proc)
        if cpu_proc is not None:
            backend.stop_server(cpu_proc)

    drop_fraction = float(soak_cfg.get("throttle_tps_drop_fraction", 0.15))
    cpu_summary = _summarize_load(cpu_results, float(duration_seconds), drop_fraction)
    gpu_summary = _summarize_load(gpu_results, float(duration_seconds), drop_fraction)

    result = {
        "kind": "soak",
        "label": label,
        "status": "ok",
        "started_at": started_at,
        "duration_seconds": wall,
        "requested_duration_seconds": duration_seconds,
        "cpu_profile": cpu_profile.get("name"),
        "gpu_profile": gpu_profile.get("name"),
        "cpu": cpu_summary,
        "gpu": gpu_summary,
        "throttling_suspected": bool(cpu_summary["throttling_suspected"] or gpu_summary["throttling_suspected"]),
        "telemetry": strip_samples(telemetry),
    }
    write_json(log_dir / "raw_soak.json", {**result, "telemetry": telemetry})
    return result


def find_soak_profiles(model: dict[str, Any], soak_cfg: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Waehlt CPU- und GPU-Profil fuer den Soak-Test.

    Explizite Namen (soak.cpu_profile/gpu_profile) haben Vorrang; sonst wird
    automatisch das erste Profil mit gpu_layers == 0 (CPU) bzw. != 0 (GPU)
    genommen - genau das, was `bootstrap` standardmaessig als "CPU-Only" und
    "Full-GPU" anlegt.
    """
    profiles = model.get("profiles") or []

    def _by_name(name: str | None) -> dict[str, Any] | None:
        if not name:
            return None
        return next((p for p in profiles if p.get("name") == name), None)

    cpu_profile = _by_name(soak_cfg.get("cpu_profile")) or next(
        (p for p in profiles if int(p.get("gpu_layers", -1)) == 0), None
    )
    gpu_profile = _by_name(soak_cfg.get("gpu_profile")) or next(
        (p for p in profiles if int(p.get("gpu_layers", -1)) != 0), None
    )
    return cpu_profile, gpu_profile
