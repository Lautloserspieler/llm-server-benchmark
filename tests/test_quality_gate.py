"""Unit tests for Quality Gate 2.0 evaluation helpers.

These tests exercise the quality evaluation APIs introduced for the local
Quality Gate 2.0 rollout:
- llmbench.monitor.evaluate_telemetry_quality / ResourceMonitor.evaluate_quality
- llmbench.llama_bench.evaluate_llama_bench_quality
- llmbench.endpoint.evaluate_endpoint_quality

User instruction (continued session): "ja mach das erstmal ales local"
-> Task 6: add tests for Quality Gate 2.0.
"""
from __future__ import annotations

import pytest

from llmbench.endpoint import evaluate_endpoint_quality
from llmbench.llama_bench import evaluate_llama_bench_quality
from llmbench.monitor import (
    PHASE_BASELINE,
    PHASE_COOLDOWN,
    PHASE_RUN,
    ResourceMonitor,
    evaluate_telemetry_quality,
)


def _gpu_dict(util=50.0, pids=None):
    return {
        "index": 0,
        "util_gpu_percent": util,
        "util_memory_percent": util / 2,
        "memory_used_bytes": 1000,
        "memory_total_bytes": 8000,
        "temperature_c": 60.0,
        "power_w": 100.0,
        "compute_pids": pids or [],
    }


def _sample(phase, util=50.0, pids=None):
    return {
        "ts": 1.0,
        "phase": phase,
        "cpu_percent": 10.0,
        "ram_used_bytes": 1024,
        "ram_percent": 10.0,
        "gpus": [_gpu_dict(util=util, pids=pids)],
    }


def test_evaluate_telemetry_quality_clean_idle_baseline_no_foreign():
    telemetry = {
        "baseline": {"gpus": [_gpu_dict(util=2.0)]},
        "foreign_gpu_processes": [],
        "phases": {
            PHASE_RUN: {"gpus": [{"index": 0, "avg_util_gpu_percent": 80.0}]},
        },
    }
    result = evaluate_telemetry_quality(telemetry, {})
    assert result["status"] == "clean"
    assert result["reasons"] == []


def test_evaluate_telemetry_quality_invalid_when_baseline_busy():
    telemetry = {
        "baseline": {"gpus": [_gpu_dict(util=42.0)]},
        "foreign_gpu_processes": [],
        "phases": {},
    }
    result = evaluate_telemetry_quality(telemetry, {})
    assert result["status"] == "invalid"
    assert any("nicht im Ruhezustand" in r for r in result["reasons"])


def test_evaluate_telemetry_quality_invalid_for_significant_foreign_process():
    telemetry = {
        "baseline": {"gpus": [_gpu_dict(util=2.0)]},
        "foreign_gpu_processes": [
            {"pid": 123, "name": "game.exe", "max_util_gpu_percent": 25.0}
        ],
        "phases": {PHASE_RUN: {"gpus": [{"index": 0, "avg_util_gpu_percent": 80.0}]}},
    }
    result = evaluate_telemetry_quality(telemetry, {"max_foreign_gpu_util_percent": 5.0})
    assert result["status"] == "invalid"
    assert any("signifikanter" in r for r in result["reasons"])


def test_evaluate_telemetry_quality_warning_when_gpu_underutilized():
    telemetry = {
        "baseline": {"gpus": [_gpu_dict(util=2.0)]},
        "foreign_gpu_processes": [],
        "phases": {
            PHASE_RUN: {"gpus": [{"index": 0, "avg_util_gpu_percent": 10.0}]},
        },
    }
    result = evaluate_telemetry_quality(
        telemetry, {"min_gpu_util_during_benchmark_percent": 50.0}
    )
    assert result["status"] == "warning"
    assert any("ausgelastet" in r for r in result["reasons"])


