from __future__ import annotations

import asyncio
import time
from pathlib import Path

from llmbench.backends import backend_name, get_backend
from llmbench.config import load_config
from llmbench.i18n import _
from llmbench.stress.base import require_capabilities, resolve_model_ref
from llmbench.utils import auth_headers, ensure_dir, print_err, print_msg, print_section, write_json


LEGACY_OOM_CONTEXTS = [4096, 8192, 16384, 32768, 65536, 96000, 130000]
DEFAULT_OOM_CONTEXTS = [
    4096,
    8192,
    16384,
    32768,
    65536,
    98304,
    131072,
    196608,
    262144,
    393216,
]


def _context_levels(cfg: dict) -> list[int]:
    stress_cfg = cfg.get("stress", {}) or {}
    configured = stress_cfg.get("oom_contexts")
    if configured:
        levels = [int(value) for value in configured if int(value) >= 2048]
        if levels == LEGACY_OOM_CONTEXTS:
            levels = list(DEFAULT_OOM_CONTEXTS)
    else:
        levels = [
            int(value)
            for value in cfg.get("benchmark", {}).get("context_depths", [])
            if int(value) >= 2048
        ]
        levels.extend(DEFAULT_OOM_CONTEXTS)
    return sorted(set(levels))


async def run_oom_stress(config_path: str = "benchmark.yaml", output_dir: str | Path | None = None) -> int:
    """Ermittelt die praktische KV-/Kontextgrenze durch schrittweise Serverstarts."""
    cfg = load_config(config_path)
    if not cfg.get("models"):
        print_err(_("Keine Modelle in Konfiguration."))
        return 1

    model = cfg["models"][0]
    profiles = model.get("profiles") or []
    if not profiles:
        print_err(_("Das Modell besitzt kein Profil."))
        return 1

    default_out = Path(cfg.get("project", {}).get("output_dir", "results")) / "stress_oom"
    out_dir = ensure_dir(Path(output_dir) if output_dir is not None else default_out)

    backend = get_backend(cfg)
    name = backend_name(cfg)
    skipped = require_capabilities(
        backend,
        name,
        ("endpoint", "oom_probe"),
        workload="text.oom_probe",
        result_path=out_dir / "oom.json",
    )
    if skipped is not None:
        return skipped

    model_path = resolve_model_ref(model["path"], cfg, name)
    print_section(_("KV-Cache / Kontext-OOM-Stresstest"))
    print_msg(_("Modell: {name}").format(name=model["name"]))

    base_endpoint = dict(cfg.get("endpoint", {}))
    base_endpoint.update(model.get("endpoint", {}) or {})
    base_endpoint["parallel_slots"] = 1
    base_url = str(base_endpoint.get("base_url", "http://127.0.0.1:8080"))
    profile = profiles[0]
    levels = _context_levels(cfg)
    if not levels:
        print_err(_("Keine Kontextstufen fuer den OOM-Test konfiguriert."))
        return 1

    results: list[dict] = []
    max_stable = 0
    overall_started = time.perf_counter()

    for level in levels:
        endpoint_cfg = dict(base_endpoint)
        endpoint_cfg["context_size"] = level + 512
        proc = None
        print_msg(
            "\n"
            + _("Teste Kontextstufe ~{level} Tokens (Server -c {ctx})...").format(
                level=level, ctx=endpoint_cfg["context_size"]
            )
        )
        stage_started = time.perf_counter()
        try:
            # In einem Worker-Thread: Container-Backends (Ollama) warten in
            # start_server synchron auf ihre API und duerfen dabei nicht in
            # der laufenden Event-Loop haengen.
            proc, command = await asyncio.to_thread(
                backend.start_server,
                model_path,
                profile,
                endpoint_cfg,
                cfg["benchmark"],
                out_dir / f"{name}-server_{level}.log",
            )
            cold_start = await asyncio.to_thread(
                backend.wait_health,
                base_url,
                float(endpoint_cfg.get("startup_timeout_seconds", 300)),
                auth_headers(endpoint_cfg),
                proc,
            )
        except Exception as exc:
            result = {
                "context_target": level,
                "context_size": endpoint_cfg["context_size"],
                "status": "startup_failed",
                "failure_category": "startup_failed",
                "error": str(exc),
                "duration_seconds": time.perf_counter() - stage_started,
            }
            results.append(result)
            print_err(
                _("Serverstart/KV-Cache fehlgeschlagen bei ~{level} Tokens: {error}").format(
                    level=level, error=exc
                )
            )
            if proc is not None:
                backend.stop_server(proc)
            break

        try:
            try:
                probe = await backend.probe_context(base_url, level, endpoint_cfg)
            except Exception as exc:  # noqa: BLE001 - ein defekter Probe darf den Ergebnisbericht nicht verhindern
                probe = {
                    "ok": False,
                    "target_prompt_tokens": level,
                    "failure_category": "probe_error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            result = {
                "context_target": level,
                "context_size": endpoint_cfg["context_size"],
                "status": "ok" if probe["ok"] else "request_failed",
                "failure_category": probe.get("failure_category"),
                "cold_start_seconds": cold_start,
                "server_command": command,
                "probe": probe,
                "duration_seconds": time.perf_counter() - stage_started,
            }
            results.append(result)
            if probe["ok"]:
                max_stable = int(probe.get("actual_prompt_tokens") or level)
                actual = probe.get("actual_prompt_tokens") or _("unbekannt")
                print_msg(
                    "[OK] "
                    + _("Ziel {level}, tatsaechlich tokenisiert: {actual}").format(
                        level=level, actual=actual
                    ),
                    style="green",
                )
            else:
                print_err(
                    _("Request fehlgeschlagen bei ~{level} Tokens: {error}").format(
                        level=level, error=probe.get("error")
                    )
                )
                break
        finally:
            if proc is not None:
                backend.stop_server(proc)
            await asyncio.sleep(1)

    result_doc = {
        "status": "ok" if max_stable else "failed",
        "backend": name,
        "model": model["name"],
        "model_path": model_path,
        "profile": profile.get("name"),
        "max_stable_prompt_tokens": max_stable,
        "levels": results,
        "duration_seconds": time.perf_counter() - overall_started,
    }
    write_json(out_dir / "oom.json", result_doc)
    print_msg("\n" + _("Maximale stabile gemessene Promptlaenge: {tokens} Tokens").format(tokens=max_stable))
    print_msg(_("Ergebnis: {path}").format(path=out_dir / "oom.json"), style="green")
    return 0 if max_stable else 1
