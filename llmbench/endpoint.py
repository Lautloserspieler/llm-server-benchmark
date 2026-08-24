from __future__ import annotations

import concurrent.futures
import json
import math
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .monitor import ResourceMonitor
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


def wait_health(base_url: str, timeout_s: float) -> None:
    deadline = time.time() + timeout_s
    last_error = ""
    while time.time() < deadline:
        try:
            r = httpx.get(base_url.rstrip("/") + "/health", timeout=5)
            if r.status_code == 200:
                return
            last_error = f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1)
    raise TimeoutError(f"llama-server did not become healthy: {last_error}")


def start_llama_server(exe: str, model_path: str, profile: dict[str, Any], endpoint_cfg: dict[str, Any], log_path: Path) -> tuple[subprocess.Popen[Any], str]:
    exe = resolve_executable(exe)
    parsed = urlparse(endpoint_cfg["base_url"])
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8080
    gpu_layers = profile.get("gpu_layers", -1)
    server_ngl = "all" if str(gpu_layers) == "-1" else str(gpu_layers)
    cmd = [exe, "-m", model_path, "--host", host, "--port", str(port), "-c", str(endpoint_cfg["context_size"]), "-np", str(endpoint_cfg["parallel_slots"]), "-ngl", server_ngl, "--no-cache-prompt", "--metrics", "-fa", "auto"]
    threads = profile.get("threads", "auto")
    if threads not in (None, "auto", -1):
        cmd.extend(["-t", str(threads)])
    if profile.get("cpu_moe_layers") is not None:
        cmd.extend(["-ncmoe", str(profile["cpu_moe_layers"])])
    for item in endpoint_cfg.get("server_additional_args", []) or []:
        cmd.append(str(item))
    log_f = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT, text=True)
    proc._llmbench_log_file = log_f  # type: ignore[attr-defined]
    return proc, " ".join(cmd)


def stop_llama_server(proc: subprocess.Popen[Any]) -> None:
    kill_process_tree(proc)
    try:
        getattr(proc, "_llmbench_log_file").close()
    except Exception:
        pass


def _one_completion(base_url: str, prompt: str, max_tokens: int, temperature: float, timeout: float, request_id: int) -> dict[str, Any]:
    payload = {"prompt": f"{prompt}\nBenchmark request id: {request_id}", "n_predict": max_tokens, "temperature": temperature, "stream": True, "return_tokens": True, "cache_prompt": False}
    started = time.perf_counter()
    ttft: float | None = None
    token_count = 0
    content_chars = 0
    final_data: dict[str, Any] = {}
    error: str | None = None
    try:
        with httpx.Client(timeout=timeout) as client:
            with client.stream("POST", base_url.rstrip("/") + "/completion", json=payload) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
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
    exact_total = timings.get("predicted_n") or timings.get("tokens_predicted")
    if exact_total is not None:
        try:
            token_count = int(exact_total)
        except Exception:
            pass
    duration = finished - started
    return {"request_id": request_id, "ok": error is None, "error": error, "duration_seconds": duration, "ttft_seconds": ttft, "output_tokens": token_count, "output_chars": content_chars, "request_tps": (token_count / duration) if duration > 0 and token_count else 0.0, "server_timings": timings}


def run_endpoint_load(base_url: str, cfg: dict[str, Any], telemetry_interval: float, out_dir: Path) -> dict[str, Any]:
    levels = [int(x) for x in cfg["concurrency"]]
    all_levels: list[dict[str, Any]] = []
    monitor = ResourceMonitor(telemetry_interval)
    monitor.start()
    total_started = time.perf_counter()
    for concurrency in levels:
        requests_n = max(int(cfg["requests_per_level"]), concurrency)
        level_started = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(_one_completion, base_url, str(cfg["prompt"]), int(cfg["max_tokens"]), float(cfg.get("temperature", 0.0)), float(cfg.get("timeout_seconds", 600)), i) for i in range(requests_n)]
            results = [f.result() for f in futures]
        wall = time.perf_counter() - level_started
        ok = [x for x in results if x["ok"]]
        total_tokens = sum(int(x["output_tokens"]) for x in ok)
        ttfts = [float(x["ttft_seconds"]) for x in ok if x["ttft_seconds"] is not None]
        request_tps = [float(x["request_tps"]) for x in ok if x["request_tps"] is not None]
        all_levels.append({"concurrency": concurrency, "requests": requests_n, "successful": len(ok), "failed": requests_n - len(ok), "wall_seconds": wall, "total_output_tokens": total_tokens, "system_tps": (total_tokens / wall) if wall > 0 else 0.0, "avg_interactivity_tps": statistics.fmean(request_tps) if request_tps else None, "ttft_p50_seconds": percentile(ttfts, 0.50), "ttft_p95_seconds": percentile(ttfts, 0.95), "request_details": results})
        time.sleep(1)
    telemetry = monitor.stop()
    result = {"status": "ok", "started_at": utc_now_iso(), "duration_seconds": time.perf_counter() - total_started, "base_url": base_url, "levels": all_levels, "telemetry": telemetry}
    write_json(out_dir / "endpoint_load.json", result)
    return result
