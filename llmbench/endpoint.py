from __future__ import annotations

import asyncio
import contextlib
import json
import math
import random
import re
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import normalize_flash_attention
from .http_bench import API_STYLE_LLAMA_CPP, API_STYLE_LLAMA_CPP_CHAT, one_completion_async
from .monitor import ResourceMonitor, strip_samples
from .i18n import _
from .utils import (
    auth_headers,
    format_exit_code,
    kill_process_tree,
    log_tail,
    resolve_executable,
    utc_now_iso,
    write_json,
)


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return xs[int(k)]
    return xs[f] * (c - k) + xs[c] * (k - f)


async def run_sanity_check(
    base_url: str,
    cfg: dict[str, Any],
    quality_gate_cfg: dict[str, Any],
) -> tuple[bool, str]:
    """Prueft anhand definierter Tests, ob das Modell sinnvolle Ausgaben erzeugt."""
    tests = quality_gate_cfg.get("tests", [])
    if not tests:
        return True, "Keine Tests im Quality Gate definiert."

    passed = 0
    errors = []

    async with httpx.AsyncClient(headers=auth_headers(cfg)) as client:
        for i, test in enumerate(tests):
            prompt = test.get("prompt", "")
            expected_regex = test.get("expected_regex")
            max_tokens = test.get("max_tokens", 50)

            payload = {
                "prompt": prompt,
                "n_predict": max_tokens,
                "temperature": 0.0,
                "stream": False,
            }
            try:
                r = await client.post(
                    base_url.rstrip("/") + "/completion",
                    json=payload,
                    timeout=30,
                )
                r.raise_for_status()
                content = r.json().get("content", "").strip()

                if expected_regex:
                    if re.search(expected_regex, content):
                        passed += 1
                    else:
                        errors.append(
                            f"Test {i+1} fehlgeschlagen. Erwartet Regex '{expected_regex}', erhalten: {content!r}"
                        )
                else:
                    passed += 1
            except Exception as exc:
                errors.append(f"Test {i+1} Fehler: {exc}")

    if errors:
        return False, "; ".join(errors)
    return True, f"Sanity check bestanden ({passed}/{len(tests)} Tests)."


def _exited_code(proc: Any) -> int | None:
    """Exitcode, falls der Prozess schon beendet ist - sonst None (auch fuer Attrappen ohne poll)."""
    poll = getattr(proc, "poll", None)
    if not callable(poll):
        return None
    try:
        code = poll()
    except Exception:
        return None
    return code if isinstance(code, int) else None


def server_exit_message(proc: Any, code: int) -> str:
    """Fehlermeldung mit dem echten Grund, statt nur "All connection attempts failed"."""
    log_path = getattr(proc, "_llmbench_log_path", None)
    log_file = getattr(proc, "_llmbench_log_file", None)
    if log_file is not None:
        with contextlib.suppress(Exception):
            log_file.flush()
    message = _("llama-server hat sich beim Start beendet ({reason}).").format(reason=format_exit_code(code))
    tail = log_tail(log_path)
    if tail:
        message += "\n" + _("Letzte Zeilen aus dem Server-Log:") + "\n" + tail
    if log_path:
        message += "\n" + _("Vollstaendiges Log: {path}").format(path=log_path)
    return message


async def wait_health_async(
    base_url: str, timeout_s: float, headers: dict[str, str] | None = None, proc: Any = None
) -> float:
    """Wartet, bis /health antwortet.

    Mit ``proc`` wird bei jedem Versuch geprueft, ob der Server noch laeuft:
    ein sofort abgestuerzter llama-server wird dann direkt mit Exitcode und
    Log-Auszug gemeldet, statt erst nach ``timeout_s`` mit einem nichtssagenden
    Verbindungsfehler.
    """
    started = time.time()
    deadline = started + timeout_s
    last_error = ""
    async with httpx.AsyncClient() as client:
        while time.time() < deadline:
            code = _exited_code(proc)
            if code is not None:
                raise RuntimeError(server_exit_message(proc, code))
            try:
                r = await client.get(
                    base_url.rstrip("/") + "/health", timeout=5, headers=headers or {}
                )
                if r.status_code == 200:
                    return time.time() - started
                last_error = f"HTTP {r.status_code}: {r.text[:200]}"
            except Exception as exc:
                last_error = str(exc)
            await asyncio.sleep(1)
    message = _("llama-server wurde nicht bereit: {error}").format(error=last_error)
    log_path = getattr(proc, "_llmbench_log_path", None)
    tail = log_tail(log_path)
    if tail:
        message += "\n" + _("Letzte Zeilen aus dem Server-Log:") + "\n" + tail
    raise TimeoutError(message)


