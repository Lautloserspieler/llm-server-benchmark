"""One model catalog for every backend: same models, backend-specific references."""

from __future__ import annotations

import pytest
import yaml

from llmbench import model_catalog
from llmbench.backend_model_select import OLLAMA_MODEL_CATALOG, _write_runtime_models
from llmbench.doctor import catalog_warning, check_model_reference


def test_every_catalog_model_is_offered_on_ollama_with_the_curated_list():
    # The Ollama list is the master: every model has an Ollama tag.
    assert all(model.reference("ollama") for model in model_catalog.CATALOG)
    assert [item["ref"] for item in OLLAMA_MODEL_CATALOG] == [m.reference("ollama").ref for m in model_catalog.CATALOG]


def test_ids_and_names_are_unique():
    ids = [m.id for m in model_catalog.CATALOG]
    names = [m.name for m in model_catalog.CATALOG]
    assert len(set(ids)) == len(ids) and len(set(names)) == len(names)


def test_vllm_and_tgi_share_the_huggingface_reference():
    for model in model_catalog.CATALOG:
        assert model.reference("vllm") == model.reference("tgi")


def test_every_reference_declares_its_precision():
    for model in model_catalog.CATALOG:
        for reference in model.refs.values():
            assert reference.precision


def test_llama_cpp_references_carry_gguf_patterns_and_a_filename_hint():
    for model in model_catalog.models_for_backend("llama_cpp"):
        reference = model.reference("llama_cpp")
        assert reference.patterns and reference.filename_hint


def _catalog_with_gap(monkeypatch):
    gap = model_catalog.CatalogModel(
        "gap-1b", "Gap 1B", "SMALL", 1.0, {"ollama": model_catalog.Reference("gap:1b", "Q4_K_M")}
    )
    monkeypatch.setattr(model_catalog, "CATALOG", (*model_catalog.CATALOG, gap))
    return gap


def test_every_catalog_model_is_available_on_every_backend():
    for backend in model_catalog.BACKENDS:
        assert model_catalog.unavailable_for_backend(backend) == []


def test_unmapped_models_are_reported_not_invented(monkeypatch):
    gap = _catalog_with_gap(monkeypatch)
    assert [m.id for m in model_catalog.unavailable_for_backend("llama_cpp")] == ["gap-1b"]
    assert gap.reference("llama_cpp") is None


def test_models_keep_the_same_order_on_every_backend():
    order = {m.id: i for i, m in enumerate(model_catalog.CATALOG)}
    for backend in ("llama_cpp", "ollama", "vllm", "tgi"):
        ids = [m.id for m in model_catalog.models_for_backend(backend)]
        assert ids == sorted(ids, key=order.__getitem__)


def test_extreme_models_can_be_left_out():
    assert all(m.tier != "EXTREME" for m in model_catalog.models_for_backend("ollama", include_extreme=False))


@pytest.mark.parametrize(
    ("reference", "backend", "expected"),
    [
        ("gemma3:1b", "ollama", "gemma3-1b"),
        ("ggml-org/gemma-3-1b-it-GGUF", "llama_cpp", "gemma3-1b"),
        ("/models/gemma-3-1b-it-Q4_K_M.gguf", "llama_cpp", "gemma3-1b"),
        ("C:\\models\\Qwen3-8B-Q4_K_M.gguf", "llama_cpp", "qwen3-8b"),
        ("Qwen/Qwen3-8B", "vllm", "qwen3-8b"),
        ("qwen/qwen3-8b", "tgi", "qwen3-8b"),
        ("gpt-oss:20b", None, "gpt-oss-20b"),
        ("something-else:7b", "ollama", None),
        ("gemma3:1b", "vllm", None),  # a tag is not a Hugging Face reference
        ("", "ollama", None),
    ],
)
def test_identify_maps_a_configured_reference_back_to_the_catalog(reference, backend, expected):
    found = model_catalog.identify(reference, backend)
    assert (found.id if found else None) == expected


