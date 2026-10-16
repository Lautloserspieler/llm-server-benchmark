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

# Unterstuetzte API-Dialekte.
API_STYLE_LLAMA_CPP = "llama_cpp"
API_STYLE_LLAMA_CPP_CHAT = "llama_cpp_chat"
API_STYLE_OPENAI_COMPLETIONS = "openai_completions"
API_STYLE_OLLAMA_NATIVE = "ollama_native"
API_STYLES = (API_STYLE_LLAMA_CPP, API_STYLE_LLAMA_CPP_CHAT, API_STYLE_OPENAI_COMPLETIONS, API_STYLE_OLLAMA_NATIVE)

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

    if api_style == API_STYLE_OLLAMA_NATIVE:
        # Ollama native API: POST /api/generate mit Streaming-JSON-Objekten.
        options: dict[str, Any] = {
            "temperature": temperature,
            "num_predict": max_tokens,
        }
        if cfg.get("ollama_num_ctx") is not None:
            options["num_ctx"] = int(cfg["ollama_num_ctx"])
        if cfg.get("ollama_num_gpu") is not None:
            options["num_gpu"] = int(cfg["ollama_num_gpu"])
        if "top_p" in cfg:
            options["top_p"] = float(cfg["top_p"])
        if "top_k" in cfg:
            options["top_k"] = int(cfg["top_k"])
        if "repeat_penalty" in cfg:
            options["repeat_penalty"] = float(cfg["repeat_penalty"])
        if cfg.get("seed") is not None:
            options["seed"] = int(cfg["seed"])
        # "min_tokens" und "ignore_eos" gibt es in Ollama nicht; num_predict
        # begrenzt die Ausgabe und fuellt damit dieselbe Rolle wie max_tokens.
        return "/api/generate", {
            "model": str(cfg.get("model", "llmbench")),
            "prompt": str(prompt_or_messages),
            "stream": True,
            # Benchmark-Prompts sollen nicht durch ein modellabhängiges
            # Ollama-Template verändert werden.
            "raw": True,
            "options": options,
        }

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

    if api_style == API_STYLE_OLLAMA_NATIVE:
        # Ollama liefert pro Stream-Chunk ein "response"-Feld; der letzte Chunk
        # mit "done": true enthaelt stattdessen die finalen Zaehler.
        if data.get("done"):
            eval_count = data.get("eval_count")
            if eval_count is not None:
                try:
                    return int(eval_count), ""
                except Exception:
                    pass
            return 0, ""
        content = data.get("response") or ""
        return (1 if content else 0), content

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


def _ollama_timings(data: dict[str, Any]) -> dict[str, Any]:
    """Serverseitige Zeiten (ns) des letzten Ollama-Chunks im Format der llama.cpp-timings."""
    def _ms(key: str) -> float | None:
        value = data.get(key)
        return float(value) / 1e6 if isinstance(value, (int, float)) else None

    timings: dict[str, Any] = {}
    for src, dst in (("prompt_eval_count", "prompt_n"), ("eval_count", "predicted_n")):
        if data.get(src) is not None:
            timings[dst] = data[src]
    for src, dst in (
        ("prompt_eval_duration", "prompt_ms"),
        ("eval_duration", "predicted_ms"),
        ("load_duration", "load_ms"),
    ):
        value = _ms(src)
        if value is not None:
            timings[dst] = value
    return timings


def _server_rate(timings: dict[str, Any], n_key: str, ms_key: str) -> float | None:
    """Tokens/s aus serverseitig gemessenen Zaehlern und Zeiten (None, wenn unvollstaendig)."""
    try:
        n = float(timings[n_key])
        ms = float(timings[ms_key])
    except (KeyError, TypeError, ValueError):
        return None
    return n / (ms / 1000.0) if n > 0 and ms > 0 else None


