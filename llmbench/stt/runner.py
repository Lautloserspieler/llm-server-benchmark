"""STT-Benchmark-Runner.

Kümmert sich um Laden des Datensatzes, Durchführen der Transkription ueber die
konfigurierten Engines, Berechnung der Metriken und Schreiben eines
strukturierten Ergebnis-JSONs.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..utils import ensure_dir, utc_now_iso, write_json
from .backends import build_engine
from .config import STTConfig
from .dataset import load_stt_dataset
from .metrics import compute_metrics


def _aggregate(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "min": 0.0, "max": 0.0, "median": 0.0}
    sorted_values = sorted(values)
    n = len(sorted_values)
    mean = sum(sorted_values) / n
    median = sorted_values[n // 2] if n % 2 else (sorted_values[n // 2 - 1] + sorted_values[n // 2]) / 2
    return {
        "mean": mean,
        "min": sorted_values[0],
        "max": sorted_values[-1],
        "median": median,
    }


def _run_engine(
    cfg: STTConfig,
    engine_name: str,
    engine_cfg_dict: dict[str, Any],
    samples: list,
    on_progress: Any | None,
) -> dict[str, Any]:
    from .config import STTEngineConfig

    engine_cfg = STTEngineConfig(**engine_cfg_dict)
    engine = build_engine(engine_cfg)
    details: list[dict[str, Any]] = []
    metric_values: dict[str, list[float]] = {m.name: [] for m in cfg.metrics}
    durations: list[float] = []

    for i, sample in enumerate(samples):
        try:
            hypothesis, duration = engine.transcribe(sample.audio_path)
            error = None
        except Exception as exc:
            hypothesis = ""
            duration = 0.0
            error = str(exc)

        metrics = compute_metrics(sample.reference, hypothesis, cfg.metrics)
        for name, value in metrics.items():
            metric_values.setdefault(name, []).append(value)
        if duration:
            durations.append(duration)

        details.append(
            {
                "sample_id": sample.id,
                "reference": sample.reference,
                "hypothesis": hypothesis,
                "duration_seconds": duration,
                "metrics": metrics,
                "error": error,
            }
        )

        if on_progress:
            on_progress(
                f"STT {engine_name}: {i + 1}/{len(samples)}",
                {"current": i + 1, "total": len(samples)},
            )

    per_metric: dict[str, Any] = {}
    for name, values in metric_values.items():
        per_metric[name] = _aggregate(values)

    return {
        "engine": engine.info(),
        "samples_count": len(samples),
        "duration_seconds": _aggregate(durations),
        "metrics": per_metric,
        "details": details,
    }


def run_stt_benchmark(
    cfg: STTConfig,
    base_output_dir: Path,
    on_progress: Any | None = None,
) -> dict[str, Any]:
    """Fuehrt den STT-Benchmark fuer alle konfigurierten Engines aus."""
    if not cfg.enabled:
        return {"status": "skipped", "reason": "STT ist in der Konfiguration deaktiviert."}

    if not cfg.dataset_path:
        return {"status": "error", "reason": "Kein dataset_path in stt konfiguriert."}

    started = time.perf_counter()
    try:
        samples = load_stt_dataset(cfg.dataset_path, cfg.max_samples)
    except FileNotFoundError:
        return {"status": "error", "reason": f"STT-Datensatz nicht gefunden: {cfg.dataset_path}"}
    if not samples:
        return {"status": "error", "reason": "Der STT-Datensatz enthaelt keine Samples."}

    output_dir = base_output_dir / cfg.output_dir
    ensure_dir(output_dir)

    results: list[dict[str, Any]] = []
    for engine_cfg in cfg.engines:
        results.append(
            _run_engine(cfg, engine_cfg.name, engine_cfg.model_dump(), samples, on_progress)
        )

    summary = {
        "status": "ok",
        "started_at": utc_now_iso(),
        "duration_seconds": time.perf_counter() - started,
        "dataset": {
            "path": cfg.dataset_path,
            "samples_count": len(samples),
        },
        "engines": results,
    }

    write_json(output_dir / "stt_summary.json", summary)
    return summary
