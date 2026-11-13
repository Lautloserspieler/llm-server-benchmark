from __future__ import annotations

import importlib.util
import json
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


def test_current_version_reads_digest_pinned_default(tmp_path: Path):
    config = tmp_path / "llmbench" / "config.py"
    config.parent.mkdir(parents=True)
    config.write_text(
        'DEFAULT_OLLAMA_IMAGE = "ollama/ollama:0.40.13@sha256:'
        + "a" * 64
        + '"\n',
        encoding="utf-8",
    )

    assert watch.current_version(tmp_path) == "0.40.13"


def test_bump_drops_stale_digest_so_the_pr_can_add_a_fresh_one(tmp_path: Path):
    digest = "a" * 64
    for name in watch.FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"ollama/ollama:0.40.9@sha256:{digest}\n", encoding="utf-8")

    watch.bump(tmp_path, "0.40.9", "0.40.13")

    for name in watch.FILES:
        text = (tmp_path / name).read_text(encoding="utf-8")
        assert "ollama/ollama:0.40.13" in text
        assert "sha256:" not in text


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


def test_bump_allows_shared_constants_and_preserves_other_version_fixtures(tmp_path: Path):
    for name in watch.REQUIRED_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('DEFAULT_OLLAMA_IMAGE = "ollama/ollama:0.40.9"\n', encoding="utf-8")
    test_file = tmp_path / "tests/test_config.py"
    test_file.parent.mkdir()
    content = 'assert default == DEFAULT_OLLAMA_IMAGE\nold = "ollama/ollama:0.3.0"\nother = "ollama/ollama:0.40.90"\n'
    test_file.write_text(content, encoding="utf-8")
    watch.bump(tmp_path, "0.40.9", "0.40.13")
    assert test_file.read_text(encoding="utf-8") == content
    assert watch.current_version(tmp_path) == "0.40.13"


def test_bump_preflights_required_references_without_partial_changes(tmp_path: Path):
    originals = {}
    for name in watch.FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "shared constant\n" if name == watch.REQUIRED_FILES[1] else "ollama/ollama:0.40.9\n"
        path.write_text(content, encoding="utf-8")
        originals[path] = path.read_bytes()
    with pytest.raises(ValueError, match="Expected pinned reference absent"):
        watch.bump(tmp_path, "0.40.9", "0.40.13")
    assert all(path.read_bytes() == content for path, content in originals.items())


@pytest.mark.parametrize("new", ["0.40.8", "0.40.9", "latest", "0.40.10\n"])
def test_bump_refuses_invalid_or_non_increasing_versions(tmp_path, new):
    with pytest.raises(ValueError, match="increasing concrete"):
        watch.bump(tmp_path, "0.40.9", new)


def test_watcher_main_prepares_proposal_from_current_repository(tmp_path, monkeypatch):
    # Use the actual reference files: synthetic all-files-have-a-tag fixtures
    # missed the drift to shared constants that broke the scheduled workflow.
    root = tmp_path / "checkout"
    for name in watch.FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((watch.ROOT / name).read_bytes())
    baseline = watch.current_version(root)
    major, minor, patch = watch.version_key(baseline)
    candidate = f"{major}.{minor}.{patch + 1}"
    releases = tmp_path / "releases.json"
    releases.write_text(json.dumps([
        release(f"v{baseline}", ""), release(f"v{candidate}", "- Fix context truncation"),
    ]), encoding="utf-8")
    report = tmp_path / "review.json"
    monkeypatch.setattr("sys.argv", [str(SCRIPT), "--root", str(root), "--releases-json", str(releases), "--report", str(report)])
    watch.main()
    assert watch.current_version(root) == candidate
    assert json.loads(report.read_text(encoding="utf-8"))["update"] is True
    assert candidate in report.with_suffix(".md").read_text(encoding="utf-8")
    assert (root / "tests/test_config.py").read_bytes() == (watch.ROOT / "tests/test_config.py").read_bytes()
