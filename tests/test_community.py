from __future__ import annotations

import json
from pathlib import Path

from llmbench.community.io import CommunityError, export_inputs, read_summary, resolve_summary, validate_document
from llmbench.community.project import project
from llmbench.community.schema import serialize
from llmbench.community.settings import load, save
from llmbench.result_schema import encode_v3


def _summary() -> dict:
    return encode_v3({"schema_version": 2, "llmbench_version": "1.6.0", "backend": "llama_cpp", "started_at": "2026-10-09T10:00:00+00:00", "finished_at": "2026-10-09T10:01:00+00:00", "server_name": "secret-host", "models": [{"model": {"name": "/private/model.gguf", "path": "/private/model.gguf", "sha256": "a" * 64, "size_bytes": 123}, "profiles": [{"settings": {"gpu_layers": -1, "threads": 4}, "benchmarks": {"prompt": {"rows": [{"n_prompt": 128, "avg_ts": 42.0, "status": "ok", "error": "password=bad"}]}}, "context_capability": {"requested_context_depths": [128], "completed_context_depths": [128], "curve": [{"populated_context": 128, "prefill_tps": 42.0, "result": "pass"}]}}]}]})


def test_projection_drops_local_identifiers_and_serializes_deterministically() -> None:
    payload = serialize(project(_summary(), nickname="bench-user", excluded=set()))
    assert b"secret-host" not in payload and b"private/model" not in payload and b"password" not in payload
    assert payload.endswith(b"\n")


def test_validate_rejects_unknown_top_level_field(tmp_path: Path) -> None:
    path = tmp_path / "candidate.json"
    data = json.loads(serialize(project(_summary(), nickname=None, excluded=set())))
    data["private_token"] = "secret"
    path.write_text(json.dumps(data), encoding="utf-8")
    try:
        validate_document(path)
    except ValueError:
        pass
    else:
        raise AssertionError("unknown fields must be rejected")


def test_explicit_rehash_is_current_artifact_not_historical_identity(tmp_path: Path) -> None:
    model = tmp_path / "model.gguf"
    model.write_bytes(b"current content")
    summary = _summary()
    metadata = summary["models"][0]["model"]
    metadata.pop("sha256")
    metadata["path"] = str(model)
    document = project(summary, nickname=None, excluded=set(), rehash_models=True)
    identity = document.models[0].identity
    assert identity.exact_identity == "unverified"
    assert identity.fingerprint is not None
    assert identity.fingerprint.scope == "current_artifact_unverified"


def test_every_optional_group_combination_is_valid_and_has_no_secret() -> None:
    """Exclusions are policy switches, not a route around structural validation."""
    import itertools

    source = _summary()
    source["hardware"] = {"os": "Linux 6.0 private-host", "cpu": {"name": "CPU", "physical_cores": {"value": 4, "source": "detected", "unit": "cores"}}}
    source["telemetry"] = {"cpu": {"avg_util_percent": 12.0, "energy_j": {"value": 4.0, "source": "measured", "unit": "J", "reason": "metered"}}, "gpus": [{"foreign_gpu_processes": [{"pid": 7, "name": "secret-process"}]}]}
    groups = ("hardware", "energy", "capabilities", "telemetry")
    for size in range(len(groups) + 1):
        for selected in itertools.combinations(groups, size):
            payload = serialize(project(source, nickname=None, excluded=set(selected)))
            assert b"private-host" not in payload
            assert b"secret-process" not in payload
            document = json.loads(payload)
            assert document["omitted_groups"] == sorted(selected)


def test_strict_parser_hides_nested_secret_and_rejects_duplicate_nonfinite(tmp_path: Path) -> None:
    payload = serialize(project(_summary(), nickname=None, excluded=set())).decode()
    crafted = json.loads(payload)
    crafted["models"][0]["identity"]["label"] = "secret/path"
    crafted["models"][0]["identity"]["evidence"] = {"token": "do-not-print"}
    path = tmp_path / "crafted.json"
    path.write_text(json.dumps(crafted), encoding="utf-8")
    try:
        validate_document(path)
    except ValueError as exc:
        assert "do-not-print" not in str(exc)
        assert "token" not in str(exc)
    else:
        raise AssertionError("crafted nested secret must be rejected")
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"export_schema_version":1,"export_schema_version":1}', encoding="utf-8")
    try:
        validate_document(duplicate)
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate keys must be rejected")
    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"value":NaN}', encoding="utf-8")
    try:
        validate_document(nonfinite)
    except ValueError:
        pass
    else:
        raise AssertionError("non-finite JSON must be rejected")


