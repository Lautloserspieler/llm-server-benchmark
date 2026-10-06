import copy

import pytest

from llmbench.result_schema import ResultSchemaError, encode_v3, envelope, scalar_summary, validate_envelope, validate_summary


def _summary() -> dict:
    return {
        "schema_version": 2,
        "backend": "llama_cpp",
        "hardware": {"cpu": {"physical_cores": 4}},
        "models": [{"model": {"name": "M"}, "profiles": [{"name": "GPU", "settings": {"gpu_layers": -1}, "benchmarks": {
            "generation": {"status": "partial", "rows": [{"avg_ts": 0.0}, {"avg_ts": None}]}
        }}]}],
    }


def test_encode_v3_keeps_raw_summary_and_wraps_reference_values():
    raw = _summary()
    original = copy.deepcopy(raw)
    result = encode_v3(raw, {("M", "GPU"): "requested"})

    assert raw == original
    assert result["schema_version"] == 3
    assert result["backend"] == {"id": "llama_cpp", "name": "llama.cpp", "config": {}}
    assert result["hardware"]["cpu"]["physical_cores"] == {
        "value": 4, "source": "detected", "unit": "cores", "evidence": {"method": "hardware_introspection"},
    }
    layers = result["models"][0]["profiles"][0]["settings"]["gpu_layers"]
    assert layers["source"] == "requested" and layers["unit"] == "layers"
    rows = result["models"][0]["profiles"][0]["benchmarks"]["generation"]["rows"]
    assert rows[0]["avg_ts"]["value"] == 0.0
    assert rows[0]["avg_ts"]["source"] == "measured"
    assert rows[1]["avg_ts"]["status"] == "unavailable"


def test_projection_is_reusable_and_keeps_scalar_computations_safe():
    projected = scalar_summary(encode_v3(_summary()))
    assert projected["backend"] == "llama_cpp"
    assert projected["models"][0]["profiles"][0]["settings"]["gpu_layers"] == -1
    assert projected["models"][0]["profiles"][0]["benchmarks"]["generation"]["rows"][0]["avg_ts"] == 0.0
    assert scalar_summary(projected) == projected


def test_projection_marker_cannot_bypass_external_v3_validation():
    result = encode_v3(_summary())
    result["_scalar_projection"] = True
    result["backend"] = "not-a-v3-descriptor"
    with pytest.raises(ResultSchemaError, match="backend"):
        scalar_summary(result)


@pytest.mark.parametrize("source", ["trusted", [], True])
def test_v3_rejects_invalid_source_with_field_path(source):
    result = encode_v3(_summary())
    result["models"][0]["profiles"][0]["settings"]["gpu_layers"]["source"] = source
    with pytest.raises(ResultSchemaError, match="gpu_layers"):
        validate_summary(result)


@pytest.mark.parametrize("source", ["requested", "defaulted", "detected", "calculated", "measured", "verified"])
def test_all_documented_sources_are_valid(source):
    item = envelope(1, source, unit="tokens", evidence={"method": "custom:example/procedure", "provider": "test", "extra": {"kept": True}})
    validate_envelope(item, "example", kind="integer", unit="tokens")
    assert item["evidence"]["extra"] == {"kept": True}


def test_boolean_and_nonfinite_values_follow_strict_field_types():
    validate_envelope(envelope(False, "detected"), "flag", kind="boolean")
    with pytest.raises(ResultSchemaError, match="integer"):
        validate_envelope(envelope(False, "detected", unit="tokens"), "count", kind="integer", unit="tokens")
    with pytest.raises(ResultSchemaError, match="finite"):
        validate_envelope(envelope(float("inf"), "measured", unit="tokens/s"), "rate", kind="number", unit="tokens/s")


def test_v3_rejects_wrong_unit_and_future_or_malformed_version():
    result = encode_v3(_summary())
    result["hardware"]["cpu"]["physical_cores"]["unit"] = "bytes"
    with pytest.raises(ResultSchemaError, match="physical_cores"):
        validate_summary(result)
    with pytest.raises(ResultSchemaError, match="update llmbench"):
        validate_summary({"schema_version": 4})
    with pytest.raises(ResultSchemaError, match="expected an integer"):
        validate_summary({"schema_version": "3"})


def test_v3_requires_backend_config_and_positive_physical_cores():
    result = encode_v3(_summary())
    del result["backend"]["config"]
    with pytest.raises(ResultSchemaError, match="backend.config"):
        validate_summary(result)
    result = encode_v3(_summary())
    result["hardware"]["cpu"]["physical_cores"]["value"] = 0
    with pytest.raises(ResultSchemaError, match="physical_cores"):
        validate_summary(result)


def test_unknown_null_is_valid_but_unavailable_known_value_is_not():
    result = encode_v3(_summary())
    layers = result["models"][0]["profiles"][0]["settings"]["gpu_layers"]
    layers.update({"value": None, "source": None, "status": "unknown", "reason": "not_collected"})
    validate_summary(result)
    layers.update({"value": 0, "status": "unavailable", "reason": "backend_not_exposed"})
    with pytest.raises(ResultSchemaError, match="unavailable"):
        validate_summary(result)
    layers.update({"value": None, "source": "measured", "status": None, "reason": None})
    with pytest.raises(ResultSchemaError, match="null value"):
        validate_summary(result)


def test_v2_remains_readable_without_rewriting_or_inventing_provenance():
    legacy = _summary()
    assert scalar_summary(legacy)["schema_version"] == 2
    assert legacy["models"][0]["profiles"][0]["settings"]["gpu_layers"] == -1


def test_vllm_keeps_unmigrated_throughput_scalar_and_valid():
    legacy = _summary()
    legacy["backend"] = "vllm"
    result = encode_v3(legacy)
    assert result["models"][0]["profiles"][0]["benchmarks"]["generation"]["rows"][0]["avg_ts"] == 0.0
    validate_summary(result)
