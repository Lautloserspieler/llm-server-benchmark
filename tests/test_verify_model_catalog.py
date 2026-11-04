"""The catalog verifier, tested against a fake network (the real run needs internet)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest

from llmbench import model_catalog

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_model_catalog.py"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("verify_model_catalog", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_huggingface_repo_with_a_matching_gguf_file_is_ok(script):
    def handler(_request):
        return httpx.Response(200, json={"siblings": [{"rfilename": "model-Q4_K_M.gguf"}]})

    assert script.check_huggingface(_client(handler), "a/b", ("*Q4_K_M*.gguf",)) == (script.OK, "")


def test_huggingface_repo_without_the_expected_quant_is_missing(script):
    def handler(_request):
        return httpx.Response(200, json={"siblings": [{"rfilename": "model-Q8_0.gguf"}]})

    status, detail = script.check_huggingface(_client(handler), "a/b", ("*Q4_K_M*.gguf",))
    assert status == script.MISSING and "no file matches" in detail


@pytest.mark.parametrize(
    ("code", "expected"),
    [(404, "missing"), (401, "ok"), (403, "ok"), (500, "unreachable")],
)
def test_huggingface_status_codes(script, code, expected):
    status, _ = script.check_huggingface(_client(lambda _r: httpx.Response(code)), "a/b")
    assert status == expected


def test_a_network_error_is_unreachable_not_missing(script):
    def handler(_request):
        raise httpx.ConnectError("blocked")

    assert script.check_huggingface(_client(handler), "a/b")[0] == script.UNREACHABLE
    assert script.check_ollama(_client(handler), "gemma3:1b")[0] == script.UNREACHABLE


def test_ollama_tag_lookup_uses_the_library_namespace_and_namespaced_tags(script):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200)

    client = _client(handler)
    assert script.check_ollama(client, "gemma3:1b")[0] == script.OK
    assert script.check_ollama(client, "someone/model:7b")[0] == script.OK
    assert seen == ["/v2/library/gemma3/manifests/1b", "/v2/someone/model/manifests/7b"]
    assert script.check_ollama(_client(lambda _r: httpx.Response(404)), "nope:1b")[0] == script.MISSING


def test_verify_reports_unmapped_models_without_calling_the_network(script, monkeypatch):
    gap = model_catalog.CatalogModel("gap-1b", "Gap 1B", "SMALL", 1.0, {})
    monkeypatch.setattr(model_catalog, "CATALOG", (gap,))
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"siblings": []})

    results = script.verify(_client(handler), ("llama_cpp",), only={"gap-1b"})
    assert results[0]["status"] == "unmapped" and calls == []


def test_main_exits_2_when_nothing_can_be_checked(script, monkeypatch, capsys):
    def blocked(self, url, **_kwargs):  # noqa: ARG001
        raise httpx.ConnectError("blocked")

    monkeypatch.setattr(httpx.Client, "get", blocked)
    assert script.main(["--backend", "ollama", "--only", "gemma3-1b"]) == 2
    assert "network blocked" in capsys.readouterr().err


def test_main_exits_1_when_a_reference_is_missing(script, monkeypatch):
    def not_found(_self, url, **_kwargs):
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", not_found)
    assert script.main(["--backend", "ollama", "--only", "gemma3-1b"]) == 1
