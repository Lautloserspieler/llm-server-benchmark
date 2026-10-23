from pathlib import Path

import pytest

from llmbench.backends.capabilities import BackendCapabilities
from llmbench.backends.llama_cpp import LlamaCppBackend
from llmbench.backends.ollama import OllamaBackend
from llmbench.backends.tgi import TgiBackend
from llmbench.backends.vllm import VllmBackend
from llmbench.stress.base import require_capabilities


def test_backend_capabilities_reject_unknown_name():
    capabilities = BackendCapabilities(endpoint=True)
    assert capabilities.supports("endpoint") is True
    assert capabilities.supports("oom_probe") is False
    with pytest.raises(ValueError, match="Unbekannte Backend-Faehigkeit"):
        capabilities.supports("does_not_exist")


def test_llama_cpp_declares_current_stress_capabilities():
    backend = LlamaCppBackend("llama-bench", "llama-server")
    assert backend.supports("endpoint")
    assert backend.supports("concurrency")
    assert backend.supports("oom_probe")
    assert backend.supports("quantization")
    assert backend.supports("multi_model")


def test_vllm_declares_only_adapter_capabilities(tmp_path: Path):
    backend = VllmBackend("vllm/vllm-openai:latest", root=tmp_path)
    assert backend.supports("endpoint")
    assert backend.supports("concurrency")
    assert backend.supports("long_context")
    assert backend.supports("kv_cache_observation")
    assert backend.supports("oom_probe")
    assert backend.supports("quantization") is False
    assert backend.supports("multi_model") is False


@pytest.mark.parametrize(
    "factory",
    [
        lambda root: VllmBackend("vllm/vllm-openai:latest", root=root),
        lambda root: TgiBackend("ghcr.io/huggingface/text-generation-inference:latest", root=root),
        lambda root: OllamaBackend("ollama/ollama:latest", root=root),
    ],
)
def test_http_backends_declare_only_implemented_stress_capabilities(factory, tmp_path: Path):
    backend = factory(tmp_path)
    # oom_probe hat eine echte, per Mock-HTTP getestete Implementierung ...
    assert backend.supports("oom_probe")
    # ... Quantisierungsvergleich und Multi-Model-Stress nicht: ein Container
    # pro Backend-Instanz, kein lokaler Quant-Varianten-Vertrag.
    assert backend.supports("quantization") is False
    assert backend.supports("multi_model") is False


def test_require_capabilities_writes_structured_skip(tmp_path: Path):
    backend = VllmBackend("vllm/vllm-openai:latest", root=tmp_path)
    backend.capabilities = BackendCapabilities(endpoint=True, oom_probe=False)
    path = tmp_path / "oom.json"

    rc = require_capabilities(
        backend,
        "vllm",
        ("endpoint", "oom_probe"),
        workload="text.oom_probe",
        result_path=path,
    )

    assert rc == 2
    import json

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["status"] == "skipped"
    assert document["reason"] == "backend_capability_missing"
    assert document["backend"] == "vllm"
    assert document["required_capabilities"] == ["endpoint", "oom_probe"]
    assert document["missing_capabilities"] == ["oom_probe"]
