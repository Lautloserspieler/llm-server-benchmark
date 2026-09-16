"""Tests der HTTP-Bench-Engine gegen einen gemockten OpenAI-kompatiblen Server."""

import json
import math
from pathlib import Path

import httpx
import pytest

from llmbench.http_bench import (
    API_STYLE_OPENAI_COMPLETIONS,
    CHARS_PER_TOKEN,
    build_filler_prompt,
    one_completion_async,
    run_http_bench,
)
from llmbench.llama_bench import _derive_test_name, flatten_bench_rows


def _bench_cfg(**overrides):
    cfg = {
        "repetitions": 3,
        "prompt_tokens": [512, 4096],
        "generation_tokens": [128, 512],
        "context_depths": [0, 8192],
        "long_context_prompt_tokens": 512,
        "long_context_generation_tokens": 128,
        "resource_sample_interval": 0.5,
        "timeout_seconds": 60,
        "seed": 42,
    }
    cfg.update(overrides)
    return cfg


def _sse(chunks: list[dict]) -> str:
    lines = ["data: " + json.dumps(c) for c in chunks]
    lines.append("data: [DONE]")
    return "\n".join(lines) + "\n"


def _completions_handler(requests: list[dict] | None = None):
    """Antwortet wie vLLM: Text-Deltas, am Ende ein Chunk mit exaktem usage."""

    def _handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        if requests is not None:
            requests.append({"url": str(request.url), "payload": payload})

        max_tokens = int(payload.get("max_tokens", 1))
        # Der Server zaehlt selbst - bewusst ein anderer Wert als die
        # Zeichen-Schaetzung, damit sichtbar wird, dass usage benutzt wird.
        prompt_tokens = max(1, len(payload.get("prompt", "")) // 4)

        chunks = [{"choices": [{"text": "x", "index": 0}], "usage": None} for _ in range(max_tokens)]
        chunks.append({
            "choices": [],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": max_tokens,
                "total_tokens": prompt_tokens + max_tokens,
            },
        })
        return httpx.Response(200, text=_sse(chunks))

    return _handler


@pytest.fixture
def mock_server(monkeypatch):
    """Verdrahtet MockTransport und legt den ResourceMonitor still."""
    seen: list[dict] = []
    transport = httpx.MockTransport(_completions_handler(seen))

    class _PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("llmbench.http_bench.httpx.AsyncClient", _PatchedAsyncClient)
    monkeypatch.setattr("llmbench.http_bench.ResourceMonitor.start", lambda _self: None)
    monkeypatch.setattr("llmbench.http_bench.ResourceMonitor.stop", lambda _self: {"sample_count": 0})
    monkeypatch.setattr("llmbench.http_bench.ResourceMonitor.latest", lambda _self: None)
    return seen


# ------------------------------------------------------------- Fuelltexte


def test_build_filler_prompt_hits_character_budget():
    prompt = build_filler_prompt(512)
    assert len(prompt) == int(round(512 * CHARS_PER_TOKEN))


def test_build_filler_prompt_scales_with_target():
    assert len(build_filler_prompt(4096)) > len(build_filler_prompt(512))


def test_build_filler_prompt_is_unique_per_nonce():
    """Identische Prompts wuerden vLLMs Prefix-Cache treffen und die Messung entwerten."""
    a = build_filler_prompt(128, "[pp128#0-aaaa]")
    b = build_filler_prompt(128, "[pp128#1-bbbb]")
    assert a != b
    assert a.startswith("[pp128#0-aaaa]")


def test_build_filler_prompt_handles_zero_tokens():
    assert build_filler_prompt(0) == "."


# ----------------------------------------------------- one_completion_async


def test_openai_payload_shape(mock_server):
    """Der Request muss /v1/completions mit exakten Tokenzahlen anfordern."""
    import asyncio

    async def _go():
        async with httpx.AsyncClient() as client:
            return await one_completion_async(
                client, "http://testserver", "hallo",
                {"max_tokens": 8, "min_tokens": 8, "ignore_eos": True, "seed": 7},
                0, api_style=API_STYLE_OPENAI_COMPLETIONS,
            )

    res = asyncio.run(_go())
    assert res["ok"] is True
    assert res["output_tokens"] == 8
    assert res["prompt_tokens"] == 1

    sent = mock_server[-1]
    assert sent["url"].endswith("/v1/completions")
    assert sent["payload"]["stream"] is True
    # Ohne include_usage liefert der letzte Chunk keine exakten Tokenzahlen.
    assert sent["payload"]["stream_options"] == {"include_usage": True}
    assert sent["payload"]["max_tokens"] == 8
    assert sent["payload"]["min_tokens"] == 8
    assert sent["payload"]["ignore_eos"] is True
    assert sent["payload"]["seed"] == 7
    # Kein Chat-Template: roher Prompt statt messages.
    assert "messages" not in sent["payload"]


