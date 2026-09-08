from __future__ import annotations

import asyncio
import time
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from llmbench.backends.llama_cpp import LlamaCppBackend
from llmbench.capacity import (
    current_hardware,
    is_gpu_profile,
    profile_vram_issue_for_path,
    total_gpu_vram_bytes,
)
from llmbench.config import load_config, resolve_path
from llmbench.endpoint import _run_endpoint_load_async, wait_health_async
from llmbench.utils import auth_headers, ensure_dir, file_fingerprint, modify_url_port, print_err, print_msg, write_json

_MULTI_TENANT_VRAM_FRACTION = 0.80


def _average_system_tps(result: dict) -> float:
    values = [float(level.get("system_tps") or 0.0) for level in result.get("levels", [])]
    return sum(values) / len(values) if values else 0.0


def _first_gpu_profile(model: dict[str, Any]) -> dict[str, Any] | None:
    return next((profile for profile in model.get("profiles") or [] if is_gpu_profile(profile)), None)


def _multitenant_candidates(cfg: dict[str, Any], hardware: dict[str, Any]) -> list[dict[str, Any]]:
    """Erzeugt nach Gewichtsgroesse sortierte, einzeln GPU-taugliche Kandidaten.

    Nicht vorhandene Dateien bleiben mit unbekannter Groesse im Kandidatensatz.
    Das erhaelt die bisherige Fehlerbehandlung im eigentlichen Serverstart und
    verhindert, dass Tests oder externe Backends allein durch den Preflight
    anders semantisch behandelt werden. Reale vorhandene GGUFs werden dagegen
    vollstaendig auf VRAM-Tauglichkeit geprueft.
    """
    candidates: list[dict[str, Any]] = []
    for model in cfg.get("models", []) or []:
        profile = _first_gpu_profile(model)
        if not profile:
            continue
        path = resolve_path(model["path"], cfg)
        fingerprint = file_fingerprint(path, with_hash=False)
        issue = profile_vram_issue_for_path(path, profile, hardware)
        if issue:
            continue
        try:
            size_bytes = int(fingerprint.get("size_bytes") or 0)
        except (TypeError, ValueError):
            size_bytes = 0
        candidates.append(
            {
                "model": model,
                "profile": profile,
                "path": path,
                "size_bytes": max(0, size_bytes),
            }
        )
    return sorted(candidates, key=lambda item: (item["size_bytes"], str(item["model"].get("name", ""))))


def _select_multitenant_pair(
    cfg: dict[str, Any],
    hardware: dict[str, Any] | None = None,
) -> tuple[tuple[dict[str, Any], dict[str, Any]] | None, str | None]:
    """Waehlt zwei kleine GPU-Modelle, die gemeinsam realistisch in VRAM passen."""
    hardware = hardware or current_hardware()
    candidates = _multitenant_candidates(cfg, hardware)
    if len(candidates) < 2:
        return None, "Weniger als zwei einzeln GPU-taugliche Modelle gefunden."

    total_vram = total_gpu_vram_bytes(hardware)
    budget = int(total_vram * _MULTI_TENANT_VRAM_FRACTION) if total_vram else 0
    for left_index, left in enumerate(candidates[:-1]):
        for right in candidates[left_index + 1 :]:
            combined = int(left["size_bytes"]) + int(right["size_bytes"])
            if not budget or combined <= budget:
                return (left, right), None

    return (
        None,
        "Kein Modellpaar passt mit ausreichender Reserve gleichzeitig in den erkannten GPU-VRAM "
        f"({total_vram / (1024 ** 3):.1f} GiB, Budget {_MULTI_TENANT_VRAM_FRACTION * 100:.0f} %).",
    )


