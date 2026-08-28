import subprocess
from pathlib import Path

import pytest

from llmbench.utils import (
    csv_value,
    ensure_dir,
    file_fingerprint,
    human_bytes,
    resolve_executable,
    safe_name,
    sha256_file,
    utc_now_compact,
    utc_now_iso,
    write_json,
    read_json,
)


def test_utc_now_iso_is_utc_and_iso_formatted():
    value = utc_now_iso()
    assert value.endswith("+00:00")
    assert "T" in value


def test_utc_now_compact_is_sortable_and_ends_in_z():
    value = utc_now_compact()
    assert value.endswith("Z")
    assert len(value) == len("20240101-120000Z")


def test_ensure_dir_creates_nested_path(tmp_path: Path):
    target = tmp_path / "a" / "b" / "c"
    result = ensure_dir(target)
    assert result == target
    assert target.is_dir()


def test_write_json_then_read_json_roundtrip(tmp_path: Path):
    path = tmp_path / "out" / "data.json"
    write_json(path, {"a": 1, "b": [1, 2, 3]})
    assert read_json(path) == {"a": 1, "b": [1, 2, 3]}


def test_sha256_file_matches_known_hash(tmp_path: Path):
    import hashlib

    p = tmp_path / "f.bin"
    p.write_bytes(b"hello world")
    assert sha256_file(p) == hashlib.sha256(b"hello world").hexdigest()


def test_file_fingerprint_missing_file_reports_not_exists(tmp_path: Path):
    info = file_fingerprint(tmp_path / "missing.gguf")
    assert info["exists"] is False
    assert "sha256" not in info


def test_file_fingerprint_existing_file_has_hash_and_size(tmp_path: Path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"content")
    info = file_fingerprint(p)
    assert info["exists"] is True
    assert info["size_bytes"] == len(b"content")
    assert "sha256" in info


def test_file_fingerprint_without_hash_skips_sha256(tmp_path: Path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"content")
    info = file_fingerprint(p, with_hash=False)
    assert "sha256" not in info


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "—"),
        (0, "0.00 B"),
        (1024, "1.00 KiB"),
        (1024 * 1024, "1.00 MiB"),
        (1024 ** 3, "1.00 GiB"),
        (1024 ** 4, "1.00 TiB"),
    ],
)
def test_human_bytes(value, expected):
    assert human_bytes(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("qwen-27b-q4_0.gguf", "qwen-27b-q4_0.gguf"),
        ("with spaces / slashes", "with_spaces_slashes"),
        ("...", "item"),
        ("", "item"),
    ],
)
def test_safe_name(value, expected):
    assert safe_name(value) == expected


def test_csv_value_joins_with_commas():
    assert csv_value([1, "a", None]) == "1,a,None"


def test_resolve_executable_finds_existing_file(tmp_path: Path):
    exe = tmp_path / "tool.bin"
    exe.write_text("x")
    assert resolve_executable(str(exe)) == str(exe.resolve())


def test_resolve_executable_raises_for_unknown_program():
    with pytest.raises(FileNotFoundError):
        resolve_executable("this-program-does-not-exist-anywhere-12345")


def test_kill_process_tree_terminates_a_real_process():
    import sys

    from llmbench.utils import kill_process_tree

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    kill_process_tree(proc)
    proc.wait(timeout=5)
    assert proc.poll() is not None
