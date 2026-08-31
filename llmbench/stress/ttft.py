from __future__ import annotations

from pathlib import Path

from llmbench.backends.llama_cpp import LlamaCppBackend
from llmbench.config import load_config, resolve_path
from llmbench.endpoint import run_endpoint_load
from llmbench.utils import ensure_dir, print_err, print_msg, write_json


def _ttft_levels(cfg: dict) -> list[int]:
    stress_cfg = cfg.get("stress", {}) or {}
    configured = stress_cfg.get("ttft_concurrency")
    if configured:
        return sorted(set(int(value) for value in configured if int(value) > 0))
    endpoint_levels = [int(value) for value in cfg.get("endpoint", {}).get("concurrency", []) if int(value) > 0]
    return sorted(set(endpoint_levels + [16, 32]))


def run_ttft_stress(config_path: str = "benchmark.yaml", output_dir: str | Path | None = None) -> int:
    """Misst TTFT P50/P95 bei deutlich hoeherer Parallelitaet als der Standardlauf."""
    cfg = load_config(config_path)
    if not cfg.get("models"):
        print_err("Keine Modelle in Konfiguration.")
        return 1

    model = cfg["models"][0]
    profiles = model.get("profiles") or []
    if not profiles:
        print_err("Das Modell besitzt kein Profil.")
        return 1

    levels = _ttft_levels(cfg)
    if not levels:
        print_err("Keine Concurrency-Stufen fuer TTFT konfiguriert.")
        return 1

    default_out = Path(cfg.get("project", {}).get("output_dir", "results")) / "stress_ttft"
    out_dir = ensure_dir(Path(output_dir) if output_dir is not None else default_out)
    endpoint_cfg = dict(cfg.get("endpoint", {}))
    endpoint_cfg.update(model.get("endpoint", {}) or {})
    endpoint_cfg["enabled"] = True
    endpoint_cfg["concurrency"] = levels
    endpoint_cfg["requests_per_level"] = max(
        int(endpoint_cfg.get("requests_per_level", 8)), max(levels) * 2
    )
    endpoint_cfg["parallel_slots"] = max(
        int(endpoint_cfg.get("parallel_slots", 1)), max(levels)
    )

    tools = cfg["tools"]
    backend = LlamaCppBackend(tools["llama_bench"], tools["llama_server"])
    profile = profiles[0]
    model_path = resolve_path(model["path"], cfg)
    proc = None

    print_msg("=== TTFT-Stresstest ===")
    print_msg(f"Modell: {model['name']} | Concurrency: {levels}")
    try:
        proc, command = backend.start_server(
            model_path,
            profile,
            endpoint_cfg,
            cfg["benchmark"],
            out_dir / "llama-server.log",
        )
        cold_start = backend.wait_health(
            endpoint_cfg["base_url"],
            float(endpoint_cfg.get("startup_timeout_seconds", 300)),
            {"Authorization": f"Bearer {endpoint_cfg['api_key']}"} if endpoint_cfg.get("api_key") else None,
        )
        result = run_endpoint_load(
            endpoint_cfg["base_url"],
            endpoint_cfg,
            float(cfg["benchmark"].get("resource_sample_interval", 0.5)),
            out_dir,
            target_pid=proc.pid,
        )
        result["model"] = model["name"]
        result["profile"] = profile.get("name")
        result["server_command"] = command
        result["cold_start_seconds"] = cold_start
        write_json(out_dir / "ttft.json", result)

        for level in result.get("levels", []):
            p50 = level.get("ttft_p50_seconds")
            p95 = level.get("ttft_p95_seconds")
            print_msg(
                f"Concurrency {level.get('concurrency')}: "
                f"TTFT P50 {(p50 or 0) * 1000:.1f} ms | P95 {(p95 or 0) * 1000:.1f} ms | "
                f"System-TPS {float(level.get('system_tps') or 0):.2f}"
            )
        print_msg(f"Ergebnis: {out_dir / 'ttft.json'}")
        return 0
    except Exception as exc:
        write_json(out_dir / "ttft.json", {"status": "failed", "error": str(exc)})
        print_err(f"TTFT-Stresstest fehlgeschlagen: {exc}")
        return 1
    finally:
        if proc is not None:
            backend.stop_server(proc)
