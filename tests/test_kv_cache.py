from __future__ import annotations

import json

from llmbench.backends.llama_cpp import LlamaCppBackend, parse_llama_kv_cache_output
from llmbench.backends.vllm import parse_vllm_cache_metrics
from llmbench.kv_cache import KvCacheObservation, normalize_kv_cache
from llmbench.result_schema import ResultSchemaError, encode_v3, validate_summary


def test_normalizer_keeps_requested_values_out_and_marks_missing_fields() -> None:
    data = normalize_kv_cache("vllm", [
        KvCacheObservation("prefix_caching", True, provider="vllm"),
        {"field": "kv_dtype", "value": "auto", "source": "requested"},
    ])

    assert data["prefix_caching"]["value"] is True
    assert data["kv_dtype"]["status"] == "unknown"
    assert data["k_dtype"]["status"] == "unavailable"


def test_normalizer_preserves_conflicting_runtime_evidence() -> None:
    data = normalize_kv_cache("vllm", [
        KvCacheObservation("token_capacity", 1024, unit="tokens", provider="vllm", phase="startup"),
        KvCacheObservation("token_capacity", 2048, unit="tokens", provider="vllm", phase="benchmark"),
    ])

    item = data["token_capacity"]
    assert item["status"] == "unknown"
    assert item["reason"] == "conflicting_runtime_observations"
    assert [entry["value"] for entry in item["evidence"]["metadata"]["observations"]] == [1024, 2048]


def test_normalizer_sanitizes_conflict_evidence() -> None:
    data = normalize_kv_cache("vllm", [
        KvCacheObservation("token_capacity", 1, unit="tokens", provider="/private/token=abc", phase="startup"),
        KvCacheObservation("token_capacity", 2, unit="tokens", provider="vllm", phase="benchmark"),
    ])
    evidence = data["token_capacity"]["evidence"]
    assert evidence["method"] == "backend_runtime_introspection"
    assert "private" not in repr(evidence).lower()
    assert "abc" not in repr(evidence).lower()


def test_vllm_metrics_does_not_resolve_auto_dtype_and_handles_escaped_labels() -> None:
    observations = parse_vllm_cache_metrics(
        'vllm:cache_config_info{cache_dtype="auto",enable_prefix_caching="True",gpu_memory_utilization="0.9",note="a,\\"b\\""} 1\n'
    )

    values = {item.field: item.value for item in observations}
    assert "kv_dtype" not in values
    assert values == {"prefix_caching": True, "executor_gpu_memory_budget_fraction": 0.9}
    budget = next(item for item in observations if item.field == "executor_gpu_memory_budget_fraction")
    assert budget.backend_detail_key == "executor_gpu_memory_budget_fraction"


def test_llama_json_parser_only_uses_captured_output() -> None:
    observations = parse_llama_kv_cache_output(
        '[{"type_k":"q8_0","type_v":"f16","build_commit":"abc123"}]', "-ctk f16 -ctv f16 -c 999999"
    )
    values = {(item.field, item.value) for item in observations}

    assert ("k_dtype", "q8_0") in values
    assert ("v_dtype", "f16") in values
    assert ("runtime_version", "abc123") in values
    assert not any(field == "effective_max_context" for field, _value in values)


def test_llama_build_identity_uses_commit_as_common_and_number_as_detail() -> None:
    observations = parse_llama_kv_cache_output('[{"build_commit":"abc123","build_number":456}]', "")
    data = normalize_kv_cache("llama_cpp", observations)
    assert data["runtime_version"]["value"] == "abc123"
    detail = data["backend_details"]["llama_cpp"]["build_number"]
    assert detail["value"] == 456
    assert detail["source"] == "detected"
    assert detail["evidence"]["method"] == "backend_log_parsing"


def test_llama_build_number_alone_does_not_invent_runtime_version() -> None:
    data = normalize_kv_cache("llama_cpp", parse_llama_kv_cache_output('[{"build_number":456}]', ""))
    assert data["runtime_version"]["status"] == "unknown"
    assert data["backend_details"]["llama_cpp"]["build_number"]["value"] == 456


