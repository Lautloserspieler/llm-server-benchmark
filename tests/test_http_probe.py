"""Generischer HTTP-Kontext-/OOM-Probe fuer vLLM, TGI und Ollama.

Alle Tests laufen gegen einen echten lokalen HTTP-Server in einem Thread
(127.0.0.1, freier Port) statt gegen Mocks der HTTP-Bibliothek. Damit werden
Verbindungsfehler, Timeouts und Abbruch wirklich ueber den Socket ausgeloest.
Docker wird wie in den Backend-Tests ersetzt - es gibt weder GPU noch Docker.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from llmbench.backends.http_probe import (
    CATEGORY_CLIENT,
    CATEGORY_CONNECTION,
    CATEGORY_CONTEXT,
    CATEGORY_INVALID,
    CATEGORY_MODEL,
    CATEGORY_OOM,
    CATEGORY_SERVER,
    CATEGORY_STARTUP_FAILED,
    CATEGORY_TIMEOUT,
    CATEGORY_TRUNCATED,
    classify_failure,
    probe_context_http,
)
from llmbench.backends.ollama import OllamaBackend
from llmbench.backends.tgi import TgiBackend
from llmbench.backends.vllm import VllmBackend
from llmbench.http_bench import API_STYLE_OLLAMA_NATIVE, API_STYLE_OPENAI_COMPLETIONS
from llmbench.stress import oom

TGI_IMAGE = "ghcr.io/huggingface/text-generation-inference:latest"
OLLAMA_IMAGE = "ollama/ollama:latest"
VLLM_IMAGE = "vllm/vllm-openai:latest"


# --------------------------------------------------------------- Fake-Server


class FakeServer:
    """Kleiner HTTP-Server mit pro Pfad austauschbarem Handler.

    Ein Handler bekommt den geparsten JSON-Body und liefert
    ``(status, body)`` oder ``(status, body, delay_seconds)``. ``body`` ist ein
    dict (JSON) oder str (roh).
    """

    def __init__(self):
        self.routes: dict[tuple[str, str], object] = {}
        self.requests: list[tuple[str, str, dict]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):  # noqa: D401 - Testlaerm vermeiden
                return

            def _dispatch(self, method: str):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw) if raw else {}
                except ValueError:
                    body = {}
                outer.requests.append((method, self.path, body))
                handler = outer.routes.get((method, self.path))
                if handler is None:
                    status, payload, delay = 404, {"error": "not routed"}, 0.0
                else:
                    result = handler(body) if callable(handler) else handler
                    status, payload = result[0], result[1]
                    delay = result[2] if len(result) > 2 else 0.0
                if delay:
                    time.sleep(delay)
                data = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # Client hat (Timeout/Abbruch) bereits getrennt

            def do_GET(self):  # noqa: N802
                self._dispatch("GET")

            def do_POST(self):  # noqa: N802
                self._dispatch("POST")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    srv = FakeServer()
    yield srv
    srv.close()


def _fake_tokens(prompt: str) -> int:
    return len(prompt) // 4


def _openai_ok(limit: int | None = None, calls: list | None = None):
    def handler(body):
        if calls is not None:
            calls.append(body)
        tokens = _fake_tokens(body["prompt"])
        if limit is not None and tokens > limit:
            return 422, {
                "error": f"Input validation error: `inputs` must have less than {limit} tokens. "
                f"Given: {tokens}",
                "error_type": "validation",
            }
        return 200, {
            "choices": [{"text": "ok"}],
            "usage": {"prompt_tokens": tokens, "completion_tokens": 3, "total_tokens": tokens + 3},
        }

    return handler


# ----------------------------------------------------------- Klassifikation


@pytest.mark.parametrize(
    ("status", "text", "expected"),
    [
        (500, "CUDA out of memory. Tried to allocate 2.00 GiB", CATEGORY_OOM),
        (500, "model requires more system memory (12.1 GiB) than is available (8.0 GiB)", CATEGORY_OOM),
        (500, "llama runner process has terminated: cudaMalloc failed", CATEGORY_OOM),
        (422, "Input validation error: `inputs` must have less than 4096 tokens. Given: 5000", CATEGORY_CONTEXT),
        (400, "This model's maximum context length is 8192 tokens", CATEGORY_CONTEXT),
        (404, "model 'x' not found, try pulling it first", CATEGORY_MODEL),
        (404, "", CATEGORY_MODEL),
        (503, "Model is overloaded", CATEGORY_SERVER),
        (500, "internal error", CATEGORY_SERVER),
        (401, "unauthorized", CATEGORY_CLIENT),
        (200, "", CATEGORY_INVALID),
        # "oom" only counts as a word / kill marker, never as a substring
        (404, "model 'bigscience/bloom' does not exist", CATEGORY_MODEL),
        (400, "bigscience/bloom does not exist", CATEGORY_MODEL),
        (500, "no room left in the queue", CATEGORY_SERVER),
        (500, "container was OOM-killed", CATEGORY_OOM),
        (500, "process exited: OOMKilled", CATEGORY_OOM),
        (500, "kernel: oom-kill event", CATEGORY_OOM),
        (500, "worker died: OOM", CATEGORY_OOM),
        # a generic CUDA error is not an OOM
        (500, "CUDA error: an illegal memory access was encountered", CATEGORY_SERVER),
        (500, "CUDA error: out of memory", CATEGORY_OOM),
        # 404 + model marker wins over OOM-looking text
        (404, "model 'x' not found, try pulling it first (oom)", CATEGORY_MODEL),
    ],
)
def test_classify_failure_by_status_and_text(status, text, expected):
    assert classify_failure(status, text) == expected


def test_classify_failure_transport_errors():
    import httpx

    assert classify_failure(None, "t", httpx.ReadTimeout("slow")) == CATEGORY_TIMEOUT
    assert classify_failure(None, "refused", httpx.ConnectError("refused")) == CATEGORY_CONNECTION
    assert classify_failure(None, "reset", httpx.RemoteProtocolError("closed")) == CATEGORY_CONNECTION


# ------------------------------------------------- OpenAI-Stil (vLLM / TGI)


def test_openai_probe_ok_uses_discovered_model_and_server_token_count(server):
    calls: list[dict] = []
    server.routes[("GET", "/v1/models")] = (200, {"data": [{"id": "served-model"}]})
    server.routes[("POST", "/v1/completions")] = _openai_ok(calls=calls)

    result = asyncio.run(
        probe_context_http(server.url, 2048, {}, api_style=API_STYLE_OPENAI_COMPLETIONS)
    )

    assert result["ok"] is True
    assert result["http_status"] == 200
    assert result["target_prompt_tokens"] == 2048
    assert result["actual_prompt_tokens"] == _fake_tokens(calls[0]["prompt"])
    assert calls[0]["model"] == "served-model"
    assert calls[0]["stream"] is False
    assert "failure_category" not in result


def test_openai_probe_falls_back_to_configured_model_when_models_route_fails(server):
    calls: list[dict] = []
    server.routes[("POST", "/v1/completions")] = _openai_ok(calls=calls)

    result = asyncio.run(
        probe_context_http(server.url, 512, {"model": "cfg-model"}, api_style=API_STYLE_OPENAI_COMPLETIONS)
    )

    assert result["ok"] is True
    assert calls[0]["model"] == "cfg-model"


def test_openai_probe_sends_api_key(server):
    seen = {}
    server.routes[("POST", "/v1/completions")] = _openai_ok()
    orig = server.httpd.RequestHandlerClass.do_POST

    def spy(self):
        seen["auth"] = self.headers.get("Authorization")
        orig(self)

    server.httpd.RequestHandlerClass.do_POST = spy
    asyncio.run(
        probe_context_http(server.url, 256, {"api_key": "secret"}, api_style=API_STYLE_OPENAI_COMPLETIONS)
    )
    assert seen["auth"] == "Bearer secret"


def test_tgi_validation_error_is_context_exceeded(server):
    """TGI antwortet 422 mit 'Input validation error', wenn max-input-tokens ueberschritten wird."""
    server.routes[("POST", "/v1/completions")] = _openai_ok(limit=1000)

    result = asyncio.run(
        probe_context_http(server.url, 4096, {}, api_style=API_STYLE_OPENAI_COMPLETIONS)
    )

    assert result["ok"] is False
    assert result["failure_category"] == CATEGORY_CONTEXT
    assert result["http_status"] == 422
    assert "must have less than 1000" in result["error"]


def test_openai_probe_cuda_oom_response_is_out_of_memory(server):
    server.routes[("POST", "/v1/completions")] = (
        500,
        {"error": {"message": "CUDA out of memory. Tried to allocate 4.00 GiB", "type": "InternalServerError"}},
    )

    result = asyncio.run(
        probe_context_http(server.url, 65536, {}, api_style=API_STYLE_OPENAI_COMPLETIONS)
    )

    assert result["ok"] is False
    assert result["failure_category"] == CATEGORY_OOM
    assert "CUDA out of memory" in result["error"]


def test_openai_probe_non_json_success_body_is_invalid_response(server):
    server.routes[("POST", "/v1/completions")] = (200, "<html>proxy error</html>")

    result = asyncio.run(
        probe_context_http(server.url, 256, {}, api_style=API_STYLE_OPENAI_COMPLETIONS)
    )

    assert result["ok"] is False
    assert result["failure_category"] == CATEGORY_INVALID


@pytest.mark.parametrize("api_style,path,body", [
    (API_STYLE_OPENAI_COMPLETIONS, "/v1/completions", {}),
    (API_STYLE_OPENAI_COMPLETIONS, "/v1/completions", {"choices": []}),
    (API_STYLE_OPENAI_COMPLETIONS, "/v1/completions", {"usage": {"prompt_tokens": 2048}}),
    (API_STYLE_OLLAMA_NATIVE, "/api/generate", {}),
    (API_STYLE_OLLAMA_NATIVE, "/api/generate", {"done": False, "response": "partial"}),
    (API_STYLE_OLLAMA_NATIVE, "/api/generate", {"done": True}),
])
def test_probe_rejects_missing_or_incomplete_generation(server, api_style, path, body):
    server.routes[("POST", path)] = (200, body)
    result = asyncio.run(probe_context_http(server.url, 2048, {}, api_style=api_style))
    assert result["ok"] is False
    assert result["failure_category"] == CATEGORY_INVALID


@pytest.mark.parametrize("count", [True, -1, 0, 3.5, "2048", float("inf"), float("nan")])
@pytest.mark.parametrize("api_style,path", [
    (API_STYLE_OPENAI_COMPLETIONS, "/v1/completions"),
    (API_STYLE_OLLAMA_NATIVE, "/api/generate"),
])
def test_probe_rejects_invalid_token_counts(server, count, api_style, path):
    body = ({"choices": [{"text": "ok"}], "usage": {"prompt_tokens": count}}
            if api_style == API_STYLE_OPENAI_COMPLETIONS
            else {"done": True, "response": "ok", "prompt_eval_count": count})
    server.routes[("POST", path)] = (200, body)
    result = asyncio.run(probe_context_http(server.url, 2048, {}, api_style=api_style))
    assert result["ok"] is False
    assert result["failure_category"] == CATEGORY_INVALID


def test_probe_timeout_is_classified_and_does_not_raise(server):
    server.routes[("POST", "/v1/completions")] = lambda _b: (200, {"usage": {"prompt_tokens": 1}}, 1.5)

    started = time.perf_counter()
    result = asyncio.run(
        probe_context_http(server.url, 256, {"timeout_seconds": 0.3}, api_style=API_STYLE_OPENAI_COMPLETIONS)
    )

    assert result["ok"] is False
    assert result["failure_category"] == CATEGORY_TIMEOUT
    assert time.perf_counter() - started < 1.4


def test_probe_connection_refused_is_connection_error():
    probe_server = FakeServer()
    url = probe_server.url
    probe_server.close()  # Port ist danach garantiert zu

    result = asyncio.run(probe_context_http(url, 256, {}, api_style=API_STYLE_OPENAI_COMPLETIONS))

    assert result["ok"] is False
    assert result["failure_category"] == CATEGORY_CONNECTION


def test_probe_server_dropping_connection_is_connection_error():
    """Ein vom OOM-Killer beendeter Container kappt die Verbindung ohne Antwort."""
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]

    def drop():
        # Modellerkennung und Completion-Request oeffnen je eine Verbindung.
        while True:
            try:
                conn, _addr = sock.accept()
            except OSError:
                return
            conn.recv(65536)
            conn.close()

    thread = threading.Thread(target=drop, daemon=True)
    thread.start()
    try:
        result = asyncio.run(
            probe_context_http(f"http://127.0.0.1:{port}", 256, {}, api_style=API_STYLE_OPENAI_COMPLETIONS)
        )
    finally:
        sock.close()
        thread.join(2)

    assert result["ok"] is False
    assert result["failure_category"] == CATEGORY_CONNECTION


def test_probe_cancellation_propagates(server):
    """Abbruch (Ctrl+C / Task-Cancel) darf nicht als Probe-Ergebnis verschluckt werden."""
    server.routes[("POST", "/v1/completions")] = lambda _b: (200, {}, 2.0)

    async def scenario():
        task = asyncio.create_task(
            probe_context_http(server.url, 256, {"timeout_seconds": 30}, api_style=API_STYLE_OPENAI_COMPLETIONS)
        )
        await asyncio.sleep(0.3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_probe_rejects_unsupported_api_style():
    with pytest.raises(ValueError):
        asyncio.run(probe_context_http("http://127.0.0.1:1", 1, {}, api_style="llama_cpp"))


# ------------------------------------------------------------- Ollama-Stil


def _ollama_handler(*, calls: list | None = None, oom_above_ctx: int | None = None, truncate: bool = True):
    def handler(body):
        if calls is not None:
            calls.append(body)
        num_ctx = int(body["options"]["num_ctx"])
        if oom_above_ctx is not None and num_ctx > oom_above_ctx:
            return 500, {"error": "model requires more system memory (14.2 GiB) than is available (8.1 GiB)"}
        tokens = _fake_tokens(body["prompt"])
        if truncate:
            tokens = min(tokens, num_ctx)
        return 200, {"model": body["model"], "response": "ok", "done": True, "prompt_eval_count": tokens}

    return handler


def test_ollama_probe_ok_requests_stage_context_via_num_ctx(server):
    calls: list[dict] = []
    server.routes[("POST", "/api/generate")] = _ollama_handler(calls=calls)

    result = asyncio.run(
        probe_context_http(
            server.url, 2048, {"model": "llama3", "context_size": 2560}, api_style=API_STYLE_OLLAMA_NATIVE
        )
    )

    assert result["ok"] is True
    assert result["actual_prompt_tokens"] == _fake_tokens(calls[0]["prompt"])
    assert calls[0]["model"] == "llama3"
    assert calls[0]["options"]["num_ctx"] == 2560
    assert calls[0]["raw"] is True
    assert calls[0]["stream"] is False
    assert calls[0]["truncate"] is False
    assert calls[0]["shift"] is False


def test_ollama_probe_detects_silent_truncation(server):
    """Ollama kuerzt zu lange Prompts auf num_ctx - das ist kein bestandener Probe."""
    server.routes[("POST", "/api/generate")] = _ollama_handler()

    result = asyncio.run(
        probe_context_http(
            server.url, 8192, {"model": "m", "context_size": 1024}, api_style=API_STYLE_OLLAMA_NATIVE
        )
    )

    assert result["ok"] is False
    assert result["failure_category"] == CATEGORY_TRUNCATED
    assert result["actual_prompt_tokens"] == 1024


def test_ollama_probe_disables_half_window_truncation(server):
    """Ollama 0.40 may shorten 4173 tokens to 514 with num_ctx=1024.

    Reject the overlong request at the server; the old near-num_ctx heuristic
    cannot recognize that half-window result as truncated.
    """
    def handler(body):
        if body.get("truncate", True) or body.get("shift", True):
            return 200, {"done": True, "response": "ok", "prompt_eval_count": 514}
        return 400, {"error": "prompt too long for context"}

    server.routes[("POST", "/api/generate")] = handler
    result = asyncio.run(probe_context_http(
        server.url, 4096, {"model": "m", "context_size": 1024}, api_style=API_STYLE_OLLAMA_NATIVE,
    ))
    assert result["ok"] is False
    assert result["failure_category"] == CATEGORY_CONTEXT
    assert result["http_status"] == 400


def test_ollama_probe_memory_error_is_out_of_memory(server):
    server.routes[("POST", "/api/generate")] = _ollama_handler(oom_above_ctx=4096)

    result = asyncio.run(
        probe_context_http(
            server.url, 16384, {"model": "m", "context_size": 16896}, api_style=API_STYLE_OLLAMA_NATIVE
        )
    )

    assert result["ok"] is False
    assert result["failure_category"] == CATEGORY_OOM
    assert result["http_status"] == 500


def test_ollama_probe_error_in_200_body_is_reported(server):
    server.routes[("POST", "/api/generate")] = (
        200, {"error": "llama runner process has terminated: CUDA error: out of memory"}
    )

    result = asyncio.run(
        probe_context_http(server.url, 2048, {"model": "m"}, api_style=API_STYLE_OLLAMA_NATIVE)
    )

    assert result["ok"] is False
    assert result["failure_category"] == CATEGORY_OOM


def test_ollama_probe_missing_prompt_eval_count_is_unverified(server):
    server.routes[("POST", "/api/generate")] = (200, {"response": "ok", "done": True})

    result = asyncio.run(
        probe_context_http(server.url, 2048, {"model": "m", "context_size": 2560}, api_style=API_STYLE_OLLAMA_NATIVE)
    )

    assert result["ok"] is True
    assert result["actual_prompt_tokens"] is None
    assert result["actual_unverified"] is True


def test_ollama_probe_measured_count_is_not_flagged_unverified(server):
    server.routes[("POST", "/api/generate")] = _ollama_handler()
    result = asyncio.run(
        probe_context_http(server.url, 2048, {"model": "m", "context_size": 2560}, api_style=API_STYLE_OLLAMA_NATIVE)
    )
    assert result["ok"] is True
    assert "actual_unverified" not in result


def test_ollama_probe_tokenizer_overshoot_beyond_margin_is_not_a_false_failure(server):
    """Tokenizer deviates >512 tokens: Ollama clips to num_ctx, but the level was reached."""
    server.routes[("POST", "/api/generate")] = lambda body: (
        200, {"response": "ok", "done": True, "prompt_eval_count": int(body["options"]["num_ctx"])}
    )

    result = asyncio.run(
        probe_context_http(server.url, 2048, {"model": "m", "context_size": 2560}, api_style=API_STYLE_OLLAMA_NATIVE)
    )

    assert result["ok"] is True
    assert result["actual_prompt_tokens"] == 2560
    assert result["truncated_at_num_ctx"] is True


def test_openai_probe_missing_usage_is_unverified(server):
    server.routes[("POST", "/v1/completions")] = (200, {"choices": [{"text": "ok"}]})
    result = asyncio.run(
        probe_context_http(server.url, 2048, {"model": "m"}, api_style=API_STYLE_OPENAI_COMPLETIONS)
    )
    assert result["ok"] is True and result["actual_unverified"] is True


def test_ollama_probe_unknown_model_is_model_not_found(server):
    server.routes[("POST", "/api/generate")] = (404, {"error": "model 'nope' not found, try pulling it first"})

    result = asyncio.run(
        probe_context_http(server.url, 2048, {"model": "nope"}, api_style=API_STYLE_OLLAMA_NATIVE)
    )

    assert result["ok"] is False
    assert result["failure_category"] == CATEGORY_MODEL


# ----------------------------------------------- Backend-Anbindung + Health


@pytest.mark.parametrize(
    ("backend", "route"),
    [
        (VllmBackend(VLLM_IMAGE), ("POST", "/v1/completions")),
        (TgiBackend(TGI_IMAGE), ("POST", "/v1/completions")),
        (OllamaBackend(OLLAMA_IMAGE), ("POST", "/api/generate")),
    ],
    ids=["vllm", "tgi", "ollama"],
)
def test_backends_expose_probe_context(server, backend, route):
    server.routes[route] = (
        _openai_ok() if route[1] == "/v1/completions" else _ollama_handler()
    )

    result = asyncio.run(backend.probe_context(server.url, 1024, {"model": "m", "context_size": 2048}))

    assert result["ok"] is True
    assert result["actual_prompt_tokens"] > 0


def test_tgi_wait_health_succeeds_after_warmup(server):
    """TGI laedt das Modell zuerst; /health antwortet 503 und danach 200."""
    state = {"n": 0}

    def health(_b):
        state["n"] += 1
        return (503, {"error": "loading"}) if state["n"] < 2 else (200, {})

    server.routes[("GET", "/health")] = health
    waited = TgiBackend(TGI_IMAGE).wait_health(server.url, 10.0, {})

    assert state["n"] >= 2
    assert waited >= 0


def test_tgi_wait_health_times_out_with_last_error(server):
    server.routes[("GET", "/health")] = (503, {"error": "model still loading"})

    with pytest.raises(TimeoutError, match="503"):
        TgiBackend(TGI_IMAGE).wait_health(server.url, 1.0, {})


def test_ollama_wait_health_uses_api_tags(server):
    server.routes[("GET", "/api/tags")] = (200, {"models": []})

    assert OllamaBackend(OLLAMA_IMAGE).wait_health(server.url, 5.0, {}) >= 0
    assert ("GET", "/api/tags", {}) in server.requests


# ------------------------------------- OOM-Stresstest Ende-zu-Ende (Mock)


@pytest.fixture
def docker(monkeypatch):
    class _Fake:
        def __init__(self):
            self.runs: list[dict] = []
            self.stopped: list[str] = []
            self.fail_run = False

        def run_container(self, name, image, args, **kwargs):
            if self.fail_run:
                raise RuntimeError("docker run failed: no space left on device")
            self.runs.append({"name": name, "image": image, "args": list(args), **kwargs})
            return "CID"

        def stop_container(self, name, log=None):  # noqa: ARG002
            self.stopped.append(name)

        def container_pid(self, _name):
            return 77

        def container_exists(self, _name):
            return False

        def container_logs(self, _name, tail=None):  # noqa: ARG002
            return "container log"

    fake = _Fake()
    for backend_module in ("tgi", "ollama", "vllm"):
        for fn in ("run_container", "stop_container", "container_pid", "container_exists", "container_logs"):
            monkeypatch.setattr(f"llmbench.backends.{backend_module}.docker_backend.{fn}", getattr(fake, fn))
        monkeypatch.setattr(
            f"llmbench.backends.{backend_module}.backend_setup.ensure_backend",
            lambda *_a, **_k: {"image": "img"},
        )
    monkeypatch.setattr(
        "llmbench.backends.ollama.OllamaBackend._ensure_registry_model", lambda _s, _m: None
    )

    real_sleep = asyncio.sleep

    async def fast_sleep(_seconds):
        await real_sleep(0)

    monkeypatch.setattr(oom.asyncio, "sleep", fast_sleep)
    return fake


def _oom_config(url: str, model: str, levels: list[int], **endpoint) -> dict:
    return {
        "project": {"output_dir": "results"},
        "tools": {},
        "benchmark": {},
        "stress": {"oom_contexts": levels},
        "endpoint": {"base_url": url, "startup_timeout_seconds": 2, **endpoint},
        "models": [{"name": "M", "path": model, "profiles": [{"name": "GPU"}]}],
        "_config_dir": ".",
    }


def _run_oom(monkeypatch, cfg: dict, backend, name: str, out: Path) -> int:
    monkeypatch.setattr(oom, "load_config", lambda _p: cfg)
    monkeypatch.setattr(oom, "get_backend", lambda _c: backend)
    monkeypatch.setattr(oom, "backend_name", lambda _c: name)
    return asyncio.run(oom.run_oom_stress("ignored.yaml", out))


def test_tgi_oom_stress_finds_limit_and_stops_container_per_level(monkeypatch, server, docker, tmp_path: Path):
    server.routes[("GET", "/health")] = (200, {})
    server.routes[("POST", "/v1/completions")] = _openai_ok(limit=5000)
    cfg = _oom_config(server.url, "org/Model", [2048, 4096, 8192, 16384])
    backend = TgiBackend(TGI_IMAGE, endpoint_cfg=cfg["endpoint"], root=tmp_path)

    rc = _run_oom(monkeypatch, cfg, backend, "tgi", tmp_path)

    assert rc == 0
    doc = json.loads((tmp_path / "oom.json").read_text(encoding="utf-8"))
    assert doc["status"] == "ok"
    assert doc["backend"] == "tgi"
    # org/Model ist eine HF-Referenz und darf nicht zu einem Dateipfad werden
    assert doc["model_path"] == "org/Model"
    statuses = [lvl["status"] for lvl in doc["levels"]]
    assert statuses == ["ok", "ok", "request_failed"]  # nach dem ersten Fehler wird abgebrochen
    failed = doc["levels"][-1]
    assert failed["failure_category"] == CATEGORY_CONTEXT
    assert failed["probe"]["http_status"] == 422
    assert doc["max_stable_prompt_tokens"] == doc["levels"][1]["probe"]["actual_prompt_tokens"] > 0
    # je Stufe ein Container-Start mit passendem max-total-tokens ...
    assert [r["args"][r["args"].index("--max-total-tokens") + 1] for r in docker.runs] == ["2560", "4608", "8704"]
    # ... und Cleanup nach jeder Stufe, auch nach der fehlgeschlagenen
    assert docker.stopped.count("llmbench-tgi") >= 3 + 3  # 3x Pre-Start-Cleanup + 3x stop_server


def test_tgi_oom_stress_health_timeout_cleans_up_and_reports_startup_failed(monkeypatch, server, docker, tmp_path: Path):
    server.routes[("GET", "/health")] = (503, {"error": "loading"})
    cfg = _oom_config(server.url, "org/Model", [2048, 4096], startup_timeout_seconds=1)
    backend = TgiBackend(TGI_IMAGE, endpoint_cfg=cfg["endpoint"], root=tmp_path)

    rc = _run_oom(monkeypatch, cfg, backend, "tgi", tmp_path)

    assert rc == 1
    doc = json.loads((tmp_path / "oom.json").read_text(encoding="utf-8"))
    assert doc["status"] == "failed"
    assert [lvl["status"] for lvl in doc["levels"]] == ["startup_failed"]
    assert doc["levels"][0]["failure_category"] == "startup_failed"
    assert "503" in doc["levels"][0]["error"]
    assert len(docker.runs) == 1  # kein zweiter Startversuch nach dem Fehlschlag
    assert docker.stopped  # Container wurde trotzdem entfernt
    assert not any(req[1] == "/v1/completions" for req in server.requests)


def test_oom_stress_docker_run_failure_is_structured(monkeypatch, server, docker, tmp_path: Path):
    docker.fail_run = True
    cfg = _oom_config(server.url, "org/Model", [2048])
    backend = TgiBackend(TGI_IMAGE, endpoint_cfg=cfg["endpoint"], root=tmp_path)

    rc = _run_oom(monkeypatch, cfg, backend, "tgi", tmp_path)

    assert rc == 1
    doc = json.loads((tmp_path / "oom.json").read_text(encoding="utf-8"))
    assert doc["levels"][0]["status"] == "startup_failed"
    assert "no space left" in doc["levels"][0]["error"]


@pytest.mark.usefixtures("docker")
def test_vllm_oom_stress_records_oom_response(monkeypatch, server, tmp_path: Path):
    server.routes[("GET", "/health")] = (200, {})
    server.routes[("GET", "/v1/models")] = (200, {"data": [{"id": "m"}]})

    def handler(body):
        if _fake_tokens(body["prompt"]) > 3000:
            return 500, {"error": {"message": "CUDA out of memory while allocating KV cache"}}
        return _openai_ok()(body)

    server.routes[("POST", "/v1/completions")] = handler
    cfg = _oom_config(server.url, "org/Model", [2048, 4096])
    backend = VllmBackend(VLLM_IMAGE, endpoint_cfg=cfg["endpoint"], root=tmp_path)

    rc = _run_oom(monkeypatch, cfg, backend, "vllm", tmp_path)

    assert rc == 0
    doc = json.loads((tmp_path / "oom.json").read_text(encoding="utf-8"))
    assert [lvl["status"] for lvl in doc["levels"]] == ["ok", "request_failed"]
    assert doc["levels"][1]["failure_category"] == CATEGORY_OOM


def test_ollama_oom_stress_uses_model_reference_and_stage_context(monkeypatch, server, docker, tmp_path: Path):
    calls: list[dict] = []
    server.routes[("GET", "/api/tags")] = (200, {"models": []})
    server.routes[("POST", "/api/generate")] = _ollama_handler(calls=calls, oom_above_ctx=4096)
    cfg = _oom_config(server.url, "llama3.2:3b", [2048, 8192])
    backend = OllamaBackend(OLLAMA_IMAGE, endpoint_cfg=cfg["endpoint"], root=tmp_path)

    rc = _run_oom(monkeypatch, cfg, backend, "ollama", tmp_path)

    assert rc == 0
    doc = json.loads((tmp_path / "oom.json").read_text(encoding="utf-8"))
    assert doc["model_path"] == "llama3.2:3b"
    assert [lvl["status"] for lvl in doc["levels"]] == ["ok", "request_failed"]
    assert doc["levels"][1]["failure_category"] == CATEGORY_OOM
    assert [c["model"] for c in calls] == ["llama3.2:3b", "llama3.2:3b"]
    assert [c["options"]["num_ctx"] for c in calls] == [2560, 8704]
    assert docker.stopped


def test_oom_stress_probe_exception_still_writes_result_and_cleans_up(monkeypatch, server, docker, tmp_path: Path):
    server.routes[("GET", "/health")] = (200, {})
    cfg = _oom_config(server.url, "org/Model", [2048])
    backend = TgiBackend(TGI_IMAGE, endpoint_cfg=cfg["endpoint"], root=tmp_path)

    async def boom(*_a, **_k):
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(backend, "probe_context", boom)

    rc = _run_oom(monkeypatch, cfg, backend, "tgi", tmp_path)

    assert rc == 1
    doc = json.loads((tmp_path / "oom.json").read_text(encoding="utf-8"))
    assert doc["levels"][0]["failure_category"] == "probe_error"
    assert "probe exploded" in doc["levels"][0]["probe"]["error"]
    assert docker.stopped


@pytest.mark.parametrize(
    ("backend", "name"),
    [
        (VllmBackend(VLLM_IMAGE), "vllm"),
        (TgiBackend(TGI_IMAGE), "tgi"),
        (OllamaBackend(OLLAMA_IMAGE), "ollama"),
    ],
)
def test_quantization_and_multi_model_stay_structured_skips(monkeypatch, backend, name, tmp_path: Path):
    """Quant-Vergleich und Multi-Tenant bleiben fuer Container-Backends ehrlich unsupported."""
    from llmbench.stress import multitenant, quant

    cfg = {
        "project": {"output_dir": "results"},
        "tools": {},
        "benchmark": {},
        "endpoint": {},
        "models": [
            {"name": "A", "path": "a", "profiles": [{"name": "GPU", "gpu_layers": -1}]},
            {"name": "B", "path": "b", "profiles": [{"name": "GPU", "gpu_layers": -1}]},
        ],
        "_config_dir": str(tmp_path),
    }
    models = tmp_path / "models"
    models.mkdir()
    for fname in ("m-Q4_K_M.gguf", "m-Q8_0.gguf"):
        (models / fname).write_bytes(b"GGUF")

    monkeypatch.setattr(multitenant, "load_config", lambda _p: cfg)
    monkeypatch.setattr(multitenant, "get_backend", lambda _c: backend)
    monkeypatch.setattr(multitenant, "backend_name", lambda _c: name)
    assert asyncio.run(multitenant.run_multitenant("x", tmp_path / "mt")) == 2
    mt = json.loads((tmp_path / "mt" / "multitenant.json").read_text(encoding="utf-8"))
    assert mt["status"] == "skipped"
    assert mt["reason"] == "backend_capability_missing"
    assert mt["missing_capabilities"] == ["multi_model"]

    monkeypatch.setattr(quant, "load_config", lambda _p: cfg)
    monkeypatch.setattr(quant, "get_backend", lambda _c: backend)
    monkeypatch.setattr(quant, "backend_name", lambda _c: name)
    assert asyncio.run(quant.run_quant_stress("x", tmp_path / "q")) == 2
    q = json.loads((tmp_path / "q" / "quant.json").read_text(encoding="utf-8"))
    assert q["status"] == "skipped"
    assert q["reason"] == "backend_capability_missing"
    assert q["missing_capabilities"] == ["quantization"]


def test_oom_stress_start_server_failure_after_run_container_stops_container(
    monkeypatch, server, docker, tmp_path: Path
):
    cfg = _oom_config(server.url, "org/Model", [2048])
    backend = TgiBackend(TGI_IMAGE, endpoint_cfg=cfg["endpoint"], root=tmp_path)
    real_start = backend.start_server
    stops_before_raise: list[int] = []

    def start_then_raise(*args, **kwargs):
        real_start(*args, **kwargs)  # run_container succeeded, container is up
        stops_before_raise.append(len(docker.stopped))
        raise RuntimeError("late failure after docker run")

    monkeypatch.setattr(backend, "start_server", start_then_raise)

    rc = _run_oom(monkeypatch, cfg, backend, "tgi", tmp_path)

    assert rc == 1
    assert len(docker.runs) == 1
    assert len(docker.stopped) > stops_before_raise[0]  # container was stopped in the error path
    doc = json.loads((tmp_path / "oom.json").read_text(encoding="utf-8"))
    assert doc["levels"][0]["status"] == "startup_failed"
    assert "late failure" in doc["levels"][0]["error"]


def test_oom_stress_llama_cpp_start_failure_without_proc_does_not_crash(monkeypatch, server, tmp_path: Path):
    from llmbench.backends.llama_cpp import LlamaCppBackend

    cfg = _oom_config(server.url, "model.gguf", [2048])
    backend = LlamaCppBackend("llama-bench", "llama-server")

    def boom(*_a, **_k):
        raise RuntimeError("spawn failed")

    monkeypatch.setattr(backend, "start_server", boom)
    stopped: list = []
    monkeypatch.setattr(backend, "stop_server", lambda proc: stopped.append(proc))

    rc = _run_oom(monkeypatch, cfg, backend, "llama_cpp", tmp_path)

    assert rc == 1
    assert stopped == []  # nothing was started, nothing to stop
    doc = json.loads((tmp_path / "oom.json").read_text(encoding="utf-8"))
    assert doc["levels"][0]["failure_category"] == CATEGORY_STARTUP_FAILED


@pytest.mark.usefixtures("docker")
def test_oom_stress_success_level_omits_failure_category(monkeypatch, server, tmp_path: Path):
    server.routes[("GET", "/health")] = (200, {})
    server.routes[("POST", "/v1/completions")] = _openai_ok()
    cfg = _oom_config(server.url, "org/Model", [2048])
    backend = TgiBackend(TGI_IMAGE, endpoint_cfg=cfg["endpoint"], root=tmp_path)

    assert _run_oom(monkeypatch, cfg, backend, "tgi", tmp_path) == 0
    level = json.loads((tmp_path / "oom.json").read_text(encoding="utf-8"))["levels"][0]
    assert level["status"] == "ok"
    assert "failure_category" not in level


@pytest.mark.usefixtures("docker")
def test_oom_stress_unverified_token_count_never_becomes_max_stable(monkeypatch, server, tmp_path: Path):
    server.routes[("GET", "/api/tags")] = (200, {"models": []})
    server.routes[("POST", "/api/generate")] = (200, {"response": "ok", "done": True})
    cfg = _oom_config(server.url, "llama3.2:3b", [2048])
    backend = OllamaBackend(OLLAMA_IMAGE, endpoint_cfg=cfg["endpoint"], root=tmp_path)

    rc = _run_oom(monkeypatch, cfg, backend, "ollama", tmp_path)

    doc = json.loads((tmp_path / "oom.json").read_text(encoding="utf-8"))
    assert doc["levels"][0]["status"] == "ok"
    assert doc["levels"][0]["probe"]["actual_unverified"] is True
    assert doc["max_stable_prompt_tokens"] == 0
    assert doc["status"] == "unverified"
    assert rc == 1
