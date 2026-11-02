from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ollama_release_watch.py"
spec = importlib.util.spec_from_file_location("ollama_release_watch", SCRIPT)
assert spec and spec.loader
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


def release(tag: str, body: str, *, prerelease: bool = False) -> dict:
    return {"tag_name": tag, "body": body, "prerelease": prerelease,
            "html_url": f"https://github.com/ollama/ollama/releases/tag/{tag}"}


def test_review_checks_every_stable_release_since_reference():
    releases = [release("v0.40.9", ""), release("v0.40.10", "- Update documentation"),
                release("v0.40.11", "- Fix prompt context truncation"),
                release("v0.40.12-rc1", "- GPU changes", prerelease=True),
                release("v0.40.12", "- Website typo")]
    result = watch.review(releases, "0.40.9")
    assert result["candidate"] == "0.40.12"
    assert [item["status"] for item in result["findings"]] == ["irrelevant", "relevant", "irrelevant"]
    assert result["update"] is True


def test_docs_only_skips_and_unknown_notes_require_review():
    baseline = release("v0.40.9", "")
    assert watch.review([baseline, release("v0.40.10", "- README typo")], "0.40.9")["update"] is False
    assert watch.review([baseline, release("v0.40.10", "Changed something")], "0.40.9")["update"] is True


def test_contributor_noise_is_not_evidence_and_report_is_readable():
    result = watch.review([
        release("v0.40.9", ""),
        release("v0.40.10", "- @person made their first contribution in https://github.com/ollama/ollama/pull/1"),
        release("v0.40.11", "- Fix context truncation\n- Update README"),
    ], "0.40.9")
    assert result["findings"][0]["status"] == "unclear"
    assert result["findings"][0]["evidence"] == []
    report = watch.markdown(result)
    assert "### Release review" in report
    assert "- Fix context truncation" in report
    assert "first contribution" not in report
    assert "- [ ] Run the pinned context" in report


def test_missing_baseline_fails_closed():
    with pytest.raises(ValueError, match="missing"):
        watch.review([release("v0.40.13", "- Improve API")], "0.40.9")


def test_bump_updates_only_reference_files(tmp_path: Path):
    for name in watch.FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ollama/ollama:0.40.9\n", encoding="utf-8")
    unrelated = tmp_path / "old-report.md"
    unrelated.write_text("ollama/ollama:0.40.9", encoding="utf-8")
    watch.bump(tmp_path, "0.40.9", "0.40.13")
    assert all("ollama/ollama:0.40.13" in (tmp_path / name).read_text() for name in watch.FILES)
    assert unrelated.read_text() == "ollama/ollama:0.40.9"
