from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx

from llmbench.backends.llama_cpp import LlamaCppBackend
from llmbench.config import load_config, resolve_path
from llmbench.endpoint import wait_health_async
from llmbench.i18n import _
from llmbench.utils import auth_headers, ensure_dir, print_err, print_msg, print_section, write_json


def _prompt_for_target(target_tokens: int) -> str:
    # Absichtlich hochgradig wiederholbar: der Test misst Speichergrenzen, nicht
    # Modellqualitaet. Die echte Tokenzahl wird zusaetzlich ueber /tokenize gemessen.
    chunk = "The quick brown fox jumps over the lazy dog. "
    approximate_tokens_per_chunk = 10
    repeats = max(1, int(target_tokens / approximate_tokens_per_chunk))
    return chunk * repeats + "\nSummarize the preceding text in one short sentence."


async def _token_count(client: httpx.AsyncClient, base_url: str, prompt: str) -> int | None:
    try:
        response = await client.post(
            base_url.rstrip("/") + "/tokenize",
            json={"content": prompt, "add_special": False},
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        tokens = data.get("tokens")
        return len(tokens) if isinstance(tokens, list) else None
    except Exception:
        return None


async def _probe_context(base_url: str, prompt_target: int, endpoint_cfg: dict) -> dict:
    prompt = _prompt_for_target(prompt_target)
    timeout = float(endpoint_cfg.get("timeout_seconds", 600))
    headers = auth_headers(endpoint_cfg)
    payload = {
        "prompt": prompt,
        "n_predict": 32,
        "temperature": 0.0,
        "stream": False,
        "cache_prompt": False,
    }

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(headers=headers) as client:
            actual_tokens = await _token_count(client, base_url, prompt)
            response = await client.post(
                base_url.rstrip("/") + "/completion",
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            duration = time.perf_counter() - started
            return {
                "ok": True,
                "target_prompt_tokens": prompt_target,
                "actual_prompt_tokens": actual_tokens,
                "duration_seconds": duration,
                "http_status": response.status_code,
            }
    except Exception as exc:
        return {
            "ok": False,
            "target_prompt_tokens": prompt_target,
            "actual_prompt_tokens": None,
            "duration_seconds": time.perf_counter() - started,
            "error": str(exc),
        }


def _context_levels(cfg: dict) -> list[int]:
    stress_cfg = cfg.get("stress", {}) or {}
    configured = stress_cfg.get("oom_contexts")
    if configured:
        levels = [int(value) for value in configured if int(value) >= 2048]
    else:
        levels = [int(value) for value in cfg.get("benchmark", {}).get("context_depths", []) if int(value) >= 2048]
        levels.extend([4096, 8192, 16384, 32768])
    return sorted(set(levels))


async def run_oom_stress(config_path: str = "benchmark.yaml", output_dir: str | Path | None = None) -> int:
    """Ermittelt die praktische KV-/Kontextgrenze durch schrittweise Serverstarts.

    Jede Stufe startet llama-server mit einer passend grossen Kontextgroesse neu.
    Dadurch kann zwischen OOM beim KV-Cache-Anlegen und einem Fehler erst beim
    eigentlichen langen Request unterschieden werden.
    """
    cfg = load_config(config_path)
    if not cfg.get("models"):
        print_err(_("Keine Modelle in Konfiguration."))
        return 1

    model = cfg["models"][0]
    profiles = model.get("profiles") or []
    if not profiles:
        print_err(_("Das Modell besitzt kein Profil."))
        return 1

    model_path = resolve_path(model["path"], cfg)
    print_section(_("KV-Cache / Kontext-OOM-Stresstest"))
    print_msg(_("Modell: {name}").format(name=model["name"]))

    default_out = Path(cfg.get("project", {}).get("output_dir", "results")) / "stress_oom"
    out_dir = ensure_dir(Path(output_dir) if output_dir is not None else default_out)
    tools = cfg["tools"]
    backend = LlamaCppBackend(tools["llama_bench"], tools["llama_server"])

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
            proc, command = backend.start_server(
                model_path,
                profile,
                endpoint_cfg,
                cfg["benchmark"],
                out_dir / f"server_{level}.log",
            )
            cold_start = await wait_health_async(
                base_url,
                float(endpoint_cfg.get("startup_timeout_seconds", 300)),
                auth_headers(endpoint_cfg),
            )
        except Exception as exc:
            result = {
                "context_target": level,
                "context_size": endpoint_cfg["context_size"],
                "status": "startup_failed",
                "error": str(exc),
                "duration_seconds": time.perf_counter() - stage_started,
            }
            results.append(result)
            print_err(_("Serverstart/KV-Cache fehlgeschlagen bei ~{level} Tokens: {error}").format(level=level, error=exc))
            if proc is not None:
                backend.stop_server(proc)
            break

        try:
            probe = await _probe_context(base_url, level, endpoint_cfg)
            result = {
                "context_target": level,
                "context_size": endpoint_cfg["context_size"],
                "status": "ok" if probe["ok"] else "request_failed",
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
                    "[OK] " + _("Ziel {level}, tatsaechlich tokenisiert: {actual}").format(level=level, actual=actual),
                    style="green",
                )
            else:
                print_err(
                    _("Request fehlgeschlagen bei ~{level} Tokens: {error}").format(level=level, error=probe.get("error"))
                )
                break
        finally:
            if proc is not None:
                backend.stop_server(proc)
            await asyncio.sleep(1)

    result_doc = {
        "status": "ok" if max_stable else "failed",
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
