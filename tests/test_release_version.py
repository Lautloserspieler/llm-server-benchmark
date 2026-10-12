"""Keep every published version source in sync before tagging a release."""

import re
from importlib import metadata
from pathlib import Path

from llmbench import __version__


ROOT = Path(__file__).resolve().parents[1]


def test_release_version_consistency():
    file_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', project)
    assert match is not None, "Missing project version in pyproject.toml"
    assert file_version == __version__ == match.group(1)
    assert metadata.version("llm-server-benchmark") == __version__


def test_release_changelogs_have_single_version_header():
    for filename in ("CHANGELOG.md", "CHANGELOG.en.md"):
        content = (ROOT / filename).read_text(encoding="utf-8")
        assert content.count("## 1.6.0\n") == 1
        assert "community-export" in content
