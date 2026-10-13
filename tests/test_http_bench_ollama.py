"""Tests der Ollama-native API-Unterstuetzung in http_bench."""

import json
from pathlib import Path

import httpx
import pytest

from llmbench.http_bench import (
    API_STYLE_OLLAMA_NATIVE,
    _build_request,
    _extract_delta,
    one_completion_async,
    run_http_bench,
)


def _ollama_chunks(response_text: str, n_tokens: int) -> str:
    """Ollama liefert pro Chunk ein JSON-Objekt in einer SSE-Zeile."""
    lines = []
    for _i in range(n_tokens):
        lines.append("data: " + json.dumps({"response": response_text, "done": False}))
    lines.append("data: " + json.dumps({
        "done": True,
        "total_duration": 1_000_000_000,
        "load_duration": 100_000_000,
        "prompt_eval_count": 8,
        "eval_count": n_tokens,
        "prompt_eval_duration": 50_000_000,
        "eval_duration": 900_000_000,
    }))
    lines.append("data: [DONE]")
    return "\n".join(lines) + "\n"


def _ollama_handler(requests: list[dict] | None = None):
    def _handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        if requests is not None:
            requests.append({"url": str(request.url), "payload": payload})

        n = int(payload.get("options", {}).get("num_predict", 1))
        return httpx.Response(200, text=_ollama_chunks("x", n))

    return _handler


@pytest.fixture
def mock_server(monkeypatch):
    seen: list[dict] = []
    transport = httpx.MockTransport(_ollama_handler(seen))

    class _PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("llmbench.http_bench.httpx.AsyncClient", _PatchedAsyncClient)
    monkeypatch.setattr("llmbench.http_bench.ResourceMonitor.start", lambda _self: None)
    monkeypatch.setattr("llmbench.http_bench.ResourceMonitor.stop", lambda _self: {"sample_count": 0})
    monkeypatch.setattr("llmbench.http_bench.ResourceMonitor.latest", lambda _self: None)
    return seen


def test_ollama_build_request_shape():
    cfg = {
        "max_tokens": 16,
        "temperature": 0.5,
        "top_p": 0.9,
        "top_k": 40,
        "repeat_penalty": 1.1,
        "seed": 123,
        "model": "llmbench-model",
    }
    path, payload = _build_request(API_STYLE_OLLAMA_NATIVE, "prompt text", cfg, 0)
    assert path == "/api/generate"
    assert payload["model"] == "llmbench-model"
    assert payload["prompt"] == "prompt text"
    assert payload["stream"] is True
    options = payload["options"]
    assert options["num_predict"] == 16
    assert options["temperature"] == 0.5
    assert options["top_p"] == 0.9
    assert options["top_k"] == 40
    assert options["repeat_penalty"] == 1.1
    assert options["seed"] == 123
    # Ollama kennt diese Felder nicht.
    assert "min_tokens" not in payload
    assert "ignore_eos" not in payload


def test_ollama_build_request_defaults_model():
    path, payload = _build_request(API_STYLE_OLLAMA_NATIVE, "p", {"max_tokens": 1}, 0)
    assert payload["model"] == "llmbench"


def test_ollama_extract_delta_counts_response_chunks():
    assert _extract_delta(API_STYLE_OLLAMA_NATIVE, {"response": "x"}) == (1, "x")
    assert _extract_delta(API_STYLE_OLLAMA_NATIVE, {"response": ""}) == (0, "")


def test_ollama_extract_delta_uses_eval_count_on_done():
    assert _extract_delta(API_STYLE_OLLAMA_NATIVE, {"done": True, "eval_count": 42}) == (42, "")
    assert _extract_delta(API_STYLE_OLLAMA_NATIVE, {"done": True}) == (0, "")


def test_ollama_one_completion_counts_final_tokens(mock_server):
    import asyncio

    async def _go():
        async with httpx.AsyncClient() as client:
            return await one_completion_async(
                client, "http://testserver", "hallo",
                {"max_tokens": 8, "model": "m", "seed": 7},
                0, api_style=API_STYLE_OLLAMA_NATIVE,
            )

    res = asyncio.run(_go())
    assert res["ok"] is True
    assert res["output_tokens"] == 8
    assert res["prompt_tokens"] == 8

    sent = mock_server[-1]
    assert sent["url"].endswith("/api/generate")
    assert sent["payload"]["stream"] is True
    assert sent["payload"]["options"]["num_predict"] == 8
    assert sent["payload"]["options"]["seed"] == 7


@pytest.mark.usefixtures("mock_server")
def test_ollama_run_http_bench_generation_kind(tmp_path: Path):
    cfg = {
        "repetitions": 1,
        "prompt_tokens": [512],
        "generation_tokens": [128],
        "context_depths": [0],
        "long_context_prompt_tokens": 512,
        "long_context_generation_tokens": 128,
        "resource_sample_interval": 0.5,
        "timeout_seconds": 60,
        "seed": 42,
        "model": "m",
    }
    result = run_http_bench(
        "http://testserver", {}, cfg, {"name": "Ollama"}, "generation", tmp_path,
        backend_name="ollama", api_style=API_STYLE_OLLAMA_NATIVE,
    )
    assert result["status"] == "ok"
    assert result["rows"][0]["test"] == "tg128"
    assert result["rows"][0]["backend"] == "ollama"

    raw = json.loads((tmp_path / "raw_generation.json").read_text(encoding="utf-8"))
    assert raw["api_style"] == API_STYLE_OLLAMA_NATIVE
