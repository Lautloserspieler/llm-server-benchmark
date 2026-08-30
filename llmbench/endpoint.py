from __future__ import annotations

import asyncio
import contextlib
import json
import math
import re
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import normalize_flash_attention
from .monitor import ResourceMonitor, strip_samples
from .utils import kill_process_tree, resolve_executable, utc_now_iso, write_json

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

def _auth_headers(cfg: dict[str, Any]) -> dict[str, str]:
    key = cfg.get("api_key")
    return {"Authorization": f"Bearer {key}"} if key else {}

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

    async with httpx.AsyncClient(headers=_auth_headers(cfg)) as client:
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
                        errors.append(f"Test {i+1} fehlgeschlagen. Erwartet Regex '{expected_regex}', erhalten: {content!r}")
                else:
                    # Wenn kein regex, dann reicht es, dass es nicht abstuerzt
                    passed += 1
            except Exception as exc:
                errors.append(f"Test {i+1} Fehler: {exc}")

    if errors:
        return False, "; ".join(errors)
    return True, f"Sanity check bestanden ({passed}/{len(tests)} Tests)."


async def wait_health_async(base_url: str, timeout_s: float, headers: dict[str, str] | None = None) -> float:
    started = time.time()
    deadline = started + timeout_s
    last_error = ""
    async with httpx.AsyncClient() as client:
        while time.time() < deadline:
            try:
                r = await client.get(base_url.rstrip("/") + "/health", timeout=5, headers=headers or {})
                if r.status_code == 200:
                    return time.time() - started
                last_error = f"HTTP {r.status_code}: {r.text[:200]}"
            except Exception as exc:
                last_error = str(exc)
            await asyncio.sleep(1)
    raise TimeoutError(f"llama-server wurde nicht bereit: {last_error}")

def wait_health(base_url: str, timeout_s: float, headers: dict[str, str] | None = None) -> float:
    """Synchronous wrapper for backward compatibility."""
    return asyncio.run(wait_health_async(base_url, timeout_s, headers))

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

    log_f = open(log_path, "w", encoding="utf-8")  # noqa: SIM115
    try:
        proc = subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT, text=True)
    except Exception:
        log_f.close()
        raise
    proc._llmbench_log_file = log_f  # type: ignore[attr-defined]
    printable = list(cmd)
    if "--api-key" in printable:
        printable[printable.index("--api-key") + 1] = "***"
    return proc, " ".join(printable)

def stop_llama_server(proc: subprocess.Popen[Any]) -> None:
    kill_process_tree(proc)
    with contextlib.suppress(Exception):
        proc._llmbench_log_file.close()  # type: ignore[attr-defined]

async def _one_completion_async(
    client: httpx.AsyncClient,
    base_url: str,
    prompt_or_messages: Any,
    cfg: dict[str, Any],
    request_id: int,
) -> dict[str, Any]:
    max_tokens = int(cfg["max_tokens"])
    chat_format = cfg.get("chat_format", False)

    payload: dict[str, Any] = {
        "n_predict": max_tokens,
        "temperature": float(cfg.get("temperature", 0.0)),
        "stream": True,
        "cache_prompt": False,
    }

    endpoint_path = "/completion"
    if chat_format:
        endpoint_path = "/v1/chat/completions"
        payload["messages"] = prompt_or_messages
        # n_predict is not standard in OpenAI API, max_tokens is
        payload["max_tokens"] = max_tokens
        payload.pop("n_predict", None)
    else:
        payload["prompt"] = f"{prompt_or_messages}\nBenchmark request id: {request_id}"
        payload["return_tokens"] = True
    if cfg.get("ignore_eos", True):
        payload["ignore_eos"] = True
    if cfg.get("seed") is not None:
        payload["seed"] = int(cfg["seed"])

    timeout = float(cfg.get("timeout_seconds", 600))
    started = time.perf_counter()
    ttft: float | None = None
    token_count = 0
    content_chars = 0
    final_data: dict[str, Any] = {}
    error: str | None = None
    try:
        async with client.stream("POST", base_url.rstrip("/") + endpoint_path, json=payload, timeout=timeout) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                text = line.strip()
                if text.startswith("data:"):
                    text = text[5:].strip()
                if text == "[DONE]":
                    continue
                try:
                    data = json.loads(text)
                except Exception:
                    continue

                # In chat_format, we need to extract from choices[0].delta
                if chat_format:
                    choices = data.get("choices") or []
                    if choices:
                        delta = choices[0].get("delta") or {}
                        content = delta.get("content") or ""
                        # Note: OpenAI stream usually doesn't return tokens count in stream
                        # Some servers send usage in the last chunk
                        tokens = [1] if content else []
                else:
                    tokens = data.get("tokens") or []
                    content = data.get("content") or ""

                if ttft is None and (tokens or content):
                    ttft = time.perf_counter() - started
                token_count += len(tokens)
                content_chars += len(content)
                final_data = data
    except Exception as exc:
        error = str(exc)
    finished = time.perf_counter()

    timings = final_data.get("timings") or {}
    usage = final_data.get("usage") or {} # for openai format

    exact_total = timings.get("predicted_n") or timings.get("tokens_predicted") or usage.get("completion_tokens")
    if exact_total is not None:
        with contextlib.suppress(Exception):
            token_count = int(exact_total)
    duration = finished - started
    return {
        "request_id": request_id,
        "ok": error is None,
        "error": error,
        "duration_seconds": duration,
        "ttft_seconds": ttft,
        "output_tokens": token_count,
        "requested_tokens": max_tokens,
        "output_chars": content_chars,
        "request_tps": (token_count / duration) if duration > 0 and token_count else 0.0,
        "server_timings": timings,
    }

async def _run_level_async(base_url: str, cfg: dict[str, Any], concurrency: int, count: int, datasets: list[Any] | None = None) -> list[dict[str, Any]]:
    import random
    semaphore = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(headers=_auth_headers(cfg)) as client:
        async def wrapped_task(i):
            # Select random item from dataset if available, otherwise use default prompt
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
            raise ValueError(f"Fehler beim Laden des Datensatzes {cfg['dataset_path']}: {e}") from e

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
    return asyncio.run(_run_endpoint_load_async(base_url, cfg, telemetry_interval, out_dir, target_pid))
