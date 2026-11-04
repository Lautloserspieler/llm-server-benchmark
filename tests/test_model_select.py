from __future__ import annotations

from pathlib import Path

import pytest

from llmbench.download import (
    get_catalog_models,
    get_models_by_name,
    get_suite_models,
    load_model_selection,
    save_model_selection,
    verify_suite,
)
from llmbench.model_select import parse_selection


def test_standard_suite_is_the_shared_catalog_and_extreme_is_separated() -> None:
    standard = get_suite_models("all")
    extreme = get_suite_models("extreme")
    catalog = get_catalog_models()

    # Same models as Ollama/vLLM offer, cheapest first.
    assert list(standard)[0] == "Gemma 3 1B"
    assert list(standard) == [
        "Gemma 3 1B",
        "Granite 4.2 3B",
        "Qwen3 8B",
        "DeepSeek-R1 14B",
        "GPT-OSS 20B",
        "Mistral Small 3.2 24B",
        "Qwen3.8 27B",
        "DeepSeek-R1 70B",
        "GPT-OSS 120B",
    ]
    assert list(extreme) == ["Qwen3 235B"]
    assert "Qwen3 235B" not in standard
    # catalog = shared models + the llama.cpp-only models
    assert len(catalog) == len(standard) + len(extreme) + 6


def test_extreme_model_can_be_selected_explicitly() -> None:
    selected = get_models_by_name(["Qwen3 235B", "DeepSeek-V4-Flash-0731"])
    assert selected["Qwen3 235B"]["repo_id"] == "unsloth/Qwen3-235B-A22B-GGUF"
    assert selected["DeepSeek-V4-Flash-0731"]["repo_id"] == (
        "unsloth/DeepSeek-V4-Flash-0731-GGUF"
    )
    assert any("UD-Q4_K_XL" in pattern for pattern in selected["DeepSeek-V4-Flash-0731"]["pattern"])


def test_parse_selection_supports_multiple_and_all() -> None:
    names = list(get_suite_models("all"))
    assert parse_selection("1,3,3", names) == [names[0], names[2]]
    assert parse_selection("a", names) == names
    assert parse_selection("0", names) == []


def test_terminal_selection_lists_extreme_but_a_keeps_standard_suite() -> None:
    catalog_names = list(get_catalog_models())
    standard_names = list(get_suite_models("all"))

    assert "DeepSeek-V4-Flash-0731" in catalog_names
    assert "DeepSeek-V4-Flash-0731" not in standard_names
    assert parse_selection("a", catalog_names, all_selection_names=standard_names) == standard_names

    extreme_index = catalog_names.index("DeepSeek-V4-Flash-0731") + 1
    assert parse_selection(str(extreme_index), catalog_names, all_selection_names=standard_names) == [
        "DeepSeek-V4-Flash-0731"
    ]


def test_parse_selection_rejects_invalid_values() -> None:
    names = list(get_suite_models("all"))
    with pytest.raises(ValueError):
        parse_selection("999", names)
    with pytest.raises(ValueError):
        parse_selection("foo", names)


def test_saved_qwen35_selection_migrates_to_glm47(tmp_path: Path) -> None:
    path = tmp_path / ".llmbench-model-selection.json"
    path.write_text(
        '{"version": 1, "models": ["Qwen3.5-9B", "Qwen3.5-35B-A3B"]}\n',
        encoding="utf-8",
    )

    assert load_model_selection(tmp_path) == ["Qwen3.5-9B", "GLM-4.7-Flash"]


def test_saved_selection_roundtrip(tmp_path: Path) -> None:
    names = list(get_suite_models("all"))
    selected = [names[0], names[2]]
    path = save_model_selection(tmp_path, selected)

    assert path.name == ".llmbench-model-selection.json"
    assert load_model_selection(tmp_path) == selected


def test_verify_all_can_use_saved_setup_selection(tmp_path: Path, monkeypatch) -> None:
    names = list(get_suite_models("all"))
    save_model_selection(tmp_path, [names[0]])
    monkeypatch.setenv("LLMBENCH_USE_SAVED_SELECTION", "1")

    complete, missing = verify_suite(tmp_path, "all")
    assert complete is False
    assert missing == [names[0]]


def test_verify_all_ignores_saved_selection_without_opt_in(tmp_path: Path, monkeypatch) -> None:
    names = list(get_suite_models("all"))
    save_model_selection(tmp_path, [names[0]])
    monkeypatch.delenv("LLMBENCH_USE_SAVED_SELECTION", raising=False)

    complete, missing = verify_suite(tmp_path, "all")
    assert complete is False
    assert missing == names