def wait_health(
    base_url: str, timeout_s: float, headers: dict[str, str] | None = None, proc: Any = None
) -> float:
    """Synchronous wrapper using nested event loop compatibility."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(wait_health_async(base_url, timeout_s, headers, proc))

    return loop.run_until_complete(wait_health_async(base_url, timeout_s, headers, proc))


def port_in_use(host: str, port: int) -> bool:
    """True, wenn auf host:port schon etwas lauscht (z. B. ein haengengebliebener llama-server)."""
    import socket

    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def start_llama_server(
    exe: str,
    model_path: str,
    profile: dict[str, Any],
    endpoint_cfg: dict[str, Any],
    bench_cfg: dict[str, Any],
    log_path: Path,
) -> tuple[subprocess.Popen[Any], str]:
    """Startet llama-server mit denselben Kernparametern wie llama-bench."""
    exe = resolve_executable(exe)
    parsed = urlparse(endpoint_cfg["base_url"])
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8080
    gpu_layers = profile.get("gpu_layers", -1)
    server_ngl = "all" if str(gpu_layers) == "-1" else str(gpu_layers)

    cmd = [
        exe,
        "-m", model_path,
        "--host", host,
        "--port", str(port),
        "-c", str(endpoint_cfg["context_size"]),
        "-np", str(endpoint_cfg["parallel_slots"]),
        "-ngl", server_ngl,
    ]
    # CPU-only: Modell muss vollstaendig in den RAM geladen werden.
    if profile.get("no_mmap") or str(gpu_layers) == "0":
        cmd.append("--no-mmap")
    if profile.get("mlock"):
        cmd.append("--mlock")

    if endpoint_cfg.get("fit"):
        cmd.append("--fit")
        if str(endpoint_cfg["fit"]).lower() == "on":
            cmd.append("on")
    if endpoint_cfg.get("fit_target"):
        cmd.extend(["--fit-target", str(endpoint_cfg["fit_target"])])
    if endpoint_cfg.get("jinja"):
        cmd.append("--jinja")

    reasoning = endpoint_cfg.get("reasoning")
    if reasoning is not None:
        if isinstance(reasoning, bool):
            if reasoning:
                cmd.append("--reasoning")
        else:
            cmd.extend(["--reasoning", str(reasoning)])
    cmd += [
        "-b", str(bench_cfg["batch_size"]),
        "-ub", str(bench_cfg["ubatch_size"]),
        "-fa", normalize_flash_attention(bench_cfg.get("flash_attention", "auto")),
        "-ctk", str(bench_cfg.get("cache_type_k", "f16")),
        "-ctv", str(bench_cfg.get("cache_type_v", "f16")),
        "--no-cache-prompt",
        "--metrics",
    ]
    threads = profile.get("threads", "auto")
    if threads not in (None, "auto", -1):
        cmd.extend(["-t", str(threads)])
    if profile.get("cpu_moe_layers") is not None:
        cmd.extend(["-ncmoe", str(profile["cpu_moe_layers"])])
    if profile.get("device"):
        cmd.extend(["-dev", str(profile["device"])])
    if profile.get("tensor_split"):
        cmd.extend(["-ts", str(profile["tensor_split"])])
    if endpoint_cfg.get("api_key"):
        cmd.extend(["--api-key", str(endpoint_cfg["api_key"])])
    for item in endpoint_cfg.get("server_additional_args", []) or []:
        cmd.append(str(item))

    if port_in_use(host, port):
        raise RuntimeError(
            _("Port {port} ist bereits belegt (laeuft noch ein anderer llama-server?).").format(port=port)
        )

    log_f = open(log_path, "w", encoding="utf-8")  # noqa: SIM115
    try:
        proc = subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT, text=True)
    except Exception:
        log_f.close()
        raise
    proc._llmbench_log_file = log_f  # type: ignore[attr-defined]
    proc._llmbench_log_path = str(log_path)  # type: ignore[attr-defined]
    printable = list(cmd)
    if "--api-key" in printable:
        printable[printable.index("--api-key") + 1] = "***"
    return proc, " ".join(printable)


def stop_llama_server(proc: subprocess.Popen[Any]) -> None:
    kill_process_tree(proc)
    with contextlib.suppress(Exception):
        proc._llmbench_log_file.close()  # type: ignore[attr-defined]


def api_style_for(cfg: dict[str, Any]) -> str:
    """API-Dialekt fuer diesen Endpoint.

    Historisch kannte llmbench nur llama.cpp und dort die Unterscheidung
    "Chat-Format ja/nein". Das ist jetzt nur noch einer von mehreren Dialekten;
    ``api_style`` kann explizit gesetzt werden, sonst gilt die alte Regel.
    """
    explicit = cfg.get("api_style")
    if explicit:
        return str(explicit)
    return API_STYLE_LLAMA_CPP_CHAT if cfg.get("chat_format", False) else API_STYLE_LLAMA_CPP


async def _one_completion_async(
    client: httpx.AsyncClient,
    base_url: str,
    prompt_or_messages: Any,
    cfg: dict[str, Any],
    request_id: int,
) -> dict[str, Any]:
    """Duenne Huelle um die gemeinsame Logik in ``http_bench``."""
    return await one_completion_async(
        client, base_url, prompt_or_messages, cfg, request_id, api_style=api_style_for(cfg)
    )


async def _run_level_async(
    base_url: str,
    cfg: dict[str, Any],
    concurrency: int,
    count: int,
    datasets: list[Any] | None = None,
) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(headers=auth_headers(cfg)) as client:

        async def wrapped_task(i: int) -> dict[str, Any]:
            item = random.choice(datasets) if datasets else str(cfg["prompt"])
            async with semaphore:
                return await _one_completion_async(client, base_url, item, cfg, i)

        tasks = [wrapped_task(i) for i in range(count)]
        return await asyncio.gather(*tasks)


async def _run_endpoint_load_async(
    base_url: str,
    cfg: dict[str, Any],
    telemetry_interval: float,
    out_dir: Path,
    target_pid: int | None = None,
) -> dict[str, Any]:
    levels = [int(x) for x in cfg["concurrency"]]
    warmup_n = int(cfg.get("warmup_requests", 0) or 0)
    warmup_info: dict[str, Any] = {"requests": warmup_n}

    datasets = None
    if cfg.get("dataset_path"):
        try:
            dataset_path = Path(cfg["dataset_path"])
            datasets = []
            with dataset_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        datasets.append(json.loads(line))
        except Exception as e:
            raise ValueError(
                f"Fehler beim Laden des Datensatzes {cfg['dataset_path']}: {e}"
            ) from e

    if warmup_n > 0:
        w_started = time.perf_counter()
        w_results = await _run_level_async(base_url, cfg, 1, warmup_n, datasets=datasets)
        warmup_info.update({
            "duration_seconds": time.perf_counter() - w_started,
            "successful": sum(1 for x in w_results if x["ok"]),
            "discarded": True,
        })

    monitor = ResourceMonitor(telemetry_interval)
    monitor.start()
    if target_pid:
        monitor.set_target_pid(target_pid)

    all_levels: list[dict[str, Any]] = []
    total_started = time.perf_counter()
    for concurrency in levels:
        requests_n = max(int(cfg["requests_per_level"]), concurrency)
        level_started = time.perf_counter()
        results = await _run_level_async(base_url, cfg, concurrency, requests_n, datasets=datasets)
        wall = time.perf_counter() - level_started

        ok = [x for x in results if x["ok"]]
        total_tokens = sum(int(x["output_tokens"]) for x in ok)
        ttfts = [float(x["ttft_seconds"]) for x in ok if x["ttft_seconds"] is not None]
        request_tps = [float(x["request_tps"]) for x in ok if x["request_tps"] is not None]
        short = [x for x in ok if int(x["output_tokens"]) < int(x["requested_tokens"])]

        level: dict[str, Any] = {
            "concurrency": concurrency,
            "requests": requests_n,
            "successful": len(ok),
            "failed": requests_n - len(ok),
            "wall_seconds": wall,
            "total_output_tokens": total_tokens,
            "system_tps": (total_tokens / wall) if wall > 0 else 0.0,
            "avg_interactivity_tps": statistics.fmean(request_tps) if request_tps else None,
            "ttft_p50_seconds": percentile(ttfts, 0.50),
            "ttft_p95_seconds": percentile(ttfts, 0.95),
            "short_responses": len(short),
            "request_details": results,
        }
        if short:
            level["note"] = (
                f"{len(short)} von {len(ok)} Antworten waren kuerzer als angefordert. "
                "Ohne ignore_eos sind die Tokenzahlen zwischen Laeufen nicht vergleichbar."
            )
        all_levels.append(level)
        await asyncio.sleep(1)

    telemetry = monitor.stop()
    result = {
        "status": "ok",
        "started_at": utc_now_iso(),
        "duration_seconds": time.perf_counter() - total_started,
        "base_url": base_url,
        "warmup": warmup_info,
        "settings": {
            "max_tokens": cfg.get("max_tokens"),
            "temperature": cfg.get("temperature"),
            "seed": cfg.get("seed"),
            "ignore_eos": cfg.get("ignore_eos"),
            "requests_per_level": cfg.get("requests_per_level"),
            "context_size": cfg.get("context_size"),
            "parallel_slots": cfg.get("parallel_slots"),
        },
        "levels": all_levels,
        "telemetry": telemetry,
    }
    write_json(out_dir / "endpoint_load.json", result)

    light = dict(result)
    light["telemetry"] = strip_samples(telemetry)
    light["levels"] = [{k: v for k, v in lv.items() if k != "request_details"} for lv in all_levels]
    light["details_stored_in"] = "endpoint_load.json"
    return light


def run_endpoint_load(
    base_url: str,
    cfg: dict[str, Any],
    telemetry_interval: float,
    out_dir: Path,
    target_pid: int | None = None,
) -> dict[str, Any]:
    """Synchronous wrapper to run the async load test."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_run_endpoint_load_async(base_url, cfg, telemetry_interval, out_dir, target_pid))

    return loop.run_until_complete(
        _run_endpoint_load_async(base_url, cfg, telemetry_interval, out_dir, target_pid)
    )