def test_resource_monitor_evaluate_quality_marks_invalid_on_busy_baseline():
    monitor = ResourceMonitor()
    monitor._baseline = {"gpus": [_gpu_dict(util=42.0)]}
    monitor._samples = [
        _sample(PHASE_RUN, util=80.0),
        _sample(PHASE_COOLDOWN, util=5.0),
    ]
    result = monitor.evaluate_quality({})
    assert result["status"] == "invalid"


def test_resource_monitor_foreign_process_quantification():
    monitor = ResourceMonitor()
    monitor._own_pids = {111}
    monitor._seen_gpu_pids = {111, 123}
    monitor._samples = [
        _sample(PHASE_BASELINE, util=2.0),
        _sample(PHASE_RUN, util=80.0, pids=[111, 123]),
        _sample(PHASE_RUN, util=85.0, pids=[111, 123]),
    ]
    foreign = monitor._foreign_processes()
    assert len(foreign) == 1
    proc = foreign[0]
    assert proc["pid"] == 123
    assert proc["max_util_gpu_percent"] == 85.0
    assert proc["avg_util_gpu_percent"] == pytest.approx(82.5)


def test_evaluate_llama_bench_quality_clean_with_low_cv():
    result = {
        "status": "ok",
        "rows": [{"test": "tg128", "avg_ts": 100.0, "stddev_ts": 5.0}],
    }
    qg = evaluate_llama_bench_quality(
        result, {"max_tps_coefficient_of_variation": 0.15}
    )
    assert qg["status"] == "clean"


def test_evaluate_llama_bench_quality_warning_with_high_cv():
    result = {
        "status": "ok",
        "rows": [{"test": "tg128", "avg_ts": 100.0, "stddev_ts": 30.0}],
    }
    qg = evaluate_llama_bench_quality(
        result, {"max_tps_coefficient_of_variation": 0.15}
    )
    assert qg["status"] == "warning"
    assert any("Streuung" in r for r in qg["reasons"])


def test_evaluate_llama_bench_quality_invalid_on_failed_status():
    result = {"status": "failed", "error": "crash"}
    qg = evaluate_llama_bench_quality(result, {})
    assert qg["status"] == "invalid"


def test_evaluate_endpoint_quality_invalid_when_no_success():
    levels = [
        {"concurrency": 1, "requests": 2, "successful": 0, "request_details": []}
    ]
    qg = evaluate_endpoint_quality(levels, {}, {})
    assert qg["status"] == "invalid"
    assert any("Keiner" in r for r in qg["reasons"])


def test_evaluate_endpoint_quality_warning_on_high_cv():
    levels = [
        {
            "concurrency": 1,
            "requests": 2,
            "successful": 2,
            "request_details": [
                {"ok": True, "request_tps": 100.0, "ttft_seconds": 0.1},
                {"ok": True, "request_tps": 50.0, "ttft_seconds": 0.15},
            ],
        }
    ]
    qg = evaluate_endpoint_quality(
        levels, {}, {"max_tps_coefficient_of_variation": 0.15}
    )
    assert qg["status"] == "warning"
    assert any("Streuung" in r for r in qg["reasons"])


def test_evaluate_endpoint_quality_warning_on_ttft_outliers():
    # Mehrere stabile Punkte, damit der Ausreißer den Q3 nicht selbst zieht.
    levels = [
        {
            "concurrency": 1,
            "requests": 6,
            "successful": 6,
            "request_details": [
                {"ok": True, "request_tps": 100.0, "ttft_seconds": 0.10},
                {"ok": True, "request_tps": 100.0, "ttft_seconds": 0.11},
                {"ok": True, "request_tps": 100.0, "ttft_seconds": 0.10},
                {"ok": True, "request_tps": 100.0, "ttft_seconds": 0.12},
                {"ok": True, "request_tps": 100.0, "ttft_seconds": 0.11},
                {"ok": True, "request_tps": 100.0, "ttft_seconds": 5.0},
            ],
        }
    ]
    qg = evaluate_endpoint_quality(levels, {}, {"max_ttft_outlier_iqr_multiplier": 3.0})
    assert qg["status"] == "warning"
    assert any("TTFT-Ausreißer" in r for r in qg["reasons"])
