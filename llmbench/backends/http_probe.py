"""Generischer Kontext-/OOM-Probe ueber HTTP fuer vLLM, TGI und Ollama.

Der Probe sendet einen einzelnen, nicht gestreamten Request mit einem Fuelltext
von ungefaehr ``prompt_target`` Tokens an den laufenden Endpoint. Server-Start und
-Stopp pro Kontextstufe uebernimmt ``llmbench.stress.oom``; hier wird nur die
Antwort bewertet.

Fehler werden nicht als Freitext, sondern als ``failure_category`` klassifiziert,
damit "Server ist OOM gegangen" von "Kontext ueberschreitet das konfigurierte
Limit" und von "Timeout" unterscheidbar bleibt. Die Klassifikation arbeitet auf
HTTP-Status und Fehlertext des Servers und ist eine Heuristik; unbekannte
Antworten landen in ``server_error``/``client_error`` und nie als ``ok``.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from ..http_bench import API_STYLE_OLLAMA_NATIVE, API_STYLE_OPENAI_COMPLETIONS, build_filler_prompt
from ..utils import auth_headers

CATEGORY_OOM = "out_of_memory"
CATEGORY_CONTEXT = "context_exceeded"
CATEGORY_TRUNCATED = "context_truncated"
CATEGORY_TIMEOUT = "timeout"
CATEGORY_CONNECTION = "connection_error"
CATEGORY_MODEL = "model_not_found"
CATEGORY_SERVER = "server_error"
CATEGORY_CLIENT = "client_error"
CATEGORY_INVALID = "invalid_response"
# Set by the stress driver (llmbench.stress.oom), not by the HTTP probe itself.
CATEGORY_STARTUP_FAILED = "startup_failed"
CATEGORY_PROBE_ERROR = "probe_error"

_OOM_MARKERS = (
    "out of memory",
    "outofmemory",
    "cudamalloc",
    "cuda_error_out_of_memory",
    "cublas_status_alloc_failed",
    "failed to allocate",
    "unable to allocate",
    "not enough memory",
    "insufficient memory",
    "requires more system memory",
    "memory layout cannot be allocated",
)
# "oom" as a bare substring would hit "bloom"/"room"; match it as a word or as
# the kernel/runtime kill markers instead.
_OOM_RE = re.compile(r"\boom\b|oom[-_ ]?kill(?:ed|er)?", re.IGNORECASE)
_CONTEXT_MARKERS = (
    "maximum context length",
    "max_model_len",
    "max_total_tokens",
    "max_input_tokens",
    "max_input_length",
    "must have less than",
    "must be <=",
    "input validation error",
    "context length",
    "context window",
    "too long",
    "exceeds the",
)
_MODEL_MARKERS = ("model not found", "not found, try pulling", "does not exist", "no such model")

# Ollama kuerzt zu lange Prompts still auf num_ctx. Meldet Ollama eine
# Prompt-Laenge nahe num_ctx, ist unklar, ob gekuerzt wurde. Es gilt als
# Fehlschlag (``context_truncated``) nur, wenn dabei die Zielstufe nicht
# erreicht wurde (actual < target). Liegt actual >= target (der Tokenizer
# zaehlt mehr Tokens als die Fuelltext-Schaetzung, ggf. > 512 Abweichung), wurde
# die Stufe nachweislich verarbeitet: ok, aber mit ``truncated_at_num_ctx``.
_TRUNCATION_MARGIN_TOKENS = 4


def classify_failure(status: int | None, text: str = "", exc: BaseException | None = None) -> str:
    """Ordnet einen Fehlschlag einer stabilen Kategorie zu."""
    if exc is not None:
        if isinstance(exc, httpx.TimeoutException):
            return CATEGORY_TIMEOUT
        if isinstance(exc, (httpx.TransportError, ConnectionError)):
            # Ein abrupt beendeter Server (Container von der Runtime gekillt) ist
            # das typische Bild eines OOM-Kills, ohne dass ein Fehlertext existiert.
            return CATEGORY_CONNECTION
    lowered = (text or "").lower()
    model_hit = any(marker in lowered for marker in _MODEL_MARKERS)
    if status == 404 and model_hit:
        return CATEGORY_MODEL
    if any(marker in lowered for marker in _OOM_MARKERS) or _OOM_RE.search(lowered):
        return CATEGORY_OOM
    if model_hit:
        return CATEGORY_MODEL
    if any(marker in lowered for marker in _CONTEXT_MARKERS):
        return CATEGORY_CONTEXT
    if status is not None and status >= 500:
        return CATEGORY_SERVER
    if status is not None and status == 404:
        return CATEGORY_MODEL
    if status is not None and status >= 400:
        return CATEGORY_CLIENT
    return CATEGORY_INVALID


def _error_text(response: httpx.Response) -> str:
    raw = response.text.strip()
    try:
        parsed = json.loads(raw)
    except ValueError:
        return raw[:500]
    if isinstance(parsed, dict):
        err = parsed.get("error") or parsed.get("message") or raw
        if isinstance(err, dict):
            err = err.get("message") or json.dumps(err)
        return str(err)[:500]
    return raw[:500]


def _result(
    target: int,
    started: float,
    *,
    ok: bool,
    actual: int | None = None,
    status: int | None = None,
    category: str | None = None,
    error: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "ok": ok,
        "target_prompt_tokens": target,
        "actual_prompt_tokens": actual,
        "duration_seconds": time.perf_counter() - started,
    }
    if status is not None:
        doc["http_status"] = status
    doc.update(extra)
    if not ok:
        doc["failure_category"] = category or CATEGORY_INVALID
        doc["error"] = error or doc["failure_category"]
    return doc


async def _discover_openai_model(client: httpx.AsyncClient, base_url: str, fallback: str) -> str:
    """vLLM/TGI melden ihren Modellnamen unter /v1/models; sonst Konfigurationswert."""
    try:
        resp = await client.get(base_url + "/v1/models", timeout=15)
        resp.raise_for_status()
        data = resp.json().get("data") or []
        if data and isinstance(data[0], dict) and data[0].get("id"):
            return str(data[0]["id"])
    except Exception:  # noqa: BLE001 - Discovery ist Best-Effort, der Request prueft alles
        pass
    return fallback


async def probe_context_http(
    base_url: str,
    prompt_target: int,
    endpoint_cfg: dict[str, Any],
    *,
    api_style: str,
) -> dict[str, Any]:
    """Ein Kontext-Probe-Request gegen einen OpenAI- oder Ollama-Endpoint."""
    if api_style not in (API_STYLE_OPENAI_COMPLETIONS, API_STYLE_OLLAMA_NATIVE):
        raise ValueError(f"Kein HTTP-Kontextprobe fuer API-Stil {api_style!r}.")

    base = base_url.rstrip("/")
    timeout = float(endpoint_cfg.get("timeout_seconds", 600))
    prompt = build_filler_prompt(prompt_target, nonce=f"[oom-probe-{prompt_target}]")
    prompt += "\nSummarize the preceding text in one short sentence."
    started = time.perf_counter()
    num_ctx: int | None = None

    try:
        async with httpx.AsyncClient(headers=auth_headers(endpoint_cfg)) as client:
            if api_style == API_STYLE_OPENAI_COMPLETIONS:
                model = await _discover_openai_model(client, base, str(endpoint_cfg.get("model", "llmbench")))
                path = "/v1/completions"
                payload: dict[str, Any] = {
                    "model": model,
                    "prompt": prompt,
                    "max_tokens": 16,
                    "temperature": 0.0,
                    "stream": False,
                }
            else:
                # Der Probe zwingt Ollama, genau den Kontext der Stufe zu
                # allozieren; das Laden mit grossem num_ctx ist der OOM-Moment.
                num_ctx = int(endpoint_cfg.get("context_size") or prompt_target + 512)
                path = "/api/generate"
                options: dict[str, Any] = {"temperature": 0.0, "num_predict": 16, "num_ctx": num_ctx}
                if endpoint_cfg.get("ollama_num_gpu") is not None:
                    options["num_gpu"] = int(endpoint_cfg["ollama_num_gpu"])
                payload = {
                    "model": str(endpoint_cfg.get("model", "llmbench")),
                    "prompt": prompt,
                    "stream": False,
                    "raw": True,
                    "options": options,
                }

            response = await client.post(base + path, json=payload, timeout=timeout)
            if response.status_code >= 400:
                text = _error_text(response)
                return _result(
                    prompt_target, started, ok=False, status=response.status_code,
                    category=classify_failure(response.status_code, text),
                    error=f"HTTP {response.status_code}: {text}",
                )
            try:
                data = response.json()
            except ValueError as exc:
                return _result(
                    prompt_target, started, ok=False, status=response.status_code,
                    category=CATEGORY_INVALID, error=f"Antwort ist kein JSON: {exc}",
                )
    except httpx.HTTPError as exc:
        return _result(
            prompt_target, started, ok=False,
            category=classify_failure(None, str(exc), exc),
            error=f"{type(exc).__name__}: {exc}".rstrip(": "),
        )

    if not isinstance(data, dict):
        return _result(prompt_target, started, ok=False, status=response.status_code,
                       category=CATEGORY_INVALID, error="Antwort ist kein JSON-Objekt.")
    # Ollama meldet Fehler teils mit 200 und {"error": ...} im Body.
    if data.get("error"):
        err = data["error"]
        text = str(err.get("message", err) if isinstance(err, dict) else err)
        return _result(prompt_target, started, ok=False, status=response.status_code,
                       category=classify_failure(response.status_code, text), error=text[:500])

    if api_style == API_STYLE_OPENAI_COMPLETIONS:
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        actual = usage.get("prompt_tokens")
    else:
        actual = data.get("prompt_eval_count")
    actual = int(actual) if isinstance(actual, (int, float)) else None

    extra: dict[str, Any] = {}
    if actual is None:
        # Der Server meldet keine Token-Zahl: bestanden, aber nicht gemessen.
        extra["actual_unverified"] = True
    if (
        api_style == API_STYLE_OLLAMA_NATIVE
        and actual is not None
        and num_ctx is not None
        and actual >= num_ctx - _TRUNCATION_MARGIN_TOKENS
    ):
        if actual < prompt_target:
            return _result(
                prompt_target, started, ok=False, actual=actual, status=response.status_code,
                category=CATEGORY_TRUNCATED,
                error=f"Prompt fuellt num_ctx={num_ctx} vollstaendig aus ({actual} Tokens); "
                      "Ollama kuerzt vermutlich still.",
            )
        extra["truncated_at_num_ctx"] = True
    return _result(prompt_target, started, ok=True, actual=actual, status=response.status_code, **extra)