async def _raise_for_status(resp: httpx.Response) -> None:
    """Wie raise_for_status(), nimmt aber den Fehlertext des Servers mit auf.

    Ollama antwortet z. B. mit 404 und {"error": "model 'x' not found"}; ohne den
    Body ist die Ursache nicht von einem falschen Pfad zu unterscheiden.
    """
    if resp.status_code < 400:
        return
    detail = ""
    with contextlib.suppress(Exception):
        raw = (await resp.aread()).decode("utf-8", errors="replace").strip()
        try:
            parsed = json.loads(raw)
            detail = str(parsed.get("error") or parsed.get("message") or raw) if isinstance(parsed, dict) else raw
        except json.JSONDecodeError:
            detail = raw
    reason = resp.reason_phrase or ""
    message = f"HTTP {resp.status_code} {reason} fuer {resp.request.url}".replace("  ", " ")
    raise RuntimeError(f"{message}: {detail[:500]}" if detail else message)


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
            await _raise_for_status(resp)
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
    if not timings and api_style == API_STYLE_OLLAMA_NATIVE and final_data.get("done"):
        timings = _ollama_timings(final_data)
    if not usage:
        usage = final_data.get("usage") or {}

    exact_total = (
        timings.get("predicted_n")
        or timings.get("tokens_predicted")
        or usage.get("completion_tokens")
        or final_data.get("eval_count")
    )
    if exact_total is not None:
        with contextlib.suppress(Exception):
            token_count = int(exact_total)

    prompt_tokens: int | None = None
    raw_prompt_tokens = (
        timings.get("prompt_n")
        or usage.get("prompt_tokens")
        or final_data.get("prompt_eval_count")
    )
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



async def sanity_completion_async(
    client: httpx.AsyncClient,
    base_url: str,
    prompt: str,
    cfg: dict[str, Any],
    *,
    api_style: str,
) -> str:
    """Run one non-persisted completion and return only its generated text.

    This shares the exact request dialect/parser used by the endpoint benchmark
    without adding generated content to benchmark result artifacts.
    """
    if api_style not in API_STYLES:
        raise ValueError(
            f"Unbekannter API-Stil: {api_style!r}. Erlaubt: {', '.join(API_STYLES)}"
        )

    path, payload = _build_request(api_style, prompt, cfg, 0)
    timeout = float(cfg.get("timeout_seconds", 30))
    parts: list[str] = []

    async with client.stream(
        "POST", base_url.rstrip("/") + path, json=payload, timeout=timeout
    ) as response:
        await _raise_for_status(response)
        async for line in response.aiter_lines():
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
            _tokens, content = _extract_delta(api_style, data)
            if content:
                parts.append(content)

    return "".join(parts).strip()


# ------------------------------------------------------------- Messschleifen


def _row(
    test: str,
    samples: list[float],
    *,
    n_prompt: int,
    n_gen: int,
    n_depth: int,
    backend_name: str,
    workload_tokens: int | None = None,
    extra: dict[str, Any] | None = None,
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
        "workload_tokens": workload_tokens,
        **(extra or {}),
    }


def _completion_cfg(base: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "temperature": 0.0,
        "seed": base.get("seed", 42),
        "timeout_seconds": float(base.get("timeout_seconds", 3600)),
    }
    # Backend-spezifische Felder muessen in jede Request-Payload gelangen: ohne
    # "model" faellt _build_request auf "llmbench" zurueck (Ollama: 404).
    for key in ("model", "ollama_num_ctx", "ollama_num_gpu"):
        if base.get(key) is not None:
            cfg[key] = base[key]
    cfg.update(overrides)
    return cfg