def test_precision_differs_between_backends_for_the_same_model():
    assert model_catalog.precision_of("qwen3-8b", "ollama") == "Q4_K_M"
    assert model_catalog.precision_of("qwen3-8b", "vllm") == "bf16"
    assert model_catalog.precision_of("gpt-oss-20b", "vllm") == "MXFP4"
    assert model_catalog.precision_of("no-such-model", "vllm") is None


def test_config_entry_uses_the_same_display_name_on_every_backend(monkeypatch):
    model = model_catalog.get("qwen3-8b")
    entries = {b: model_catalog.config_entry(model, b) for b in ("ollama", "llama_cpp", "vllm")}
    assert {e["name"] for e in entries.values()} == {"Qwen3 8B"}
    assert {e["catalog_id"] for e in entries.values()} == {"qwen3-8b"}
    assert entries["ollama"]["path"] == "qwen3:8b" and entries["vllm"]["path"] == "Qwen/Qwen3-8B"
    with pytest.raises(ValueError):
        model_catalog.config_entry(_catalog_with_gap(monkeypatch), "vllm")


@pytest.mark.parametrize(
    ("backend", "reference"),
    [("ollama", "qwen3:8b"), ("vllm", "Qwen/Qwen3-8B"), ("llama_cpp", "/m/Qwen3-8B-Q4_K_M.gguf")],
)
def test_setup_writes_the_catalog_name_and_precision_into_the_config(tmp_path, backend, reference):
    config = tmp_path / "benchmark.yaml"
    _write_runtime_models(config, backend, [reference])
    (entry,) = yaml.safe_load(config.read_text(encoding="utf-8"))["models"]
    assert entry["name"] == "Qwen3 8B"
    assert entry["catalog_id"] == "qwen3-8b"
    assert entry["precision"] == model_catalog.precision_of("qwen3-8b", backend)
    assert entry["path"] == reference


def test_models_outside_the_catalog_keep_their_own_name_and_get_no_catalog_id(tmp_path):
    config = tmp_path / "benchmark.yaml"
    _write_runtime_models(config, "ollama", ["my-own:7b"])
    (entry,) = yaml.safe_load(config.read_text(encoding="utf-8"))["models"]
    assert entry["name"] == "my-own:7b" and "catalog_id" not in entry


# -------------------------------------------------- doctor: reference fits the backend


@pytest.mark.parametrize(
    ("backend", "reference", "exists", "level"),
    [
        ("llama_cpp", "gemma3:1b", False, "error"),            # the mistake we saw on a real machine
        ("llama_cpp", "Qwen/Qwen3-8B", False, "error"),
        ("llama_cpp", "/models/x.gguf", False, None),          # a missing file is reported elsewhere
        ("vllm", "gemma3:1b", False, "error"),
        ("tgi", "qwen3:8b", False, "error"),
        ("vllm", "Qwen/Qwen3-8B", False, None),
        ("ollama", "Qwen/Qwen3-8B", False, "warning"),
        ("ollama", "someuser/model:7b", False, None),        # namespaced Ollama tag
        ("ollama", "hf.co/org/repo", False, None),
        ("ollama", "qwen3:8b", False, None),
        ("ollama", "/models/x.gguf", True, None),
    ],
)
def test_doctor_detects_a_model_reference_of_the_wrong_backend(backend, reference, exists, level):
    problem = check_model_reference(backend, reference, exists)
    assert (problem["level"] if problem else None) == level
    if problem:
        assert "llmbench setup" in problem["message"]


def test_doctor_warns_once_per_model_outside_the_catalog_but_not_for_catalog_models():
    assert catalog_warning("ollama", {"name": "X", "path": "my-own:7b"}) is not None
    assert catalog_warning("ollama", {"name": "Qwen3 8B", "path": "qwen3:8b"}) is None
    assert catalog_warning("vllm", {"name": "custom", "path": "/data/model", "catalog_id": "qwen3-8b"}) is None
