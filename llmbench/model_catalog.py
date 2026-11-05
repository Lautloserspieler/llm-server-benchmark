"""One model catalog for every backend.

Results of different backends are only comparable when the same models were
measured. Until now llama.cpp, Ollama and vLLM each offered a different list.
This module is the single source of truth: the same models are offered on every
backend, each with the reference that fits the backend:

* ``ollama``    - Ollama library tag (``gemma3:1b``)
* ``llama_cpp`` - GGUF repository, file pattern and quantization on Hugging Face
* ``vllm``      - Hugging Face repository with the original weights (also used for TGI)

The same model is not byte-identical across backends: GGUF and Ollama use a
quantization (usually Q4_K_M), vLLM loads the original bf16/fp16 weights. The
``precision`` of every reference is therefore stored, shown in reports and used
to warn when two runs compare different precisions.

``verified`` marks references that were checked against the registry: the
Hugging Face repositories and GGUF file names (checked on 2026-11-04) and the
Ollama tags of the project's curated list. Re-check them with
``scripts/verify_model_catalog.py`` (needs network access); a reference that is
not verified is shown as "unverified" in the menus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

BACKENDS = ("llama_cpp", "ollama", "vllm", "tgi")
# TGI loads the same Hugging Face weights as vLLM.
_REF_KEY = {"llama_cpp": "llama_cpp", "ollama": "ollama", "vllm": "vllm", "tgi": "vllm"}


@dataclass(frozen=True)
class Reference:
    """How one backend obtains a catalog model."""

    ref: str
    precision: str
    verified: bool = False
    # llama.cpp only: GGUF file patterns inside the repository.
    patterns: tuple[str, ...] = ()
    filename_hint: str = ""
    note: str = ""


@dataclass(frozen=True)
class CatalogModel:
    id: str
    name: str
    tier: str  # SMALL | MID | HEAVY | EXTREME
    estimated_gib: float
    refs: dict[str, Reference] = field(default_factory=dict)

    def reference(self, backend: str) -> Reference | None:
        return self.refs.get(_REF_KEY.get(backend, backend))


def _q4(repo: str, hint: str, *, verified: bool = True, note: str = "") -> Reference:
    return Reference(
        ref=repo,
        precision="Q4_K_M",
        verified=verified,
        patterns=("*Q4_K_M*.gguf", "*q4_k_m*.gguf"),
        filename_hint=hint,
        note=note,
    )


def _hf(repo: str, precision: str = "bf16", *, note: str = "") -> Reference:
    return Reference(ref=repo, precision=precision, verified=True, note=note)


CATALOG: tuple[CatalogModel, ...] = (
    CatalogModel(
        "gemma3-1b", "Gemma 3 1B", "SMALL", 0.8,
        {
            "ollama": Reference("gemma3:1b", "Q4_K_M", verified=True),
            "llama_cpp": _q4("ggml-org/gemma-3-1b-it-GGUF", "gemma-3-1b-it", verified=True),
            "vllm": _hf("google/gemma-3-1b-it", note="gated repository: accept the licence and set HF_TOKEN"),
        },
    ),
    CatalogModel(
        "granite4.2-3b", "Granite 4.2 3B", "SMALL", 2.2,
        {
            "ollama": Reference("granite4.2:3b", "Q4_K_M", verified=True),
            "llama_cpp": _q4("ibm-granite/granite-4.2-3b-GGUF", "granite-4.2-3b"),
            "vllm": _hf("ibm-granite/granite-4.2-3b"),
        },
    ),
    CatalogModel(
        "qwen3-8b", "Qwen3 8B", "SMALL", 5.2,
        {
            "ollama": Reference("qwen3:8b", "Q4_K_M", verified=True),
            "llama_cpp": _q4("Qwen/Qwen3-8B-GGUF", "qwen3-8b"),
            "vllm": _hf("Qwen/Qwen3-8B"),
        },
    ),
    CatalogModel(
        "deepseek-r1-14b", "DeepSeek-R1 14B", "MID", 9.0,
        {
            "ollama": Reference("deepseek-r1:14b", "Q4_K_M", verified=True),
            "llama_cpp": _q4("bartowski/DeepSeek-R1-Distill-Qwen-14B-GGUF", "deepseek-r1-distill-qwen-14b"),
            "vllm": _hf("deepseek-ai/DeepSeek-R1-Distill-Qwen-14B"),
        },
    ),
    CatalogModel(
        "gpt-oss-20b", "GPT-OSS 20B", "MID", 14.0,
        {
            "ollama": Reference("gpt-oss:20b", "MXFP4", verified=True),
            "llama_cpp": Reference(
                "ggml-org/gpt-oss-20b-GGUF", "MXFP4", verified=True,
                patterns=("*MXFP4*.gguf", "*mxfp4*.gguf"), filename_hint="gpt-oss-20b"
            ),
            "vllm": _hf("openai/gpt-oss-20b", "MXFP4"),
        },
    ),
    CatalogModel(
        "mistral-small3.2-24b", "Mistral Small 3.2 24B", "MID", 15.0,
        {
            "ollama": Reference("mistral-small3.2:24b", "Q4_K_M", verified=True),
            "llama_cpp": _q4(
                "bartowski/mistralai_Mistral-Small-3.2-24B-Instruct-2506-GGUF", "mistral-small-3.2-24b"
            ),
            "vllm": _hf("mistralai/Mistral-Small-3.2-24B-Instruct-2506"),
        },
    ),
    CatalogModel(
        "qwen3.8-27b", "Qwen3.8 27B", "HEAVY", 18.0,
        {
            "ollama": Reference("qwen3.8:27b", "Q4_K_M", verified=True),
            "llama_cpp": _q4("bartowski/Qwen3.8-27B-GGUF", "qwen3.8-27b", verified=True),
            "vllm": _hf("Qwen/Qwen3.8-27B"),
        },
    ),
    CatalogModel(
        "deepseek-r1-70b", "DeepSeek-R1 70B", "HEAVY", 43.0,
        {
            "ollama": Reference("deepseek-r1:70b", "Q4_K_M", verified=True),
            "llama_cpp": _q4("bartowski/DeepSeek-R1-Distill-Llama-70B-GGUF", "deepseek-r1-distill-llama-70b"),
            "vllm": _hf("deepseek-ai/DeepSeek-R1-Distill-Llama-70B"),
        },
    ),
    CatalogModel(
        "gpt-oss-120b", "GPT-OSS 120B", "HEAVY", 65.0,
        {
            "ollama": Reference("gpt-oss:120b", "MXFP4", verified=True),
            "llama_cpp": Reference(
                "ggml-org/gpt-oss-120b-GGUF", "MXFP4", verified=True,
                patterns=("*MXFP4*.gguf", "*mxfp4*.gguf"), filename_hint="gpt-oss-120b"
            ),
            "vllm": _hf("openai/gpt-oss-120b", "MXFP4"),
        },
    ),
    CatalogModel(
        "qwen3-235b", "Qwen3 235B", "EXTREME", 142.0,
        {
            "ollama": Reference("qwen3:235b", "Q4_K_M", verified=True),
            "llama_cpp": _q4("unsloth/Qwen3-235B-A22B-GGUF", "qwen3-235b-a22b"),
            "vllm": _hf("Qwen/Qwen3-235B-A22B"),
        },
    ),
)

_BY_ID = {model.id: model for model in CATALOG}


def get(model_id: str) -> CatalogModel | None:
    return _BY_ID.get(model_id)


def models_for_backend(backend: str, *, include_extreme: bool = True) -> list[CatalogModel]:
    """Catalog models that have a reference for ``backend`` (same order everywhere)."""
    return [
        model
        for model in CATALOG
        if model.reference(backend) is not None and (include_extreme or model.tier != "EXTREME")
    ]


def unavailable_for_backend(backend: str) -> list[CatalogModel]:
    """Models the catalog knows but cannot offer on this backend yet."""
    return [model for model in CATALOG if model.reference(backend) is None]


def identify(reference: str, backend: str | None = None) -> CatalogModel | None:
    """Map a configured reference (tag, repo id, GGUF path) back to a catalog model."""
    text = str(reference or "").strip().replace("\\", "/")
    if not text:
        return None
    lowered = text.lower()
    leaf = lowered.rsplit("/", 1)[-1]
    for model in CATALOG:
        for key, ref in model.refs.items():
            if backend is not None and _REF_KEY.get(backend, backend) != key:
                continue
            if key == "llama_cpp":
                hint = ref.filename_hint.lower()
                if hint and (leaf.startswith(hint) or f"/{hint}" in lowered or lowered == ref.ref.lower()):
                    return model
            elif lowered == ref.ref.lower():
                return model
    return None


def reference_precision(reference: str, backend: str, model: CatalogModel) -> str:
    """Use the observed GGUF quantization instead of assuming the catalog default.

    A local GGUF path may use Q8_0 or another variant of the same base model.
    Unknown local precision must never silently become the catalog's Q4_K_M.
    """
    declared = model.reference(backend)
    if declared is None:
        return "unknown"
    if backend != "llama_cpp" or not reference.lower().endswith(".gguf"):
        return declared.precision
    leaf = reference.replace("\\\\", "/").rsplit("/", 1)[-1]
    match = re.search(r"(?<![A-Za-z0-9])(Q[2-8]_[A-Z0-9_]+|IQ[1-4]_[A-Z0-9_]+|MXFP4)(?=\\.gguf$|[-_.])", leaf, re.I)
    return match.group(1).upper() if match else "unknown"


def precision_of(model_id: str, backend: str) -> str | None:
    model = get(model_id)
    ref = model.reference(backend) if model else None
    return ref.precision if ref else None


def config_entry(model: CatalogModel, backend: str, reference: str | None = None) -> dict[str, Any]:
    """Model entry for ``benchmark.yaml``: the display name is identical on every backend."""
    ref = model.reference(backend)
    if ref is None:
        raise ValueError(f"{model.name} ist fuer das Backend {backend!r} nicht im Katalog.")
    return {
        "name": model.name,
        "path": reference or ref.ref,
        "catalog_id": model.id,
        "precision": reference_precision(reference or ref.ref, backend, model),
    }
