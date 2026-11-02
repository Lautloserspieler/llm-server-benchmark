from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/backend_release_watch.py"
spec = importlib.util.spec_from_file_location("backend_release_watch", SCRIPT)
assert spec and spec.loader
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


def release(tag: str, body: str = "", *, prerelease: bool = False) -> dict:
    return {"tag_name": tag, "body": body, "prerelease": prerelease}


def test_llama_cpp_batches_stable_releases_and_skips_docs_only():
    releases = [release("b11748", prerelease=True), release("b11749", "- README typo"),
                release("b11750", "- Fix CUDA server crash"),
                release("b11751-rc1", "- GPU", prerelease=True)]
    result = watch.review("llama_cpp", releases, "b11748")
    assert result["candidate"] == "b11750"
    assert [entry["status"] for entry in result["findings"]] == ["irrelevant", "relevant"]
    assert result["update"] is True
    assert watch.review("llama_cpp", releases[:2], "b11748")["update"] is False


def test_numbered_llama_prereleases_are_candidates():
    result = watch.review("llama_cpp", [release("b11748", prerelease=True),
                                        release("b11749", "- GPU", prerelease=True)], "b11748")
    assert result["candidate"] == "b11749"
    assert result["update"] is True


def test_large_llama_release_batch_has_bounded_pr_report():
    releases = [release("b11748", prerelease=True)]
    releases.extend(release(f"b{n}", "- Fix GPU model loading", prerelease=True)
                    for n in range(11749, 12041))
    result = watch.review("llama_cpp", releases, "b11748")
    assert result["candidate"] == "b12040"
    assert len(result["findings"]) == 292
    report = watch.markdown(result)
    assert "Reviewed 292 releases; showing the latest 12" in report
    assert "b11748...b12040" in report
    assert len(report) < 20000


def test_first_vllm_pin_uses_latest_stable_release():
    result = watch.review("vllm", [release("v0.32.0", "- README"),
                                   release("v0.33.0rc3", "- GPU"),
                                   release("v0.31.0", "- API")], "latest")
    assert result["candidate"] == "v0.32.0"
    assert result["update"] is True  # Pin is needed even for a docs-only release.


def test_tgi_release_tag_maps_to_published_image_tag(tmp_path: Path):
    result = watch.review("tgi", [release("v3.3.5"), release("v3.3.6", "- Fix server")], "3.3.5")
    assert result["candidate"] == "v3.3.6"
    assert result["update"] is True
    for name in watch.BACKENDS["tgi"]["files"]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ghcr.io/huggingface/text-generation-inference:3.3.5\n")
    watch.bump(tmp_path, result)
    assert all("inference:3.3.6" in (tmp_path / name).read_text()
               for name in watch.BACKENDS["tgi"]["files"])


def test_vllm_bump_updates_default_tag_assertion(tmp_path: Path):
    for name in watch.BACKENDS["vllm"]["files"]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('vllm/vllm-openai:latest\n', encoding="utf-8")
    assertion = tmp_path / "tests/test_backend_setup.py"
    assertion.write_text(assertion.read_text() + 'assert written["tag"] == "latest"\n')
    watch.bump(tmp_path, {"backend": "vllm", "baseline": "latest", "candidate": "v0.32.0"})
    assert 'assert written["tag"] == "v0.32.0"' in assertion.read_text()


def test_missing_baseline_fails_closed():
    with pytest.raises(ValueError, match="absent"):
        watch.review("llama_cpp", [release("b12040", "- CUDA")], "b11748")


def test_bump_changes_only_pinned_llama_line(tmp_path: Path):
    pin = tmp_path / "llama-cpp-version.txt"
    pin.write_text("# baseline b11748\nb11748\n")
    watch.bump(tmp_path, {"backend": "llama_cpp", "baseline": "b11748", "candidate": "b12040"})
    assert pin.read_text() == "# baseline b11748\nb12040\n"


def test_invalid_candidate_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="Unsafe"):
        watch.bump(tmp_path, {"backend": "llama_cpp", "baseline": "b11748", "candidate": "b1;exit"})
