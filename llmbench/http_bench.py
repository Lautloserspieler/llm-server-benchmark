"""HTTP-basierte Bench-Engine - das Gegenstueck zu ``llama_bench.py``.

llama.cpp bringt mit ``llama-bench`` ein eigenes Messwerkzeug mit. vLLM (und
spaeter Ollama/TGI) haben das nicht: dort existiert nur ein HTTP-Server. Die
pp/tg/long-context-Werte werden deshalb hier ueber kalibrierte Einzelrequests
gegen den bereits laufenden Server gemessen und im gleichen Zeilenformat
ausgegeben, das ``llama_bench.flatten_bench_rows()`` erwartet - damit
funktionieren Berichte, CSV und ``compare.py`` unveraendert weiter.

``one_completion_async`` ist die gemeinsame Anfrage-/Streaming-/Tokenzaehl-Logik
fuer alle HTTP-Backends. ``endpoint.py`` nutzt exakt dieselbe Funktion, damit es
die Logik nicht zweimal gibt.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import statistics
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from .monitor import ResourceMonitor, strip_samples
from .utils import utc_now_iso, write_json

# Unterstuetzte API-Dialekte. "ollama_native" kommt in einer spaeteren Phase
# dazu und braucht dann nur je einen Zweig in _build_request/_extract_delta.
API_STYLE_LLAMA_CPP = "llama_cpp"
API_STYLE_LLAMA_CPP_CHAT = "llama_cpp_chat"
API_STYLE_OPENAI_COMPLETIONS = "openai_completions"
API_STYLES = (API_STYLE_LLAMA_CPP, API_STYLE_LLAMA_CPP_CHAT, API_STYLE_OPENAI_COMPLETIONS)

# Grobe Umrechnung fuer die Fuelltexte. Der Schaetzwert wird nur zum Bauen des
# Prompts benutzt; gemessen wird anschliessend mit usage.prompt_tokens, also mit
# der echten Tokenzahl des Servers.
CHARS_PER_TOKEN = 4.0

_FILLER_WORDS = (
    "Messung", "Kontext", "System", "Speicher", "Ablauf", "Bericht",
    "Struktur", "Verfahren", "Modell", "Rechner", "Analyse", "Ergebnis",
    "Laufzeit", "Auslastung", "Vergleich", "Protokoll",
)

_SHORT_PROMPT = "Zaehle ruhig weiter und beschreibe dabei den Messaufbau."

ProgressFn = Callable[[str, dict[str, Any] | None], None]


# --------------------------------------------------------------- Fuelltexte


def build_filler_prompt(target_tokens: int, nonce: str = "") -> str:
    """Fuelltext von ungefaehr ``target_tokens`` Tokens Laenge.

    Der ``nonce`` steht bewusst ganz am Anfang: vLLM hat Prefix-Caching
    standardmaessig aktiv, und ein wiederholt identischer Prompt wuerde ab der
    zweiten Wiederholung gar nicht mehr verarbeitet - die gemessene
    Prompt-Verarbeitung waere dann reine Cache-Trefferzeit. Ein eindeutiger
    Anfang macht jeden Request zu einem echten Cache-Miss, ganz ohne sich auf
    ein imageabhaengiges Server-Flag verlassen zu muessen.
    """
    if target_tokens <= 0:
        return nonce or "."

    budget = max(1, int(round(target_tokens * CHARS_PER_TOKEN)))
    parts: list[str] = []
    length = 0
    if nonce:
        head = f"{nonce} "
        parts.append(head)
        length += len(head)

    index = 0
    while length < budget:
        word = _FILLER_WORDS[index % len(_FILLER_WORDS)]
        index += 1
        parts.append(word + " ")
        length += len(word) + 1

    return "".join(parts)[:budget] or "."


def _nonce(label: str, repetition: int) -> str:
    return f"[{label}#{repetition}-{uuid.uuid4().hex[:10]}]"


# ------------------------------------------------- gemeinsame Request-Logik


def _build_request(
    api_style: str,
    prompt_or_messages: Any,
    cfg: dict[str, Any],
    request_id: int,
) -> tuple[str, dict[str, Any]]:
    """(Pfad, JSON-Payload) fuer den gewaehlten API-Dialekt."""
    max_tokens = int(cfg["max_tokens"])
    temperature = float(cfg.get("temperature", 0.0))

    if api_style == API_STYLE_OPENAI_COMPLETIONS:
        # Bewusst /v1/completions statt /v1/chat/completions: ein roher Prompt
        # ohne Chat-Template haelt die gemessene Tokenzahl unter Kontrolle.
        payload: dict[str, Any] = {
            "prompt": str(prompt_or_messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            # Erst dadurch traegt der letzte SSE-Chunk exakte Tokenzahlen.
            "stream_options": {"include_usage": True},
        }
        if cfg.get("min_tokens") is not None:
            payload["min_tokens"] = int(cfg["min_tokens"])
        if "top_p" in cfg:
            payload["top_p"] = float(cfg["top_p"])
        if "top_k" in cfg:
            payload["top_k"] = int(cfg["top_k"])
        if "repeat_penalty" in cfg:
            payload["repetition_penalty"] = float(cfg["repeat_penalty"])
        if cfg.get("ignore_eos"):
            payload["ignore_eos"] = True
        if cfg.get("seed") is not None:
            payload["seed"] = int(cfg["seed"])
        return "/v1/completions", payload

    payload = {
        "n_predict": max_tokens,
        "temperature": temperature,
        "stream": True,
        "cache_prompt": False,
    }
    if "top_p" in cfg:
        payload["top_p"] = float(cfg["top_p"])
    if "top_k" in cfg:
        payload["top_k"] = int(cfg["top_k"])
    if "repeat_penalty" in cfg:
        payload["repeat_penalty"] = float(cfg["repeat_penalty"])

    if api_style == API_STYLE_LLAMA_CPP_CHAT:
        path = "/v1/chat/completions"
        payload["messages"] = prompt_or_messages
        payload["max_tokens"] = max_tokens
        payload.pop("n_predict", None)
    else:
        path = "/completion"
        payload["prompt"] = f"{prompt_or_messages}\nBenchmark request id: {request_id}"
        payload["return_tokens"] = True

    if cfg.get("ignore_eos", True):
        payload["ignore_eos"] = True
    if cfg.get("seed") is not None:
        payload["seed"] = int(cfg["seed"])
    return path, payload


def _extract_delta(api_style: str, data: dict[str, Any]) -> tuple[int, str]:
    """(Anzahl neuer Tokens, neuer Text) aus einem SSE-Chunk."""
    if api_style == API_STYLE_LLAMA_CPP:
        tokens = data.get("tokens") or []
        return len(tokens), data.get("content") or ""

    choices = data.get("choices") or []
    if not choices:
        # Bei include_usage traegt der letzte Chunk nur noch usage.
        return 0, ""

    if api_style == API_STYLE_LLAMA_CPP_CHAT:
        delta = choices[0].get("delta") or {}
        content = delta.get("content") or ""
    else:
        content = choices[0].get("text") or ""
    return (1 if content else 0), content


async def one_completion_async(
    client: httpx.AsyncClient,
    base_url: str,
    prompt_or_messages: Any,
    cfg: dict[str, Any],
    request_id: int,
    api_style: str = API_STYLE_LLAMA_CPP,
) -> dict[str, Any]:
    """Ein einzelner Streaming-Request mit TTFT- und Tokenmessung.

    Gemeinsame Grundlage fuer den Endpoint-Lasttest und die pp/tg-Messungen.
    """
    if api_style not in API_STYLES:
        raise ValueError(f"Unbekannter API-Stil: {api_style!r}. Erlaubt: {', '.join(API_STYLES)}")

    path, payload = _build_request(api_style, prompt_or_messages, cfg, request_id)
    max_tokens = int(cfg["max_tokens"])
    timeout = float(cfg.get("timeout_seconds", 600))

    started = time.perf_counter()
    ttft: float | None = None
    token_count = 0
    content_chars = 0
    final_data: dict[str, Any] = {}
    usage: dict[str, Any] = {}
    error: str | None = None

    try:
        async with client.stream(
            "POST", base_url.rstrip("/") + path, json=payload, timeout=timeout
        ) as resp:
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
                except json.JSONDecodeError:
                    continue

                tokens, content = _extract_delta(api_style, data)
                if ttft is None and (tokens or content):
                    ttft = time.perf_counter() - started
                token_count += tokens
                content_chars += len(content)
                if data.get("usage"):
                    usage = data["usage"]
                final_data = data
    except Exception as exc:
        error = str(exc)

    finished = time.perf_counter()

    timings = final_data.get("timings") or {}
    if not usage:
        usage = final_data.get("usage") or {}

    exact_total = (
        timings.get("predicted_n")
        or timings.get("tokens_predicted")
        or usage.get("completion_tokens")
    )
    if exact_total is not None:
        with contextlib.suppress(Exception):
            token_count = int(exact_total)

    prompt_tokens: int | None = None
    raw_prompt_tokens = timings.get("prompt_n") or usage.get("prompt_tokens")
    if raw_prompt_tokens is not None:
        with contextlib.suppress(Exception):
            prompt_tokens = int(raw_prompt_tokens)

    duration = finished - started
    return {
        "request_id": request_id,
        "ok": error is None,
        "error": error,
        "duration_seconds": duration,
        "ttft_seconds": ttft,
        "output_tokens": token_count,
        "requested_tokens": max_tokens,
        "prompt_tokens": prompt_tokens,
        "output_chars": content_chars,
        "request_tps": (token_count / duration) if duration > 0 and token_count else 0.0,
        "server_timings": timings,
        "usage": usage,
    }


# ------------------------------------------------------------- Messschleifen


def _row(
    test: str,
    samples: list[float],
    *,
    n_prompt: int,
    n_gen: int,
    n_depth: int,
    backend_name: str,
) -> dict[str, Any]:
    """Ergebniszeile im Format, das flatten_bench_rows() liest.

    Felder, die es nur bei llama-bench gibt (Threads, GPU-Layer, Build-Nummer,
    Modellmetadaten), bleiben bewusst None statt geraten zu werden.
    """
    return {
        "test": test,
        "avg_ts": statistics.fmean(samples) if samples else None,
        "stddev_ts": statistics.stdev(samples) if len(samples) > 1 else 0.0,
        "n_prompt": n_prompt,
        "n_gen": n_gen,
        "n_depth": n_depth,
        "n_threads": None,
        "n_gpu_layers": None,
        "backend": backend_name,
        "model_type": None,
        "model_n_params": None,
        "model_size": None,
        "build_commit": None,
        "build_number": None,
        "cpu_info": None,
        "gpu_info": None,
        "samples_ts": samples,
        "repetitions": len(samples),
    }


def _completion_cfg(base: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "temperature": 0.0,
        "seed": base.get("seed", 42),
        "timeout_seconds": float(base.get("timeout_seconds", 3600)),
    }
    cfg.update(overrides)
    return cfg


async def _measure(
    client: httpx.AsyncClient,
    base_url: str,
    prompt: str,
    cfg: dict[str, Any],
    request_id: int,
) -> dict[str, Any]:
    return await one_completion_async(
        client, base_url, prompt, cfg, request_id, api_style=API_STYLE_OPENAI_COMPLETIONS
    )


async def _run_prompt_kind(
    client: httpx.AsyncClient,
    base_url: str,
    bench_cfg: dict[str, Any],
    backend_name: str,
    reps: int,
    details: list[dict[str, Any]],
    errors: list[str],
    report: Callable[[str], None],
) -> list[dict[str, Any]]:
    """Prompt-Verarbeitung: TTFT bei max_tokens=1 ist reine Prefill-Zeit."""
    rows: list[dict[str, Any]] = []
    request_id = 0
    for n in bench_cfg["prompt_tokens"]:
        samples: list[float] = []
        for rep in range(reps):
            prompt = build_filler_prompt(int(n), _nonce(f"pp{n}", rep))
            cfg = _completion_cfg(bench_cfg, max_tokens=1)
            report(f"pp{n} · Wiederholung {rep + 1}/{reps}")
            res = await _measure(client, base_url, prompt, cfg, request_id)
            request_id += 1
            details.append({"test": f"pp{n}", "repetition": rep, **_detail(res)})
            if not res["ok"]:
                errors.append(f"pp{n}: {res['error']}")
                continue
            ttft = res["ttft_seconds"] or res["duration_seconds"]
            tokens = res["prompt_tokens"] or int(n)
            if ttft and ttft > 0:
                samples.append(tokens / ttft)
        rows.append(_row(f"pp{n}", samples, n_prompt=int(n), n_gen=0, n_depth=0,
                         backend_name=backend_name))
    return rows


async def _run_generation_kind(
    client: httpx.AsyncClient,
    base_url: str,
    bench_cfg: dict[str, Any],
    backend_name: str,
    reps: int,
    details: list[dict[str, Any]],
    errors: list[str],
    report: Callable[[str], None],
) -> list[dict[str, Any]]:
    """Textgenerierung: Tokens nach dem ersten, geteilt durch die Zeit danach."""
    rows: list[dict[str, Any]] = []
    request_id = 0
    for n in bench_cfg["generation_tokens"]:
        samples: list[float] = []
        for rep in range(reps):
            prompt = f"{_nonce(f'tg{n}', rep)} {_SHORT_PROMPT}"
            # ignore_eos und min_tokens zusammen: das erste erlaubt dem Modell
            # nicht, frueh aufzuhoeren, das zweite erzwingt die Zielmenge auch
            # dann, wenn eine Server-Version ignore_eos nicht beachtet. Ohne das
            # waeren die Tokenzahlen zwischen Wiederholungen nicht vergleichbar.
            cfg = _completion_cfg(
                bench_cfg, max_tokens=int(n), min_tokens=int(n), ignore_eos=True
            )
            report(f"tg{n} · Wiederholung {rep + 1}/{reps}")
            res = await _measure(client, base_url, prompt, cfg, request_id)
            request_id += 1
            details.append({"test": f"tg{n}", "repetition": rep, **_detail(res)})
            if not res["ok"]:
                errors.append(f"tg{n}: {res['error']}")
                continue
            produced = res["output_tokens"] or int(n)
            ttft = res["ttft_seconds"] or 0.0
            gen_seconds = res["duration_seconds"] - ttft
            if gen_seconds > 0 and produced:
                samples.append(produced / gen_seconds)
        rows.append(_row(f"tg{n}", samples, n_prompt=0, n_gen=int(n), n_depth=0,
                         backend_name=backend_name))
    return rows


async def _run_long_context_kind(
    client: httpx.AsyncClient,
    base_url: str,
    bench_cfg: dict[str, Any],
    backend_name: str,
    reps: int,
    details: list[dict[str, Any]],
    errors: list[str],
    report: Callable[[str], None],
) -> list[dict[str, Any]]:
    """Kombinierter pp+tg-Durchsatz bei wachsender Kontexttiefe.

    Entspricht llama-bench mit ``-p P -n N -d D``: erst D Tokens Kontext, dann
    P Prompt-Tokens und N generierte Tokens; berichtet wird der Gesamtdurchsatz.
    """
    rows: list[dict[str, Any]] = []
    prompt_tokens = int(bench_cfg["long_context_prompt_tokens"])
    gen_tokens = int(bench_cfg["long_context_generation_tokens"])
    request_id = 0

    for depth in bench_cfg["context_depths"]:
        depth = int(depth)
        name = f"pg{prompt_tokens}+{gen_tokens}@d{depth}" if depth else f"pg{prompt_tokens}+{gen_tokens}"
        samples: list[float] = []
        for rep in range(reps):
            prompt = build_filler_prompt(depth + prompt_tokens, _nonce(name, rep))
            cfg = _completion_cfg(
                bench_cfg, max_tokens=gen_tokens, min_tokens=gen_tokens, ignore_eos=True
            )
            report(f"{name} · Wiederholung {rep + 1}/{reps}")
            res = await _measure(client, base_url, prompt, cfg, request_id)
            request_id += 1
            details.append({"test": name, "repetition": rep, **_detail(res)})
            if not res["ok"]:
                errors.append(f"{name}: {res['error']}")
                continue
            produced = res["output_tokens"] or gen_tokens
            consumed = res["prompt_tokens"] or (depth + prompt_tokens)
            duration = res["duration_seconds"]
            if duration > 0:
                samples.append((consumed + produced) / duration)
        rows.append(_row(name, samples, n_prompt=prompt_tokens, n_gen=gen_tokens,
                         n_depth=depth, backend_name=backend_name))
    return rows


def _detail(res: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": res["ok"],
        "error": res["error"],
        "duration_seconds": res["duration_seconds"],
        "ttft_seconds": res["ttft_seconds"],
        "prompt_tokens": res["prompt_tokens"],
        "output_tokens": res["output_tokens"],
        "usage": res["usage"],
    }


_KIND_RUNNERS = {
    "prompt": _run_prompt_kind,
    "generation": _run_generation_kind,
    "long_context": _run_long_context_kind,
}


async def _run_http_bench_async(
    base_url: str,
    headers: dict[str, str] | None,
    bench_cfg: dict[str, Any],
    profile: dict[str, Any],
    kind: str,
    out_dir: Path,
    on_progress: ProgressFn | None,
    backend_name: str,
    target_pid: int | None,
) -> dict[str, Any]:
    runner = _KIND_RUNNERS.get(kind)
    if runner is None:
        raise ValueError(f"Unbekannte Testart: {kind}")

    reps = max(1, int(bench_cfg.get("repetitions", 1)))
    details: list[dict[str, Any]] = []
    errors: list[str] = []

    monitor = ResourceMonitor(float(bench_cfg.get("resource_sample_interval", 0.5)))
    # Erst der Monitor (wartet ggf. auf eine ruhige GPU), dann die Zeitmessung.
    monitor.start()
    started = time.perf_counter()
    # Unter nativem Linux-Docker laesst sich der Containerprozess zuordnen,
    # unter Docker Desktop nicht - ResourceMonitor misst dann ohne Ziel-PID.
    if target_pid:
        monitor.set_target_pid(target_pid)

    def report(note: str) -> None:
        if on_progress:
            with contextlib.suppress(Exception):
                on_progress(note, monitor.latest())

    rows: list[dict[str, Any]] = []
    fatal: str | None = None
    try:
        async with httpx.AsyncClient(headers=headers or {}) as client:
            rows = await runner(
                client, base_url, bench_cfg, backend_name, reps, details, errors, report
            )
    except Exception as exc:
        fatal = str(exc)
    finally:
        duration = time.perf_counter() - started
        telemetry = monitor.stop()

    write_json(out_dir / f"raw_{kind}.json", {
        "started_at": utc_now_iso(),
        "duration_seconds": duration,
        "backend": backend_name,
        "base_url": base_url,
        "api_style": API_STYLE_OPENAI_COMPLETIONS,
        "profile": profile,
        "kind": kind,
        "repetitions": reps,
        "rows": rows,
        "requests": details,
        "errors": errors,
        "telemetry": telemetry,
    })

    light = strip_samples(telemetry)
    if fatal:
        return {
            "kind": kind,
            "status": "failed",
            "error": f"HTTP-Benchmark abgebrochen: {fatal}",
            "duration_seconds": duration,
            "telemetry": light,
        }
    if not any(row.get("avg_ts") is not None for row in rows):
        return {
            "kind": kind,
            "status": "failed",
            "error": "Kein einziger Messwert konnte erhoben werden: " + ("; ".join(errors[:5]) or "unbekannt"),
            "error_detail": "\n".join(errors[:20]),
            "duration_seconds": duration,
            "telemetry": light,
        }

    result: dict[str, Any] = {
        "kind": kind,
        "status": "ok",
        "duration_seconds": duration,
        "rows": rows,
        "telemetry": light,
    }
    if errors:
        result["partial_errors"] = errors[:20]
    return result


def run_http_bench(
    base_url: str,
    headers: dict[str, str] | None,
    bench_cfg: dict[str, Any],
    profile: dict[str, Any],
    kind: str,
    out_dir: Path,
    on_progress: ProgressFn | None = None,
    *,
    backend_name: str = "vllm",
    target_pid: int | None = None,
) -> dict[str, Any]:
    """Misst eine Testart gegen einen bereits laufenden HTTP-Server.

    Der Server wird nicht hier gestartet: bei HTTP-Backends uebernimmt das
    ``begin_profile`` einmal pro Profil, statt dreimal einmal pro Testart.
    """
    coro = _run_http_bench_async(
        base_url, headers, bench_cfg, profile, kind, Path(out_dir),
        on_progress, backend_name, target_pid,
    )
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return loop.run_until_complete(coro)