async def _measure(
    client: httpx.AsyncClient,
    base_url: str,
    prompt: str,
    cfg: dict[str, Any],
    request_id: int,
    api_style: str = API_STYLE_OPENAI_COMPLETIONS,
) -> dict[str, Any]:
    return await one_completion_async(
        client, base_url, prompt, cfg, request_id, api_style=api_style
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
    api_style: str = API_STYLE_OPENAI_COMPLETIONS,
) -> list[dict[str, Any]]:
    """Prompt-Verarbeitung: TTFT bei max_tokens=1 ist reine Prefill-Zeit."""
    rows: list[dict[str, Any]] = []
    request_id = 0
    for n in bench_cfg["prompt_tokens"]:
        samples: list[float] = []
        workload_tokens = 0
        used_server = 0
        for rep in range(reps):
            prompt = build_filler_prompt(int(n), _nonce(f"pp{n}", rep))
            cfg = _completion_cfg(bench_cfg, max_tokens=1)
            report(f"pp{n} · Wiederholung {rep + 1}/{reps}")
            res = await _measure(client, base_url, prompt, cfg, request_id, api_style=api_style)
            request_id += 1
            details.append({"test": f"pp{n}", "repetition": rep, **_detail(res)})
            if not res["ok"]:
                errors.append(f"pp{n}: {res['error']}")
                continue
            ttft = res["ttft_seconds"] or res["duration_seconds"]
            tokens = res["prompt_tokens"] or int(n)
            # Ollama meldet die Prefill-Zeit selbst (ohne HTTP-/Tokenisierungs-Overhead
            # und ohne Modellladezeit); bei kurzen Prompts ist das deutlich stabiler als
            # die Wanduhr-TTFT.
            server_rate = (
                _server_rate(res["server_timings"], "prompt_n", "prompt_ms")
                if api_style == API_STYLE_OLLAMA_NATIVE else None
            )
            if server_rate is not None:
                samples.append(server_rate)
                workload_tokens += int(tokens)
                used_server += 1
            elif ttft and ttft > 0:
                samples.append(tokens / ttft)
                workload_tokens += int(tokens)
        rows.append(_row(
            f"pp{n}", samples, n_prompt=int(n), n_gen=0, n_depth=0,
            backend_name=backend_name, workload_tokens=workload_tokens,
            extra={"timing_source": "server" if used_server == len(samples) and samples else "wallclock"},
        ))
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
    api_style: str = API_STYLE_OPENAI_COMPLETIONS,
) -> list[dict[str, Any]]:
    """Textgenerierung: Tokens nach dem ersten, geteilt durch die Zeit danach."""
    rows: list[dict[str, Any]] = []
    request_id = 0
    for n in bench_cfg["generation_tokens"]:
        samples: list[float] = []
        workload_tokens = 0
        used_server = 0
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
            res = await _measure(client, base_url, prompt, cfg, request_id, api_style=api_style)
            request_id += 1
            details.append({"test": f"tg{n}", "repetition": rep, **_detail(res)})
            if not res["ok"]:
                errors.append(f"tg{n}: {res['error']}")
                continue
            produced = res["output_tokens"] or int(n)
            if api_style == API_STYLE_OLLAMA_NATIVE and res["output_tokens"] and res["output_tokens"] < int(n):
                # Ollama kennt weder ignore_eos noch min_tokens; endet das Modell frueh,
                # basiert die Rate auf weniger Tokens als angefordert.
                errors.append(
                    f"tg{n}: Modell endete nach {res['output_tokens']} von {n} Tokens (EOS); "
                    "Messwert beruht auf kuerzerer Ausgabe"
                )
            ttft = res["ttft_seconds"] or 0.0
            gen_seconds = res["duration_seconds"] - ttft
            server_rate = (
                _server_rate(res["server_timings"], "predicted_n", "predicted_ms")
                if api_style == API_STYLE_OLLAMA_NATIVE else None
            )
            if server_rate is not None:
                samples.append(server_rate)
                workload_tokens += int(produced)
                used_server += 1
            elif gen_seconds > 0 and produced:
                samples.append(produced / gen_seconds)
                workload_tokens += int(produced)
        rows.append(_row(
            f"tg{n}", samples, n_prompt=0, n_gen=int(n), n_depth=0,
            backend_name=backend_name, workload_tokens=workload_tokens,
            extra={"timing_source": "server" if used_server == len(samples) and samples else "wallclock"},
        ))
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
    api_style: str = API_STYLE_OPENAI_COMPLETIONS,
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
        prefill_samples: list[float] = []
        decode_samples: list[float] = []
        num_ctx = bench_cfg.get("ollama_num_ctx") if api_style == API_STYLE_OLLAMA_NATIVE else None
        if num_ctx is not None and depth + prompt_tokens + gen_tokens > int(num_ctx):
            # Ollama kuerzt zu lange Prompts still auf num_ctx; der Messwert truege
            # dann das falsche Tiefenlabel.
            errors.append(
                f"{name}: uebersprungen - {depth + prompt_tokens + gen_tokens} Tokens "
                f"ueberschreiten ollama_num_ctx={int(num_ctx)}"
            )
            rows.append(_row(name, samples, n_prompt=prompt_tokens, n_gen=gen_tokens,
                             n_depth=depth, backend_name=backend_name))
            continue
        for rep in range(reps):
            prompt = build_filler_prompt(depth + prompt_tokens, _nonce(name, rep))
            cfg = _completion_cfg(
                bench_cfg, max_tokens=gen_tokens, min_tokens=gen_tokens, ignore_eos=True
            )
            report(f"{name} · Wiederholung {rep + 1}/{reps}")
            res = await _measure(client, base_url, prompt, cfg, request_id, api_style=api_style)
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
            # Prefill und Decode getrennt ausweisen, soweit der Server Zeiten meldet;
            # der kombinierte Wert allein steigt mit der Tiefe, ohne dass etwas schneller wird.
            timings = res["server_timings"] or {}
            for n_key, ms_key, bucket in (
                ("prompt_n", "prompt_ms", prefill_samples),
                ("predicted_n", "predicted_ms", decode_samples),
            ):
                rate = _server_rate(timings, n_key, ms_key)
                if rate is not None:
                    bucket.append(rate)
        rows.append(_row(
            name, samples, n_prompt=prompt_tokens, n_gen=gen_tokens,
            n_depth=depth, backend_name=backend_name,
            extra={
                "prefill_ts": statistics.fmean(prefill_samples) if prefill_samples else None,
                "decode_ts": statistics.fmean(decode_samples) if decode_samples else None,
            },
        ))
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
    api_style: str = API_STYLE_OPENAI_COMPLETIONS,
) -> dict[str, Any]:
    runner = _KIND_RUNNERS.get(kind)
    if runner is None:
        raise ValueError(f"Unbekannte Testart: {kind}")

    reps = max(1, int(bench_cfg.get("repetitions", 1)))
    details: list[dict[str, Any]] = []
    errors: list[str] = []

    monitor = ResourceMonitor(
        float(bench_cfg.get("resource_sample_interval", 0.5)),
        ignored_process_names=tuple(bench_cfg.get("ignore_gpu_processes") or ()),
    )
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
            if api_style == API_STYLE_OLLAMA_NATIVE:
                # Ollama laedt das Modell erst beim ersten Request. Ohne Vorlauf
                # steckt die Ladezeit im ersten Messwert (und im Fehlerfall zeigt
                # sich ein fehlendes Modell sofort mit klarer Meldung).
                warm_cfg = _completion_cfg(bench_cfg, max_tokens=1)
                warm = await _measure(
                    client, base_url, _SHORT_PROMPT, warm_cfg, -1, api_style=api_style
                )
                if not warm["ok"]:
                    raise RuntimeError(f"Ollama-Warmup fehlgeschlagen: {warm['error']}")
            rows = await runner(
                client, base_url, bench_cfg, backend_name, reps, details, errors, report,
                api_style=api_style,
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
        "api_style": api_style,
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
    api_style: str = API_STYLE_OPENAI_COMPLETIONS,
) -> dict[str, Any]:
    """Misst eine Testart gegen einen bereits laufenden HTTP-Server.

    Der Server wird nicht hier gestartet: bei HTTP-Backends uebernimmt das
    ``begin_profile`` einmal pro Profil, statt dreimal einmal pro Testart.
    """
    coro = _run_http_bench_async(
        base_url, headers, bench_cfg, profile, kind, Path(out_dir),
        on_progress, backend_name, target_pid, api_style=api_style,
    )
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return loop.run_until_complete(coro)
