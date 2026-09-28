from __future__ import annotations

from llmbench.download import MODELS, RichTqdm, _AdaptiveAmountColumn, get_suite_models


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


def test_2026_model_manifest_uses_verified_repositories_and_quants() -> None:
    assert MODELS["small"]["Qwen3.5-9B"]["repo_id"] == "unsloth/Qwen3.5-9B-GGUF"
    assert MODELS["mid"]["Gemma-4-12B-IT"]["repo_id"] == "unsloth/gemma-4-12b-it-GGUF"
    assert MODELS["mid"]["Qwen3.8-27B"]["repo_id"] == "bartowski/Qwen3.8-27B-GGUF"
    assert MODELS["mid"]["Qwen3.5-35B-A3B"]["repo_id"] == "unsloth/Qwen3.5-35B-A3B-GGUF"
    assert MODELS["heavy"]["Qwen3.5-122B-A10B"]["repo_id"] == (
        "unsloth/Qwen3.5-122B-A10B-GGUF"
    )
    assert MODELS["heavy"]["Mistral-Small-4-119B-2603"]["repo_id"] == (
        "unsloth/Mistral-Small-4-119B-2603-GGUF"
    )
    assert MODELS["extreme"]["DeepSeek-V4-Flash-0731"]["repo_id"] == (
        "unsloth/DeepSeek-V4-Flash-0731-GGUF"
    )

    assert any(
        "UD-Q4_K_M" in pattern
        for pattern in MODELS["heavy"]["Mistral-Small-4-119B-2603"]["pattern"]
    )
    assert any(
        "UD-Q4_K_XL" in pattern
        for pattern in MODELS["extreme"]["DeepSeek-V4-Flash-0731"]["pattern"]
    )
    assert len(get_suite_models("all")) == 6
