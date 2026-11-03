import os
import stat
import subprocess
from pathlib import Path

import pytest

from llmbench.utils import (
    csv_value,
    ensure_dir,
    file_fingerprint,
    human_bytes,
    redact_command,
    redact_secrets,
    resolve_executable,
    safe_name,
    sha256_file,
    utc_now_compact,
    utc_now_iso,
    write_json,
    write_text_atomic,
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


def test_write_json_redacts_credentials_at_persistence_boundary(tmp_path: Path):
    path = tmp_path / "data.json"
    write_json(path, {"api_key": "sk-live", "metrics": {"tokens": 7}})
    assert read_json(path) == {"api_key": "***", "metrics": {"tokens": 7}}


def test_write_json_leaves_no_temporary_file(tmp_path: Path):
    path = tmp_path / "data.json"
    path.write_text('{"old": true}', encoding="utf-8")
    write_json(path, {"new": True})
    assert read_json(path) == {"new": True}
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.skipif(os.name == "nt", reason="POSIX-Dateirechte werden unter Windows nicht abgebildet.")
def test_write_text_atomic_applies_restrictive_mode(tmp_path: Path):
    path = tmp_path / "secret.json"
    write_text_atomic(path, "{}", mode=0o600)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_redact_secrets_masks_credentials_but_keeps_metrics():
    data = {
        "endpoint": {"api_key": "sk-top", "base_url": "https://user:pass@example.test/v1"},
        "models": [{"endpoint": {"api_key": "sk-nested"}}],
        "metrics": {"tokens": 42, "prompt_tokens": 10, "completion_tokens": 32},
        "password": "secret",
        "authorization": "Bearer abc",
        "safe": "value",
    }

    redacted = redact_secrets(data)

    assert redacted["endpoint"]["api_key"] == "***"
    assert redacted["endpoint"]["base_url"] == "https://***@example.test/v1"
    assert redacted["models"][0]["endpoint"]["api_key"] == "***"
    assert redacted["metrics"] == {"tokens": 42, "prompt_tokens": 10, "completion_tokens": 32}
    assert redacted["password"] == "***"
    assert redacted["authorization"] == "***"
    assert redacted["safe"] == "value"
    assert data["endpoint"]["api_key"] == "sk-top"


def test_redact_command_masks_secret_flag_values():
    assert redact_command(["docker", "run", "--api-key", "sk-123", "image"]) == (
        "docker run --api-key *** image"
    )
    assert redact_command(["docker", "run", "--api-key=sk-123", "image"]) == (
        "docker run --api-key=*** image"
    )
    assert redact_command(["docker", "run", "--hf-token", "hf_123", "image"]) == (
        "docker run --hf-token *** image"
    )
    assert redact_command(["curl", "-H", "Authorization: Bearer abc"]) == (
        "curl -H Authorization: ***"
    )


def test_redact_secrets_masks_environment_assignments_but_keeps_metric_variables():
    assert redact_secrets("HF_TOKEN=hf_secret GITHUB_TOKEN=ghp_value") == (
        "HF_TOKEN=*** GITHUB_TOKEN=***"
    )
    assert redact_secrets("MAX_TOKENS=4096 NVIDIA_VISIBLE_DEVICES=all") == (
        "MAX_TOKENS=4096 NVIDIA_VISIBLE_DEVICES=all"
    )


def test_redact_command_does_not_mask_metrics_or_flags():
    assert redact_command(["tool", "--tokens", "42", "--tokenizer", "auto"]) == (
        "tool --tokens 42 --tokenizer auto"
    )


@pytest.mark.parametrize(("prefix", "expected"), [
    ("Authorization: Basic ", "Authorization: ***"),
    ("authorization=basic\t", "authorization=***"),
    ("Authorization: Bearer ", "Authorization: ***"),
])
def test_redact_authorization_masks_complete_credential(prefix, expected):
    assert redact_secrets(prefix + "dXNlcjpzeW50aGV0aWM=") == expected


@pytest.mark.parametrize("text", [
    '"Authorization": "Basic dXNlcjpzeW50aGV0aWM="',
    "'Authorization': 'Basic dXNlcjpzeW50aGV0aWM='",
    'Authorization: "Basic dXNlcjpzeW50aGV0aWM="',
    '--api-key "synthetic secret with spaces" --tokens 42',
    "--password='synthetic secret with spaces'",
    'HF_TOKEN="synthetic secret with spaces"',
])
def test_redact_quoted_secret_values(text):
    result = redact_secrets(text)
    assert "dXNlcjpzeW50aGV0aWM=" not in result
    assert "synthetic" not in result
    assert "secret with spaces" not in result


def test_redact_nested_argument_sequences_preserves_types_and_metrics():
    data = {"args": ["--api-key", "-synthetic secret", "--tokens", 42, {"password": "hidden"}],
            "tuple": ("--hf-token", "hf_secret", "--tokenizer", "auto")}
    result = redact_secrets(data)
    assert result["args"] == ["--api-key", "***", "--tokens", 42, {"password": "***"}]
    assert result["tuple"] == ("--hf-token", "***", "--tokenizer", "auto")
    assert data["args"][1] == "-synthetic secret"
    assert redact_command(["tool", "--password", "-synthetic"]) == "tool --password ***"


def test_read_json_accepts_utf8_bom(tmp_path: Path):
    path = tmp_path / ".llama-build.json"
    path.write_bytes(b"\xef\xbb\xbf{\"backend\": \"cuda\"}")
    assert read_json(path) == {"backend": "cuda"}


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