def test_final_artifact_is_never_replaced_by_partial_after_corruption(tmp_path: Path) -> None:
    (tmp_path / "summary.json").write_text("{broken", encoding="utf-8")
    (tmp_path / "summary.partial.json").write_text(json.dumps(_summary()), encoding="utf-8")
    assert resolve_summary(tmp_path).name == "summary.json"
    try:
        read_summary(resolve_summary(tmp_path))
    except CommunityError:
        pass
    else:
        raise AssertionError("corrupt final must not fall back to partial")


def test_batch_keeps_valid_output_when_later_input_is_bad(tmp_path: Path) -> None:
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_summary()), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text("{broken", encoding="utf-8")
    output = tmp_path / "exports"
    code, messages = export_inputs([good, bad], out=output, preview=False, nickname=None, excluded=set())
    assert code == 1
    assert (output / "community-run-0001.json").exists()
    from llmbench.i18n import _
    assert _("Community-Export: {successes} erfolgreich, {failures} fehlgeschlagen").format(successes=1, failures=1) in messages


def test_exclusions_remove_their_metrics_but_keep_unrelated_measurements() -> None:
    source = _summary()
    source["hardware"] = {"os": "Linux 6", "memory_domains": [{"id": "private-domain", "vendor": "NVIDIA", "kind": "dram", "bandwidth": {"theoretical": {"value": 1.0, "source": "calculated", "unit": "GB/s"}}}]}
    profile = source["models"][0]["profiles"][0]
    from llmbench.kv_cache import empty_kv_cache
    profile["kv_cache"] = empty_kv_cache("llama_cpp")
    profile["kv_cache"]["token_capacity"] = {"value": 512, "source": "detected", "unit": "tokens"}
    profile["benchmarks"]["prompt"]["efficiency"] = {"power_scope": "measured_components", "token_scope": "prompt_tokens", "power_coverage": ["cpu_package"], **{key: {"value": 2 if key == "workload_tokens" else 2.0, "source": "calculated", "unit": unit} for key, unit in (("workload_tokens", "tokens"), ("tokens_per_joule", "tokens/J"), ("joules_per_1k_tokens", "J/1k tokens"), ("wh_per_1k_tokens", "Wh/1k tokens"))}}
    profile["benchmarks"]["prompt"]["telemetry"] = {"cpu": {"energy_j": {"value": 9.0, "source": "measured", "unit": "J"}}}
    energy = json.loads(serialize(project(source, nickname=None, excluded={"energy"})))
    text = json.dumps(energy)
    assert "efficiency" not in text and "energy_j" not in text and "token_capacity" in text
    capabilities = json.loads(serialize(project(source, nickname=None, excluded={"capabilities"})))
    text = json.dumps(capabilities)
    assert "kv_cache" not in text and "context_capability" not in text and "n_prompt" in text
    telemetry = json.loads(serialize(project(source, nickname=None, excluded={"telemetry"})))
    prompt = telemetry["models"][0]["profiles"][0]["benchmarks"]["prompt"]
    assert "efficiency" in prompt and "energy_j" in prompt["telemetry"]["cpu"]
    hardware = json.loads(serialize(project(source, nickname=None, excluded={"hardware"})))
    assert "hardware" not in hardware and "models" in hardware


def test_settings_are_explicit_and_preview_does_not_write_settings(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    save("bench-user", settings)
    assert load(settings) == "bench-user"
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps(_summary()), encoding="utf-8")
    before = settings.read_bytes()
    code, _ = export_inputs([summary], out=None, preview=True, nickname=load(settings), excluded=set())
    assert code == 0 and settings.read_bytes() == before


def test_projection_is_offline_without_subprocess_or_socket(monkeypatch: object) -> None:
    import socket
    import subprocess

    def denied(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("offline boundary violated")

    monkeypatch.setattr(socket, "socket", denied)  # type: ignore[attr-defined]
    monkeypatch.setattr(subprocess, "run", denied)  # type: ignore[attr-defined]
    project(_summary(), nickname=None, excluded=set())


def test_multimodel_noninteractive_requires_each_unidentified_model(tmp_path: Path) -> None:
    source = _summary()
    second = json.loads(json.dumps(source["models"][0]))
    second["model"].pop("sha256")
    second["model"]["path"] = str(tmp_path / "other.gguf")
    source["models"].append(second)
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    code, messages = export_inputs([path], out=tmp_path / "out", preview=False, nickname=None, excluded=set(), non_interactive=True)
    assert code == 1 and any("missing_approved_identity" in message for message in messages)


def test_selected_fingerprint_rehashes_only_selected_model(tmp_path: Path) -> None:
    artifact = tmp_path / "model.gguf"
    artifact.write_bytes(b"identity")
    source = _summary()
    source["models"][0]["model"].pop("sha256")
    source["models"][0]["model"]["path"] = str(artifact)
    document = project(source, nickname=None, excluded=set(), rehash_positions={1})
    assert document.models[0].identity.fingerprint is not None
