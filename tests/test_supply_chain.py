"""Statische Pruefungen fuer Installer- und Supply-Chain-Haertung."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_posix_downloads_use_retry_and_fail_fast():
    text = (ROOT / "scripts" / "docker_common.sh").read_text(encoding="utf-8")

    assert "curl -fsSL --retry 3 --retry-delay 2" in text
    assert "--connect-timeout 10" in text
    assert "| _llmbench_sudo tee" not in text
    assert "chmod 777" not in text
    assert re.search(r"^\s*eval\b", text, re.MULTILINE) is None


def test_windows_download_helper_supports_integrity_and_retry():
    text = (ROOT / "scripts" / "lib" / "UI.psm1").read_text(encoding="utf-8")

    for token in ("ExpectedSha256", "MaxBytes", "Retries", ".part"):
        assert token in text


def test_windows_zip_extraction_validates_entries_before_expanding():
    text = (ROOT / "scripts" / "lib" / "LlamaCpp.psm1").read_text(encoding="utf-8")

    assert "function Assert-LlamaZipSafe" in text
    assert "Assert-LlamaZipSafe -Zip $Zip" in text


def test_requirements_txt_covers_pyproject_runtime_dependencies():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"dependencies\s*=\s*\[(.*?)\]", pyproject, re.DOTALL)
    assert block is not None
    declared = {
        re.split(r"[<>=!~\[]", item, maxsplit=1)[0].strip().lower().replace("_", "-")
        for item in re.findall(r'"([^"]+)"', block.group(1))
    }

    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    pinned = {
        re.split(r"[<>=!~;\[]", line.split("#", 1)[0], maxsplit=1)[0].strip().lower().replace("_", "-")
        for line in requirements.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert declared <= pinned, f"Fehlende Laufzeitabhaengigkeiten: {sorted(declared - pinned)}"


def test_pinned_artifacts_do_not_use_a_mutable_latest_tag():
    for name in (
        "Dockerfile",
        "compose.yaml",
        "compose.build.yaml",
        "scripts/docker_common.sh",
        "scripts/DOCKER_BENCHMARK.ps1",
    ):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert re.search(r":latest(?!@sha256:)", text) is None, name

    from llmbench import config

    for image in (
        config.DEFAULT_VLLM_IMAGE,
        config.DEFAULT_TGI_IMAGE,
        config.DEFAULT_OLLAMA_IMAGE,
    ):
        assert re.search(r"@sha256:[0-9a-f]{64}$", image), image
