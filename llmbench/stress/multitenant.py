from __future__ import annotations

import asyncio
import time
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from llmbench.backends.llama_cpp import LlamaCppBackend
from llmbench.config import load_config, resolve_path
from llmbench.endpoint import _run_endpoint_load_async, wait_health_async
from llmbench.utils import ensure_dir, print_err, print_msg, write_json


def modify_url_port(base_url: str, new_port: int) -> str:
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{new_port}"
    return urlunparse((parsed.scheme or "http", netloc, parsed.path, "", "", ""))


def _auth_headers(cfg: dict) -> dict[str, str]:
    key = cfg.get("api_key")
    return {"Authorization": f"Bearer {key}"} if key else {}


def _average_system_tps(result: dict) -> float:
    values = [float(level.get("system_tps") or 0.0) for level in result.get("levels", [])]
    return sum(values) / len(values) if values else 0.0


async def run_multitenant(config_path: str = "benchmark.yaml", output_dir: str | Path | None = None) -> int:
    """Startet zwei Modelle parallel und misst beide Endpoints getrennt."""
    cfg = load_config(config_path)
    if len(cfg.get("models", [])) < 2:
        print_err("Multi-Tenant Stresstest benoetigt mindestens 2 Modelle in der Konfiguration.")
        return 1

    model1, model2 = cfg["models"][:2]
    profiles1 = model1.get("profiles") or []
    profiles2 = model2.get("profiles") or []
    if not profiles1 or not profiles2:
        print_err("Beide Modelle benoetigen mindestens ein Profil.")
        return 1

    print_msg("=== Multi-Tenant Stresstest ===")
    print_msg(f"Modell 1: {model1['name']}")
    print_msg(f"Modell 2: {model2['name']}")

    default_out = Path(cfg.get("project", {}).get("output_dir", "results")) / "stress_multitenant"
    out_dir = ensure_dir(Path(output_dir) if output_dir is not None else default_out)
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

    prof1 = profiles1[0]
    prof2 = profiles2[0]
    model_path1 = resolve_path(model1["path"], cfg)
    model_path2 = resolve_path(model2["path"], cfg)

    proc1 = None
    proc2 = None
    started = time.perf_counter()
    try:
        print_msg("Starte Server 1...")
        proc1, command1 = backend.start_server(
            model_path1, prof1, ep_cfg1, cfg["benchmark"], out_dir / "server1.log"
        )

        print_msg("Starte Server 2...")
        proc2, command2 = backend.start_server(
            model_path2, prof2, ep_cfg2, cfg["benchmark"], out_dir / "server2.log"
        )

        print_msg("Warte auf Health Checks...")
        timeout = float(base_endpoint.get("startup_timeout_seconds", 300))
        await asyncio.gather(
            wait_health_async(ep_cfg1["base_url"], timeout, _auth_headers(ep_cfg1)),
            wait_health_async(ep_cfg2["base_url"], timeout, _auth_headers(ep_cfg2)),
        )
        print_msg("Beide Server bereit.")

        interval = float(cfg["benchmark"].get("resource_sample_interval", 0.5))
        print_msg("Starte parallele Endpoint-Last auf beide Server...")
        res1, res2 = await asyncio.gather(
            _run_endpoint_load_async(
                ep_cfg1["base_url"], ep_cfg1, interval, load_dir1,
                target_pid=proc1.pid if proc1 else None,
            ),
            _run_endpoint_load_async(
                ep_cfg2["base_url"], ep_cfg2, interval, load_dir2,
                target_pid=proc2.pid if proc2 else None,
            ),
        )

        result = {
            "status": "ok",
            "duration_seconds": time.perf_counter() - started,
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
