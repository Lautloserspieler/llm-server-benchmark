"""Backend-Auswahl.

``runner.py`` instanziierte frueher fest ``LlamaCppBackend``. Die Factory hier
ist die einzige Stelle, an der ein neues Backend eingehaengt werden muss.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import BenchmarkBackend
from .capabilities import BackendCapabilities, BackendCapabilityError

DEFAULT_BACKEND = "llama_cpp"


def backend_name(cfg: dict[str, Any]) -> str:
    """Konfiguriertes Backend. Fehlt der Schluessel, gilt llama.cpp.

    Damit bleiben bestehende Konfigurationen ohne ``tools.backend`` unveraendert
    gueltig.
    """
    return (cfg.get("tools") or {}).get("backend") or DEFAULT_BACKEND


def get_backend(cfg: dict[str, Any]) -> BenchmarkBackend:
    name = backend_name(cfg)
    tools = cfg.get("tools") or {}

    if name == "llama_cpp":
        from .llama_cpp import LlamaCppBackend

        return LlamaCppBackend(tools["llama_bench"], tools["llama_server"])

    if name == "vllm":
        from ..backend_setup import DEFAULT_VLLM_IMAGE
        from .vllm import VllmBackend

        return VllmBackend(
            tools.get("vllm_image") or DEFAULT_VLLM_IMAGE,
            endpoint_cfg=cfg.get("endpoint") or {},
            root=Path(cfg.get("_config_dir") or "."),
        )

    if name == "tgi":
        from ..backend_setup import DEFAULT_TGI_IMAGE
        from .tgi import TgiBackend

        return TgiBackend(
            tools.get("tgi_image") or DEFAULT_TGI_IMAGE,
            endpoint_cfg=cfg.get("endpoint") or {},
            root=Path(cfg.get("_config_dir") or "."),
        )

    if name == "ollama":
        from ..backend_setup import DEFAULT_OLLAMA_IMAGE
        from .ollama import OllamaBackend

        return OllamaBackend(
            tools.get("ollama_image") or DEFAULT_OLLAMA_IMAGE,
            endpoint_cfg=cfg.get("endpoint") or {},
            root=Path(cfg.get("_config_dir") or "."),
        )

    raise ValueError(f"Unbekanntes Backend: {name!r}. Erlaubt: llama_cpp, vllm, tgi, ollama")


__all__ = [
    "DEFAULT_BACKEND",
    "BackendCapabilities",
    "BackendCapabilityError",
    "BenchmarkBackend",
    "backend_name",
    "get_backend",
]