def test_unknown_api_style_is_rejected():
    import asyncio

    async def _go():
        async with httpx.AsyncClient() as client:
            await one_completion_async(client, "http://x", "p", {"max_tokens": 1}, 0, api_style="nope")

    with pytest.raises(ValueError, match="Unbekannter API-Stil"):
        asyncio.run(_go())


# ---------------------------------------------------------------- kind: prompt


@pytest.mark.usefixtures("mock_server")
def test_prompt_kind_produces_pp_rows(tmp_path: Path):
    result = run_http_bench(
        "http://testserver", {}, _bench_cfg(), {"name": "vLLM"}, "prompt", tmp_path
    )
    assert result["status"] == "ok"
    rows = result["rows"]
    assert [r["test"] for r in rows] == ["pp512", "pp4096"]
    for row in rows:
        assert row["n_gen"] == 0
        assert row["n_depth"] == 0
        assert row["backend"] == "vllm"
        assert row["avg_ts"] > 0
    assert rows[0]["n_prompt"] == 512
    assert rows[1]["n_prompt"] == 4096


def test_prompt_kind_requests_single_token(mock_server, tmp_path: Path):
    """pp misst die Prefill-Zeit; mehr als ein Token wuerde tg mitmessen."""
    run_http_bench("http://testserver", {}, _bench_cfg(repetitions=1, prompt_tokens=[512]),
                   {}, "prompt", tmp_path)
    assert all(r["payload"]["max_tokens"] == 1 for r in mock_server)


def test_prompt_kind_honours_repetitions(mock_server, tmp_path: Path):
    cfg = _bench_cfg(repetitions=4, prompt_tokens=[512])
    result = run_http_bench("http://testserver", {}, cfg, {}, "prompt", tmp_path)
    assert len(mock_server) == 4
    assert result["rows"][0]["repetitions"] == 4


# ------------------------------------------------------------ kind: generation


@pytest.mark.usefixtures("mock_server")
def test_generation_kind_produces_tg_rows(tmp_path: Path):
    result = run_http_bench(
        "http://testserver", {}, _bench_cfg(), {"name": "vLLM"}, "generation", tmp_path
    )
    assert result["status"] == "ok"
    rows = result["rows"]
    assert [r["test"] for r in rows] == ["tg128", "tg512"]
    for row in rows:
        assert row["n_prompt"] == 0
        assert row["avg_ts"] > 0
    assert rows[0]["n_gen"] == 128
    assert rows[1]["n_gen"] == 512


def test_generation_kind_forces_exact_token_count(mock_server, tmp_path: Path):
    """Ohne erzwungene Laenge sind die Tokenzahlen zwischen Laeufen unvergleichbar."""
    run_http_bench("http://testserver", {}, _bench_cfg(repetitions=1, generation_tokens=[128]),
                   {}, "generation", tmp_path)
    payload = mock_server[-1]["payload"]
    assert payload["max_tokens"] == 128
    assert payload["min_tokens"] == 128
    assert payload["ignore_eos"] is True


# --------------------------------------------------------- kind: long_context


@pytest.mark.usefixtures("mock_server")
def test_long_context_row_names_match_llama_bench_convention(tmp_path: Path):
    result = run_http_bench(
        "http://testserver", {}, _bench_cfg(), {"name": "vLLM"}, "long_context", tmp_path
    )
    assert result["status"] == "ok"
    rows = result["rows"]
    assert [r["test"] for r in rows] == ["pg512+128", "pg512+128@d8192"]
    # Die Namen muessen exakt der llama-bench-Ableitung entsprechen, sonst
    # stehen im Vergleichsbericht zwei Namen fuer denselben Test nebeneinander.
    for row in rows:
        assert row["test"] == _derive_test_name(row)


def test_long_context_prompt_grows_with_depth(mock_server, tmp_path: Path):
    cfg = _bench_cfg(repetitions=1, context_depths=[0, 8192])
    run_http_bench("http://testserver", {}, cfg, {}, "long_context", tmp_path)
    shallow = len(mock_server[0]["payload"]["prompt"])
    deep = len(mock_server[1]["payload"]["prompt"])
    assert deep > shallow
    assert math.isclose(deep - shallow, 8192 * CHARS_PER_TOKEN, rel_tol=0.01)


@pytest.mark.usefixtures("mock_server")
def test_long_context_sets_depth_field(tmp_path: Path):
    result = run_http_bench("http://testserver", {}, _bench_cfg(), {}, "long_context", tmp_path)
    assert [r["n_depth"] for r in result["rows"]] == [0, 8192]


