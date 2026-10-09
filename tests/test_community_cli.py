from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path

import pytest

from llmbench.cli import main
from llmbench.community.io import export_inputs, validate_document
from llmbench.community.identity import hash_shards
from llmbench.community.project import project
from llmbench.community.schema import parse_document, serialize
import llmbench.community.settings as community_settings
from llmbench import i18n
from test_community_contract import SECRET, native_source


def write_source(tmp_path: Path, source: dict | None = None, name: str = "summary.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(source or native_source()), encoding="utf-8")
    return path


def test_preview_is_saved_exact_bytes_and_no_preview_writes(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    source = write_source(tmp_path)
    before = source.read_bytes()
    settings = tmp_path / "not-created.json"
    assert main(["community-export", str(source), "--preview", "--non-interactive", "--settings-file", str(settings)]) == 0
    preview = capsys.readouterr().out.encode()
    assert not settings.exists() and sorted(path.name for path in tmp_path.iterdir()) == ["summary.json"]
    output = tmp_path / "exports"
    assert main(["community-export", str(source), "--out", str(output), "--settings-file", str(settings)]) == 0
    saved = output / "community-run-0001.json"
    assert preview == saved.read_bytes()
    assert source.read_bytes() == before
    assert main(["community-export", str(source), "--out", str(output), "--settings-file", str(settings)]) == 1
    assert saved.read_bytes() == preview


@pytest.mark.parametrize("options", [["--preview", "--out", "exports"], ["--nickname", "u", "--no-nickname"], ["--exclude", "future"], ["--model-label", "0=x"], ["--model-label", "2=x"], ["--model-identity", "2=fingerprint"], ["--model-label", "1=x", "--model-identity", "1=fingerprint"], ["--model-label", "1=x", "--model-label", "1=y"], ["--model-label", "1=/secret/path"], ["--model-identity", "1=rehash"], ["--nickname", "\x00"]])
def test_invalid_invocation_writes_nothing(tmp_path: Path, options: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    source = write_source(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["community-export", str(source), *options, "--settings-file", str(tmp_path / "settings.json")]) == 2
    assert [path.name for path in tmp_path.iterdir()] == ["summary.json"]


def test_nickname_settings_precedence_and_clear(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = write_source(tmp_path)
    settings = tmp_path / "settings.json"
    assert main(["community-settings", "--nickname", "default-user", "--settings-file", str(settings)]) == 0
    before = settings.read_bytes()
    for flags, expected in (([], "default-user"), (["--nickname", "override-user"], "override-user"), (["--no-nickname"], None)):
        assert main(["community-export", str(path), "--preview", "--settings-file", str(settings), *flags]) == 0
        document = json.loads(capsys.readouterr().out)
        assert document.get("attribution", {}).get("nickname") == expected
        assert settings.read_bytes() == before
    assert main(["community-settings", "--show", "--settings-file", str(settings)]) == 0
    assert json.loads(capsys.readouterr().out) == {"nickname": "default-user"}
    assert main(["community-settings", "--clear-nickname", "--settings-file", str(settings)]) == 0
    assert community_settings.load(settings) is None


@pytest.mark.parametrize("raw", ['{"settings_version":true}', '{"settings_version":2}', '{"settings_version":1,"settings_version":1}', '{"settings_version":1,"nickname":123}', '{"settings_version":1,"private-secret":"value"}', '{"settings_version":1,"nickname":NaN}', '{broken'])
def test_malformed_settings_are_errors_without_sensitive_values(tmp_path: Path, raw: str) -> None:
    path = tmp_path / "settings.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(community_settings.SettingsError) as caught:
        community_settings.load(path)
    assert "private-secret" not in str(caught.value)


@pytest.mark.parametrize("value", ["a\x00b", "a\x7fb", "a\u200eb", "a/b", "a\\b", "", "x" * 65])
def test_nickname_rejects_controls_and_paths(value: str) -> None:
    with pytest.raises(community_settings.SettingsError):
        community_settings.validate_nickname(value)


def test_settings_path_platform_conventions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(community_settings.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert community_settings.settings_path() == tmp_path / "llmbench/community-settings.json"
    monkeypatch.setattr(community_settings.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert community_settings.settings_path() == tmp_path / "llmbench/community-settings.json"


def test_fingerprint_only_uses_recorded_hash_without_opening_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    path = write_source(tmp_path)
    import llmbench.community.identity_v1 as identity
    def denied(*_args: object) -> str:
        raise AssertionError("model read was not authorized")
    monkeypatch.setattr(identity, "hash_content", denied)
    assert main(["community-export", str(path), "--preview", "--model-identity", "1=fingerprint", "--settings-file", str(tmp_path / "settings.json")]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["models"][0]["identity"]["fingerprint"]["scope"] == "recorded_single_file_content"
    source = native_source()
    source["models"][0]["model"].pop("sha256")
    path = write_source(tmp_path, source)
    assert main(["community-export", str(path), "--preview", "--model-identity", "1=fingerprint", "--settings-file", str(tmp_path / "settings.json")]) == 1


def test_interactive_choice_once_per_proven_model_and_labels_not_equivalence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    first = native_source()
    second = copy.deepcopy(first)
    second["models"][0]["model"]["path"] = "/other/renamed.gguf"
    one = write_source(tmp_path, first, "one.json")
    two = write_source(tmp_path, second, "two.json")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    replies = iter(["2", "Approved model"])
    monkeypatch.setattr("builtins.input", lambda: next(replies))
    assert export_inputs([one, two], out=None, preview=True, nickname=None, excluded=set())[0] == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert all(json.loads(line)["models"][0]["identity"]["label"] == "Approved model" for line in lines)
    # Same name with different contents requires another choice.
    second["models"][0]["model"]["sha256"] = "d" * 64
    two = write_source(tmp_path, second, "two.json")
    replies = iter(["3", "3"])
    monkeypatch.setattr("builtins.input", lambda: next(replies))
    assert export_inputs([one, two], out=None, preview=True, nickname=None, excluded=set())[0] == 0
    with pytest.raises(StopIteration):
        next(replies)


def test_explicit_batch_label_propagates_by_hash_and_rehash_reads_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    artifact = tmp_path / "model.gguf"
    artifact.write_bytes(b"same content")
    source = native_source()
    source["models"][0]["model"].update(path=str(artifact), sha256=hashlib.sha256(b"same content").hexdigest())
    path = write_source(tmp_path, source)
    import llmbench.community.identity_v1 as identity
    original = identity.hash_content
    calls = []
    def counted(path: Path) -> str:
        calls.append(path)
        return original(path)
    monkeypatch.setattr(identity, "hash_content", counted)
    assert export_inputs([path, path], out=None, preview=True, nickname=None, excluded=set(), labels={1: "Chosen"}, rehash_models=True, non_interactive=True)[0] == 0
    assert calls == [artifact]
    documents = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert all(document["models"][0]["identity"]["label"] == "Chosen" for document in documents)
    assert all(document["models"][0]["identity"]["exact_identity"] == "content_fingerprinted" for document in documents)
    assert export_inputs([path, path], out=None, preview=True, nickname=None, excluded=set(), labels={2: "Second choice"}, non_interactive=True)[0] == 0
    documents = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert all(document["models"][0]["identity"]["label"] == "Second choice" for document in documents)


def test_shards_are_complete_ordered_content_only_and_legacy_hash_is_not_identity(tmp_path: Path) -> None:
    shards = [tmp_path / f"old-{i:05d}-of-00002.gguf" for i in (1, 2)]
    for i, shard in enumerate(shards):
        shard.write_bytes(bytes([i]) * (i + 1))
    expected = hash_shards(shards)
    renamed = [tmp_path / f"renamed-{i:05d}-of-00002.gguf" for i in (1, 2)]
    for old, new in zip(shards, renamed, strict=True):
        new.write_bytes(old.read_bytes())
    assert hash_shards(renamed) == expected and hash_shards(list(reversed(shards))) != expected
    source = native_source()
    source["models"][0]["model"].update(path=str(shards[1]), shard_count=2)
    historical = project(source, nickname=None, excluded=set(), labels={1: "Old split model"})
    assert historical.models[0].identity.fingerprint_status == "unavailable"
    current = project(source, nickname=None, excluded=set(), rehash_models=True)
    identity = current.models[0].identity
    assert identity.fingerprint.algorithm == "sha256-shards-v1" and identity.fingerprint.value == expected
    assert identity.exact_identity == "unverified"
    shards[0].unlink()
    with pytest.raises(ValueError, match="incomplete_shards"):
        project(source, nickname=None, excluded=set(), rehash_models=True)


def test_validate_is_offline_and_does_not_hash_or_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "community.json"
    path.write_bytes(serialize(project(native_source(), nickname=None, excluded=set())))
    import socket
    import subprocess
    import llmbench.community.identity_v1 as identity
    def denied(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("offline boundary violated")
    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(subprocess, "run", denied)
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(identity, "hash_content", denied)
    validate_document(path)


def test_unknown_dictionary_key_and_cli_validation_error_are_safe(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    data = json.loads(serialize(project(native_source(), nickname=None, excluded=set())))
    data["models"][0]["profiles"][0][SECRET] = {SECRET: SECRET}
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert main(["community-validate", str(path)]) == 1
    error = capsys.readouterr().err
    assert SECRET not in error and "models[0].profiles[0]" in error
    with pytest.raises(ValueError):
        parse_document('{"export_schema_version":1,"export_schema_version":1}')


def test_configuration_fingerprint_depends_on_settings_not_identity_or_metrics() -> None:
    source = native_source()
    first = project(source, nickname=None, excluded=set())
    source["models"][0]["profiles"][0]["benchmarks"]["prompt"]["rows"][0]["avg_ts"]["value"] = 75.
    second = project(source, nickname="different", excluded={"hardware"}, labels={1: "Different label"})
    assert first.benchmark_configuration.fingerprint == second.benchmark_configuration.fingerprint
    source["models"][0]["profiles"][0]["settings"]["threads"] = 8
    third = project(source, nickname=None, excluded=set())
    assert first.benchmark_configuration.fingerprint != third.benchmark_configuration.fingerprint


def test_cli_human_text_is_available_in_both_languages(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = write_source(tmp_path)
    old = i18n.current_language()
    try:
        for language, expected in (("de", "erfolgreich"), ("en", "succeeded")):
            i18n.set_language(language)
            assert main(["community-export", str(path), "--preview", "--settings-file", str(tmp_path / "none.json")]) == 0
            assert expected in capsys.readouterr().err
    finally:
        i18n.set_language(old)