def test_vllm_native_details_are_not_common_comparisons() -> None:
    from llmbench.backends.vllm import parse_vllm_cache_logs

    observations = [
        *parse_vllm_cache_metrics('vllm:cache_config_info{gpu_memory_utilization="0.9"} 1\n'),
        *parse_vllm_cache_logs("GPU KV cache size: 12,345 tokens"),
    ]
    data = normalize_kv_cache("vllm", observations)
    details = data["backend_details"]["vllm"]
    assert details["gpu_kv_cache_size_tokens"]["value"] == 12345
    assert details["gpu_kv_cache_size_tokens"]["unit"] == "tokens"
    assert details["executor_gpu_memory_budget_fraction"]["value"] == 0.9
    assert details["executor_gpu_memory_budget_fraction"]["unit"] == "fraction"
    assert data["token_capacity"]["status"] == "unavailable"
    assert data["memory_budget_fraction"]["status"] == "unavailable"


def test_detail_validation_accepts_required_key_and_rejects_invalid_identifier() -> None:
    summary = {
        "schema_version": 2, "backend": "vllm", "hardware": {"cpu": {"physical_cores": 4}},
        "models": [{"model": {"name": "M"}, "profiles": [{
            "name": "P", "settings": {}, "benchmarks": {},
            "kv_cache": normalize_kv_cache("vllm", [
                KvCacheObservation("gpu_kv_cache_size_tokens", 12, unit="tokens", backend_detail_key="gpu_kv_cache_size_tokens"),
            ]),
        }]}],
    }
    encoded = encode_v3(summary)
    validate_summary(encoded)
    encoded["models"][0]["profiles"][0]["kv_cache"]["backend_details"]["vllm"]["bad-key"] = {"value": 1, "source": "detected"}
    try:
        validate_summary(encoded)
    except ResultSchemaError as exc:
        assert "bounded identifiers" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("invalid detail key was accepted")


def test_start_failure_suppresses_backend_details() -> None:
    data = normalize_kv_cache("vllm", [
        KvCacheObservation("gpu_kv_cache_size_tokens", 12, unit="tokens", backend_detail_key="gpu_kv_cache_size_tokens"),
    ], start_failed=True)
    assert "backend_details" not in data


def test_schema_v3_validates_the_complete_kv_core_without_a_v4() -> None:
    summary = {
        "schema_version": 2, "backend": "vllm", "hardware": {"cpu": {"physical_cores": 4}},
        "models": [{"model": {"name": "M"}, "profiles": [{
            "name": "P", "settings": {}, "benchmarks": {},
            "kv_cache": normalize_kv_cache("vllm", []),
        }]}],
    }
    encoded = encode_v3(summary)
    assert encoded["schema_version"] == 3
    validate_summary(encoded)
    encoded["models"][0]["profiles"][0]["kv_cache"]["kv_dtype"] = {
        "value": "fp8", "source": "requested",
    }
    try:
        validate_summary(encoded)
    except ResultSchemaError as exc:
        assert "effective KV-cache" in str(exc)
    else:  # pragma: no cover - documents the prohibited source invariant
        raise AssertionError("requested KV dtype was accepted")


def test_llama_collection_uses_only_artifacts_recorded_for_current_profile(tmp_path) -> None:
    current = tmp_path / "current"
    current.mkdir()
    stale = current / "raw_prompt.json"
    stale.write_text(json.dumps({"stdout": '[{"type_k":"stale"}]', "stderr": ""}), encoding="utf-8")
    fresh = current / "raw_generation.json"
    fresh.write_text(json.dumps({"stdout": '[{"type_k":"q8_0"}]', "stderr": ""}), encoding="utf-8")

    backend = LlamaCppBackend("llama-bench", "llama-server")
    backend._kv_artifacts = {fresh}
    observed = backend.collect_kv_cache_observations("m.gguf", {}, {}, current, "benchmark")

    assert [(item.field, item.value) for item in observed] == [("k_dtype", "q8_0")]