async def run_multitenant(config_path: str = "benchmark.yaml", output_dir: str | Path | None = None) -> int:
    """Startet zwei automatisch VRAM-kompatibel ausgewaehlte GPU-Modelle parallel."""
    cfg = load_config(config_path)
    if len(cfg.get("models", [])) < 2:
        print_err("Multi-Tenant Stresstest benoetigt mindestens 2 Modelle in der Konfiguration.")
        return 1

    default_out = Path(cfg.get("project", {}).get("output_dir", "results")) / "stress_multitenant"
    out_dir = ensure_dir(Path(output_dir) if output_dir is not None else default_out)

    pair, reason = _select_multitenant_pair(cfg)
    if not pair:
        result = {"status": "skipped", "reason": reason or "Kein geeignetes Modellpaar gefunden."}
        write_json(out_dir / "multitenant.json", result)
        print_msg(f"Multi-Tenant uebersprungen: {result['reason']}")
        return 2

    first, second = pair
    model1, model2 = first["model"], second["model"]
    prof1, prof2 = first["profile"], second["profile"]
    model_path1, model_path2 = first["path"], second["path"]

    print_msg("=== Multi-Tenant Stresstest ===")
    print_msg(f"Modell 1: {model1['name']} ({prof1.get('name')})")
    print_msg(f"Modell 2: {model2['name']} ({prof2.get('name')})")

    load_dir1 = ensure_dir(out_dir / "model1")
    load_dir2 = ensure_dir(out_dir / "model2")

    tools = cfg["tools"]
    backend = LlamaCppBackend(tools["llama_bench"], tools["llama_server"])

    base_endpoint = deepcopy(cfg.get("endpoint", {}))
    ep_cfg1 = deepcopy(base_endpoint)
    ep_cfg1.update(model1.get("endpoint", {}) or {})
    ep_cfg2 = deepcopy(base_endpoint)
    ep_cfg2.update(model2.get("endpoint", {}) or {})

    parsed = urlparse(str(base_endpoint.get("base_url", "http://127.0.0.1:8080")))
    first_port = parsed.port or 8080
    ep_cfg1["base_url"] = modify_url_port(str(ep_cfg1.get("base_url", parsed.geturl())), first_port)
    ep_cfg2["base_url"] = modify_url_port(str(ep_cfg2.get("base_url", parsed.geturl())), first_port + 1)

    proc1 = None
    proc2 = None
    started = time.perf_counter()
    try:
        print_msg("Starte Server 1...")
        proc1, command1 = backend.start_server(
            model_path1,
            prof1,
            ep_cfg1,
            cfg["benchmark"],
            out_dir / "server1.log",
        )

        print_msg("Starte Server 2...")
        proc2, command2 = backend.start_server(
            model_path2,
            prof2,
            ep_cfg2,
            cfg["benchmark"],
            out_dir / "server2.log",
        )

        print_msg("Warte auf Health Checks...")
        timeout = float(base_endpoint.get("startup_timeout_seconds", 300))
        await asyncio.gather(
            wait_health_async(ep_cfg1["base_url"], timeout, auth_headers(ep_cfg1)),
            wait_health_async(ep_cfg2["base_url"], timeout, auth_headers(ep_cfg2)),
        )
        print_msg("Beide Server bereit.")

        interval = float(cfg["benchmark"].get("resource_sample_interval", 0.5))
        print_msg("Starte parallele Endpoint-Last auf beide Server...")
        res1, res2 = await asyncio.gather(
            _run_endpoint_load_async(
                ep_cfg1["base_url"],
                ep_cfg1,
                interval,
                load_dir1,
                target_pid=proc1.pid if proc1 else None,
            ),
            _run_endpoint_load_async(
                ep_cfg2["base_url"],
                ep_cfg2,
                interval,
                load_dir2,
                target_pid=proc2.pid if proc2 else None,
            ),
        )

        result = {
            "status": "ok",
            "duration_seconds": time.perf_counter() - started,
            "selection": {
                "strategy": "two-smallest-vram-compatible-gpu-models",
                "combined_model_bytes": int(first["size_bytes"]) + int(second["size_bytes"]),
                "vram_budget_fraction": _MULTI_TENANT_VRAM_FRACTION,
            },
            "models": [
                {
                    "name": model1["name"],
                    "path": model_path1,
                    "profile": prof1.get("name"),
                    "base_url": ep_cfg1["base_url"],
                    "server_command": command1,
                    "average_system_tps": _average_system_tps(res1),
                    "endpoint": res1,
                },
                {
                    "name": model2["name"],
                    "path": model_path2,
                    "profile": prof2.get("name"),
                    "base_url": ep_cfg2["base_url"],
                    "server_command": command2,
                    "average_system_tps": _average_system_tps(res2),
                    "endpoint": res2,
                },
            ],
        }
        write_json(out_dir / "multitenant.json", result)
        print_msg(f"{model1['name']}: {_average_system_tps(res1):.2f} System-TPS im Mittel")
        print_msg(f"{model2['name']}: {_average_system_tps(res2):.2f} System-TPS im Mittel")
        print_msg(f"Ergebnis: {out_dir / 'multitenant.json'}")
        return 0
    except Exception as exc:
        write_json(
            out_dir / "multitenant.json",
            {"status": "failed", "error": str(exc), "duration_seconds": time.perf_counter() - started},
        )
        print_err(f"Fehler im Stresstest: {exc}")
        return 1
    finally:
        if proc1 is not None:
            backend.stop_server(proc1)
        if proc2 is not None:
            backend.stop_server(proc2)
