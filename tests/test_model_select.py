from __future__ import annotations

from pathlib import Path

import pytest

from llmbench.download import (
    get_suite_models,
    load_model_selection,
    save_model_selection,
    verify_suite,
)
from llmbench.model_select import parse_selection


def test_parse_selection_supports_multiple_and_all() -> None:
    names = list(get_suite_models("all"))
    assert parse_selection("1,3,3", names) == [names[0], names[2]]
    assert parse_selection("a", names) == names
    assert parse_selection("0", names) == []


def test_parse_selection_rejects_invalid_values() -> None:
    names = list(get_suite_models("all"))
    with pytest.raises(ValueError):
        parse_selection("999", names)
    with pytest.raises(ValueError):
        parse_selection("foo", names)


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
