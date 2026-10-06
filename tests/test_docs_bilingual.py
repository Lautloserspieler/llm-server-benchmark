from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DOC_PAIRS = (
    ("README.md", "README.de.md"),
    ("CHANGELOG.md", "CHANGELOG.en.md"),
    ("CONTRIBUTING.md", "CONTRIBUTING.en.md"),
    ("ROADMAP.md", "ROADMAP.en.md"),
    ("SECURITY.md", "SECURITY.de.md"),
    ("docs/DOCKER.md", "docs/DOCKER.en.md"),
    ("docs/RELEASE_CHECKLIST.md", "docs/RELEASE_CHECKLIST.de.md"),
    (
        "docs/linux-llamacpp-source-build.md",
        "docs/linux-llamacpp-source-build.en.md",
    ),
    ("models/README.md", "models/README.en.md"),
)

BILINGUAL_SINGLE_FILES = {
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/backend_request.md",
    ".github/ISSUE_TEMPLATE/bug_report.md",
    ".github/ISSUE_TEMPLATE/feature_request.md",
    "wiki/Home.md",
    "wiki/_Footer.md",
    "wiki/_Sidebar.md",
}


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_document_language_pairs_exist_and_link_each_other() -> None:
    for left, right in DOC_PAIRS:
        left_path = ROOT / left
        right_path = ROOT / right
        assert left_path.is_file(), f"Missing documentation file: {left}"
        assert right_path.is_file(), f"Missing documentation file: {right}"

        left_text = _read(left)
        right_text = _read(right)
        assert Path(right).name in left_text, f"{left} does not link to {right}"
        assert Path(left).name in right_text, f"{right} does not link to {left}"


def test_bilingual_single_files_contain_both_languages() -> None:
    for path in BILINGUAL_SINGLE_FILES:
        text = _read(path)
        assert "Deutsch" in text, f"{path} has no German language marker"
        assert "English" in text, f"{path} has no English language marker"


def test_wiki_german_and_english_pages_are_paired() -> None:
    de_pages = {path.name for path in (ROOT / "wiki/de").glob("*.md")}
    en_pages = {path.name for path in (ROOT / "wiki/en").glob("*.md")}
    assert de_pages == en_pages, (
        "Wiki language pages differ: "
        f"missing EN={sorted(de_pages - en_pages)}, "
        f"missing DE={sorted(en_pages - de_pages)}"
    )


def test_every_markdown_file_is_covered_by_bilingual_policy() -> None:
    covered = set(BILINGUAL_SINGLE_FILES)
    for left, right in DOC_PAIRS:
        covered.add(left)
        covered.add(right)

    for lang in ("de", "en"):
        covered.update(
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / f"wiki/{lang}").glob("*.md")
        )

    markdown_files = {
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*.md")
        if ".git" not in path.parts
    }

    assert markdown_files == covered, (
        "Markdown bilingual policy coverage mismatch: "
        f"uncovered={sorted(markdown_files - covered)}, "
        f"missing={sorted(covered - markdown_files)}"
    )
