from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from .monitor import ResourceMonitor
from .utils import csv_value, resolve_executable, utc_now_iso, write_json


def _extract_json(stdout: str) -> list[dict[str, Any]]:
    text = stdout.strip()
    if not text:
        raise ValueError("llama-bench returned empty stdout")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start < 0 or end < start:
            raise
        data = json.loads(text[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("llama-bench JSON output is not a list")
    return data


def _base_args(exe: str, model_path: str, bench_cfg: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    args = [exe, "-m", model_path, "-r", str(bench_cfg["repetitions"]), "--delay", str(bench_cfg.get("delay_seconds", 0)), "-o", "json", "-b", str(bench_cfg["batch_size"]), "-ub", str(bench_cfg["ubatch_size"]), "-fa", str(bench_cfg.get("flash_attention", "auto")), "-ctk", str(bench_cfg.get("cache_type_k", "f16")), "-ctv", str(bench_cfg.get("cache_type_v", "f16")), "-ngl", str(profile.get("gpu_layers", -1))]
    threads = profile.get("threads", "auto")
    if threads not in (None, "auto", -1):
        args.extend(["-t", str(threads)])
    if profile.get("cpu_moe_layers") is not None:
        args.extend(["-ncmoe", str(profile["cpu_moe_layers"])])
    if profile.get("no_kv_offload"):
        args.extend(["-nkvo", "1"])
    if profile.get("device"):
        args.extend(["-dev", str(profile["device"])])
    if profile.get("tensor_split"):
        args.extend(["-ts", str(profile["tensor_split"])])
    for item in profile.get("additional_args", []) or []:
        args.append(str(item))
    return args


def run_llama_bench(exe: str, model_path: str, bench_cfg: dict[str, Any], profile: dict[str, Any], test_kind: str, output_dir: Path) -> dict[str, Any]:
    exe = resolve_executable(exe)
    args = _base_args(exe, model_path, bench_cfg, profile)
    if test_kind == "prompt":
        args.extend(["-p", csv_value(bench_cfg["prompt_tokens"]), "-n", "0", "-d", "0"])
    elif test_kind == "generation":
        args.extend(["-p", "0", "-n", csv_value(bench_cfg["generation_tokens"]), "-d", "0"])
    elif test_kind == "long_context":
        args.extend(["-p", str(bench_cfg["long_context_prompt_tokens"]), "-n", str(bench_cfg["long_context_generation_tokens"]), "-d", csv_value(bench_cfg["context_depths"])])
    else:
        raise ValueError(f"Unknown test kind: {test_kind}")

    monitor = ResourceMonitor(float(bench_cfg.get("resource_sample_interval", 0.5)))
    started = time.perf_counter()
    monitor.start()
    cp = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", check=False)
    duration = time.perf_counter() - started
    telemetry = monitor.stop()
    raw = {"started_at": utc_now_iso(), "duration_seconds": duration, "command": args, "returncode": cp.returncode, "stdout": cp.stdout, "stderr": cp.stderr, "telemetry": telemetry}
    write_json(output_dir / f"raw_{test_kind}.json", raw)
    if cp.returncode != 0:
        return {"kind": test_kind, "status": "failed", "error": f"llama-bench exited with {cp.returncode}", "duration_seconds": duration, "stderr_tail": cp.stderr[-4000:], "telemetry": telemetry}
    try:
        rows = _extract_json(cp.stdout)
    except Exception as exc:
        return {"kind": test_kind, "status": "failed", "error": f"Could not parse llama-bench JSON: {exc}", "duration_seconds": duration, "stdout_tail": cp.stdout[-4000:], "telemetry": telemetry}
    return {"kind": test_kind, "status": "ok", "duration_seconds": duration, "rows": rows, "telemetry": telemetry}


def flatten_bench_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if result.get("status") != "ok":
        return rows
    for row in result.get("rows", []):
        rows.append({"test": row.get("test") or _derive_test_name(row), "avg_ts": row.get("avg_ts"), "stddev_ts": row.get("stddev_ts"), "n_prompt": row.get("n_prompt"), "n_gen": row.get("n_gen"), "n_depth": row.get("n_depth"), "n_threads": row.get("n_threads"), "n_gpu_layers": row.get("n_gpu_layers"), "backend": row.get("backends") or row.get("backend"), "model_type": row.get("model_type"), "model_n_params": row.get("model_n_params"), "model_size": row.get("model_size"), "build_commit": row.get("build_commit"), "build_number": row.get("build_number"), "cpu_info": row.get("cpu_info"), "gpu_info": row.get("gpu_info")})
    return rows


def _derive_test_name(row: dict[str, Any]) -> str:
    p = int(row.get("n_prompt") or 0)
    n = int(row.get("n_gen") or 0)
    d = int(row.get("n_depth") or 0)
    if p and not n:
        base = f"pp{p}"
    elif n and not p:
        base = f"tg{n}"
    elif p and n:
        base = f"pg{p}+{n}"
    else:
        base = "unknown"
    return f"{base}@d{d}" if d else base
