from __future__ import annotations

import csv
import traceback
from pathlib import Path
from typing import Any

from .config import resolve_path
from .endpoint import run_endpoint_load, start_llama_server, stop_llama_server, wait_health
from .hardware import collect_hardware
from .llama_bench import run_llama_bench, flatten_bench_rows
from .report import generate_run_html
from .utils import ensure_dir, hostname, local_now_compact, safe_name, sha256_file, utc_now_iso, write_json


def _model_meta(model: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    path = resolve_path(model["path"], cfg)
    p = Path(path)
    meta = {"name": model["name"], "path": path, "exists": p.exists(), "size_bytes": p.stat().st_size if p.exists() else None, "quality_gate": model.get("quality_gate"), "notes": model.get("notes")}
    if p.exists() and cfg["project"].get("hash_models", True):
        meta["sha256"] = sha256_file(p)
    return meta


def run_suite(cfg: dict[str, Any], selected_model: str | None = None, skip_endpoint: bool = False) -> Path:
    server_name = cfg["project"].get("server_name") or hostname()
    output_root = Path(resolve_path(cfg["project"]["output_dir"], cfg))
    run_dir = ensure_dir(output_root / f"{safe_name(server_name)}_{local_now_compact()}")
    hardware = collect_hardware()
    write_json(run_dir / "hardware.json", hardware)
    summary: dict[str, Any] = {"schema_version": 1, "project": cfg["project"].get("name"), "server_name": server_name, "started_at": utc_now_iso(), "config_path": cfg.get("_config_path"), "hardware": hardware, "models": []}

    for model in cfg["models"]:
        if selected_model and model["name"].lower() != selected_model.lower():
            continue
        meta = _model_meta(model, cfg)
        model_dir = ensure_dir(run_dir / safe_name(model["name"]))
        model_result: dict[str, Any] = {"model": meta, "profiles": []}
        if not meta["exists"]:
            model_result["status"] = "failed"
            model_result["error"] = "Model file not found"
            summary["models"].append(model_result)
            continue

        for profile in model.get("profiles", []):
            profile_dir = ensure_dir(model_dir / safe_name(profile["name"]))
            profile_result: dict[str, Any] = {"name": profile["name"], "settings": profile, "benchmarks": {}}
            for kind in ("prompt", "generation", "long_context"):
                try:
                    result = run_llama_bench(cfg["tools"]["llama_bench"], meta["path"], cfg["benchmark"], profile, kind, profile_dir)
                except Exception as exc:
                    result = {"kind": kind, "status": "failed", "error": str(exc), "traceback": traceback.format_exc()}
                profile_result["benchmarks"][kind] = result
            model_result["profiles"].append(profile_result)

        endpoint_cfg = dict(cfg.get("endpoint", {}))
        endpoint_cfg.update(model.get("endpoint", {}) or {})
        if endpoint_cfg.get("enabled") and not skip_endpoint:
            wanted_profile = endpoint_cfg.get("profile")
            profile = next((p for p in model["profiles"] if p["name"] == wanted_profile), model["profiles"][0])
            endpoint_dir = ensure_dir(model_dir / "endpoint")
            proc = None
            try:
                if endpoint_cfg.get("auto_start", True):
                    proc, command = start_llama_server(cfg["tools"]["llama_server"], meta["path"], profile, endpoint_cfg, endpoint_dir / "llama-server.log")
                    wait_health(endpoint_cfg["base_url"], float(endpoint_cfg.get("startup_timeout_seconds", 300)))
                else:
                    command = None
                    wait_health(endpoint_cfg["base_url"], 10)
                ep = run_endpoint_load(endpoint_cfg["base_url"], endpoint_cfg, float(cfg["benchmark"].get("resource_sample_interval", 0.5)), endpoint_dir)
                ep["server_command"] = command
                model_result["endpoint"] = ep
            except Exception as exc:
                model_result["endpoint"] = {"status": "failed", "error": str(exc), "traceback": traceback.format_exc()}
            finally:
                if proc is not None:
                    stop_llama_server(proc)

        summary["models"].append(model_result)
        write_json(run_dir / "summary.partial.json", summary)

    summary["finished_at"] = utc_now_iso()
    write_json(run_dir / "summary.json", summary)
    _write_csv(run_dir / "benchmarks.csv", summary)
    generate_run_html(summary, run_dir / "report.html")
    return run_dir


def _write_csv(path: Path, summary: dict[str, Any]) -> None:
    fields = ["server_name", "model", "profile", "kind", "test", "avg_ts", "stddev_ts", "n_prompt", "n_gen", "n_depth", "n_threads", "n_gpu_layers", "backend", "gpu_info", "cpu_info", "build_commit"]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for m in summary.get("models", []):
            for profile in m.get("profiles", []):
                for kind, result in profile.get("benchmarks", {}).items():
                    for row in flatten_bench_rows(result):
                        w.writerow({"server_name": summary.get("server_name"), "model": m.get("model", {}).get("name"), "profile": profile.get("name"), "kind": kind, **{k: row.get(k) for k in fields if k not in {"server_name", "model", "profile", "kind"}}})
