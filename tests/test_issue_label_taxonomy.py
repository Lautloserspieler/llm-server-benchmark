"""Offline checks for the version-controlled GitHub issue-label taxonomy."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync_issue_labels.py"
SPEC = importlib.util.spec_from_file_location("label_sync_under_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
LABEL_MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LABEL_MODULE
SPEC.loader.exec_module(LABEL_MODULE)
sync_labels = LABEL_MODULE.sync_labels
validate_config = LABEL_MODULE.validate_config

CONFIG = ROOT / ".github" / "issue-labels.json"


def load_config():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def test_issue_label_taxonomy_is_valid():
    config = load_config()
    validate_config(config)
    assert len(config["labels"]) >= 15
    assert set(config["issue_assignments"]) == {str(n) for n in range(116, 141)}
    assert all(label["color"] != "" for label in config["labels"])


@pytest.mark.parametrize(
    "bad",
    [
        {"schema_version": 2, "labels": [], "issue_assignments": {}},
        {"schema_version": 1, "labels": [{"name": "bad", "color": "xyz", "description": ""}], "issue_assignments": {}},
        {"schema_version": 1, "labels": [{"name": "kind:feature", "color": "112233", "description": ""}], "issue_assignments": {"1": ["missing"]}},
    ],
)
def test_rejects_invalid_configuration(bad):
    with pytest.raises(ValueError):
        validate_config(bad)


def test_sync_preserves_unrelated_labels_and_replaces_legacy_enhancement():
    config = {
        "schema_version": 1,
        "labels": [
            {"name": "kind:feature", "color": "2563EB", "description": "Feature"},
            {"name": "release:1.8.0", "color": "BBF7D0", "description": "Release"},
        ],
        "issue_assignments": {"125": ["kind:feature", "release:1.8.0"]},
    }
    validate_config(config)
    calls = []
    actual = {
        "kind:feature": {"name": "kind:feature", "color": "2563eb", "description": "Feature"},
        "release:1.8.0": {"name": "release:1.8.0", "color": "bbf7d0", "description": "Release"},
    }
    state = ["enhancement", "keep-me"]

    def fake_api(_token, method, path, data=None):
        calls.append((method, path, data))
        if path.endswith("/labels?per_page=100&page=1"):
            return list(actual.values())
        if path.endswith("/issues/125") and method == "GET":
            return {"labels": [{"name": x} for x in state]}
        if path.endswith("/issues/125") and method == "PATCH":
            state[:] = data["labels"]
            return {"labels": [{"name": x} for x in state]}
        raise AssertionError(f"Unexpected API call: {method} {path}")

    with patch.object(LABEL_MODULE, "api_request", side_effect=fake_api):
        sync_labels("test", "org/repo", config, dry_run=False)
        assert state == ["keep-me", "kind:feature", "release:1.8.0"]
        before = len([x for x in calls if x[0] == "PATCH"])
        sync_labels("test", "org/repo", config, dry_run=False)
        assert len([x for x in calls if x[0] == "PATCH"]) == before


def test_dry_run_makes_no_write_requests():
    config = load_config()

    def fake_api(_token, method, path, _data=None):
        if method != "GET":
            raise AssertionError(f"Unexpected write in dry-run: {method}")
        if "/labels?" in path:
            return []
        if "/issues/" in path:
            return {"labels": [{"name": "enhancement"}]}
        raise AssertionError(f"Unexpected GET: {path}")

    with patch.object(LABEL_MODULE, "api_request", side_effect=fake_api):
        sync_labels("test", "org/repo", config, dry_run=True)


def test_issue_templates_use_new_taxonomy():
    templates = {
        "feature_request.md": 'labels: ["kind:feature"]',
        "backend_request.md": 'labels: ["kind:feature", "area:backends"]',
        "bug_report.md": 'labels: ["kind:bug"]',
    }
    for filename, expected in templates.items():
        text = (ROOT / ".github" / "ISSUE_TEMPLATE" / filename).read_text(encoding="utf-8")
        assert expected in text
        assert 'labels: ["enhancement"' not in text
