from __future__ import annotations

from pathlib import Path

from llmbench.download import (
    MODELS,
    RichTqdm,
    _AdaptiveAmountColumn,
    download_models,
    find_downloaded_model,
    get_suite_models,
)


def _task_for(bar: RichTqdm):
    progress = RichTqdm._global_progress
    assert progress is not None
    assert bar.task_id is not None
    return next(task for task in progress.tasks if task.id == bar.task_id)


def test_late_total_update_reaches_rich_task() -> None:
    bar = RichTqdm(total=0, desc="Downloading (incomplete total...)", unit="B")
    try:
        task = _task_for(bar)
        assert task.total is None

        # huggingface_hub.snapshot_download macht genau dieses +=, sobald
        # die Dateigroesse nach dem HEAD/Metadata-Request bekannt wird.
        bar.total += 4_000_000_000
        task = _task_for(bar)
        assert task.total == 4_000_000_000

        bar.update(1_000_000_000)
        task = _task_for(bar)
        assert task.completed == 1_000_000_000
        assert task.percentage == 25.0
    finally:
        RichTqdm.close_all()


def test_unknown_total_never_displays_zero_byte_denominator() -> None:
    bar = RichTqdm(total=0, desc="Downloading (incomplete total...)", unit="B")
    try:
        bar.update(2_393_026_638)
        rendered = str(_AdaptiveAmountColumn().render(_task_for(bar)))
        assert "/0" not in rendered
        assert "geladen" in rendered
    finally:
        RichTqdm.close_all()


def test_iterable_progress_advances_file_counter() -> None:
    bar = RichTqdm(iter(["a", "b", "c"]), total=3, desc="Fetching 3 files")
    try:
        assert list(bar) == ["a", "b", "c"]
        task = _task_for(bar)
        assert bar.n == 3
        assert task.completed == 3
        assert task.total == 3
    finally:
        RichTqdm.close_all()


def test_set_description_str_is_tqdm_compatible() -> None:
    bar = RichTqdm(total=1, desc="Downloading")
    try:
        bar.set_description_str("Download complete")
        assert bar.desc == "Download complete"
        assert _task_for(bar).description == "Download complete"
    finally:
        RichTqdm.close_all()


def test_completed_model_is_recovered_after_progress_callback_error(
    tmp_path: Path, monkeypatch
) -> None:
    def _download_then_fail(**kwargs):
        local_dir = Path(kwargs["local_dir"])
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "Qwen3-8B-Q4_K_M.gguf").write_bytes(b"GGUF")
        raise AttributeError("'RichTqdm' object has no attribute 'set_description_str'")

    monkeypatch.setattr("llmbench.download.snapshot_download", _download_then_fail)

    download_models(tmp_path, "small", model_names=["Qwen3 8B"])

    found = find_downloaded_model(tmp_path, MODELS["small"]["Qwen3 8B"])
    assert found is not None
    assert found.name == "Qwen3-8B-Q4_K_M.gguf"


def test_shared_catalog_models_and_legacy_llama_only_models_are_separated() -> None:
    # The shared catalog is the same list that Ollama and vLLM offer.
    assert MODELS["small"]["Gemma 3 1B"]["repo_id"] == "ggml-org/gemma-3-1b-it-GGUF"
    assert MODELS["heavy"]["Qwen3.8 27B"]["repo_id"] == "bartowski/Qwen3.8-27B-GGUF"
    assert MODELS["extreme"]["Qwen3 235B"]["estimated_gib"] == 142.0
    assert MODELS["small"]["Granite 4.2 3B"]["repo_id"] == "ibm-granite/granite-4.2-3b-GGUF"

    # Models that only existed for llama.cpp stay selectable but are not part of the standard suite.
    assert MODELS["legacy"]["Qwen3.5-9B"]["repo_id"] == "unsloth/Qwen3.5-9B-GGUF"
    assert MODELS["legacy"]["Gemma-4-12B-IT"]["repo_id"] == "unsloth/gemma-4-12b-it-GGUF"
    assert MODELS["legacy"]["GLM-4.7-Flash"]["repo_id"] == "lmstudio-community/GLM-4.7-Flash-GGUF"
    assert MODELS["legacy"]["Qwen3.5-122B-A10B"]["repo_id"] == "unsloth/Qwen3.5-122B-A10B-GGUF"
    assert MODELS["legacy"]["Mistral-Small-4-119B-2603"]["repo_id"] == (
        "unsloth/Mistral-Small-4-119B-2603-GGUF"
    )
    assert MODELS["legacy"]["DeepSeek-V4-Flash-0731"]["repo_id"] == "unsloth/DeepSeek-V4-Flash-0731-GGUF"
    assert any("UD-Q4_K_M" in pattern for pattern in MODELS["legacy"]["Mistral-Small-4-119B-2603"]["pattern"])
    assert any("UD-Q4_K_XL" in pattern for pattern in MODELS["legacy"]["DeepSeek-V4-Flash-0731"]["pattern"])

    standard = get_suite_models("all")
    assert "Qwen3.5-9B" not in standard and "Gemma 3 1B" in standard
    assert "Qwen3 235B" not in standard  # extreme is only downloaded when chosen explicitly