# ------------------------------------------------------------ Statistik/Format


@pytest.mark.usefixtures("mock_server")
def test_stddev_is_zero_for_single_repetition(tmp_path: Path):
    cfg = _bench_cfg(repetitions=1, prompt_tokens=[512])
    result = run_http_bench("http://testserver", {}, cfg, {}, "prompt", tmp_path)
    assert result["rows"][0]["stddev_ts"] == 0.0


@pytest.mark.usefixtures("mock_server")
def test_stddev_is_non_negative_across_repetitions(tmp_path: Path):
    cfg = _bench_cfg(repetitions=5, prompt_tokens=[512])
    result = run_http_bench("http://testserver", {}, cfg, {}, "prompt", tmp_path)
    row = result["rows"][0]
    assert row["stddev_ts"] >= 0.0
    assert row["avg_ts"] > 0
    assert len(row["samples_ts"]) == 5


@pytest.mark.usefixtures("mock_server")
def test_rows_survive_flatten_bench_rows(tmp_path: Path):
    """Berichte und CSV muessen ohne Anpassung mit den Zeilen umgehen koennen."""
    result = run_http_bench("http://testserver", {}, _bench_cfg(), {}, "prompt", tmp_path)
    flat = flatten_bench_rows(result)
    assert [r["test"] for r in flat] == ["pp512", "pp4096"]
    assert all(r["backend"] == "vllm" for r in flat)
    # llama.cpp-spezifische Felder bleiben leer statt geraten zu werden.
    assert all(r["n_gpu_layers"] is None and r["build_commit"] is None for r in flat)


@pytest.mark.usefixtures("mock_server")
def test_raw_json_is_written_per_kind(tmp_path: Path):
    run_http_bench("http://testserver", {}, _bench_cfg(), {}, "generation", tmp_path)
    raw_path = tmp_path / "raw_generation.json"
    assert raw_path.exists()
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    assert raw["kind"] == "generation"
    assert raw["backend"] == "vllm"
    assert raw["api_style"] == API_STYLE_OPENAI_COMPLETIONS
    assert len(raw["requests"]) == 6  # 2 Groessen x 3 Wiederholungen


@pytest.mark.usefixtures("mock_server")
def test_unknown_kind_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="Unbekannte Testart"):
        run_http_bench("http://testserver", {}, _bench_cfg(), {}, "nonsense", tmp_path)


# ----------------------------------------------------------------- Fehlerfall


def test_server_errors_yield_failed_status(monkeypatch, tmp_path: Path):
    transport = httpx.MockTransport(lambda _r: httpx.Response(500, text="boom"))

    class _PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("llmbench.http_bench.httpx.AsyncClient", _PatchedAsyncClient)
    monkeypatch.setattr("llmbench.http_bench.ResourceMonitor.start", lambda _self: None)
    monkeypatch.setattr("llmbench.http_bench.ResourceMonitor.stop", lambda _self: {"sample_count": 0})
    monkeypatch.setattr("llmbench.http_bench.ResourceMonitor.latest", lambda _self: None)

    result = run_http_bench(
        "http://testserver", {}, _bench_cfg(repetitions=1, prompt_tokens=[512]), {}, "prompt", tmp_path
    )
    assert result["status"] == "failed"
    assert "Kein einziger Messwert" in result["error"]
    assert flatten_bench_rows(result) == []


@pytest.mark.usefixtures("mock_server")
def test_progress_callback_is_invoked(tmp_path: Path):
    notes = []
    run_http_bench(
        "http://testserver", {}, _bench_cfg(repetitions=2, prompt_tokens=[512]), {}, "prompt",
        tmp_path, on_progress=lambda note, sample: notes.append(note),  # noqa: ARG005
    )
    assert any("pp512" in n for n in notes)


def test_auth_headers_are_forwarded(monkeypatch, tmp_path: Path):
    seen_headers = []

    def _handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers.get("authorization"))
        return _completions_handler()(request)

    transport = httpx.MockTransport(_handler)

    class _PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("llmbench.http_bench.httpx.AsyncClient", _PatchedAsyncClient)
    monkeypatch.setattr("llmbench.http_bench.ResourceMonitor.start", lambda _self: None)
    monkeypatch.setattr("llmbench.http_bench.ResourceMonitor.stop", lambda _self: {"sample_count": 0})
    monkeypatch.setattr("llmbench.http_bench.ResourceMonitor.latest", lambda _self: None)

    run_http_bench(
        "http://testserver", {"Authorization": "Bearer tok"},
        _bench_cfg(repetitions=1, prompt_tokens=[512]), {}, "prompt", tmp_path,
    )
    assert seen_headers[-1] == "Bearer tok"
