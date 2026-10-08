import copy

import pytest

from llmbench.result_schema import ResultSchemaError, encode_v3, envelope, scalar_summary, validate_envelope, validate_summary
from llmbench.kv_cache import KvCacheObservation, normalize_kv_cache


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


def test_encode_v3_preserves_bound_auto_tune_calculation_evidence():
    result = encode_v3(_summary(), {("M", "GPU"): {
        "source": "calculated",
        "evidence": {
            "method": "derived_calculation",
            "provider": "llmbench",
            "metadata": {"selected_gpu_layers": -1, "selected_tps": 42.5, "successful_candidates": 3},
        },
    }})
    layers = result["models"][0]["profiles"][0]["settings"]["gpu_layers"]
    assert layers["source"] == "calculated"
    assert layers["evidence"]["metadata"]["selected_tps"] == 42.5


def test_encode_v3_rejects_unbound_auto_tune_calculation_as_unknown():
    result = encode_v3(_summary(), {("M", "GPU"): {
        "source": "calculated",
        "evidence": {
            "method": "derived_calculation", "provider": "llmbench",
            "metadata": {"selected_gpu_layers": 1},
        },
    }})
    layers = result["models"][0]["profiles"][0]["settings"]["gpu_layers"]
    assert layers["source"] is None
    assert layers["reason"] == "invalid_calculation_origin"


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


def test_v3_accepts_memory_domains_and_runtime_bandwidth_provenance():
    result = encode_v3(_summary())
    result["hardware"]["memory_domains"] = [{
        "id": "apple:unified:0", "kind": "unified_memory", "vendor": "Apple",
        "bandwidth": {
            "theoretical": envelope(410, "detected", unit="GB/s", evidence={"method": "hardware_introspection"}),
        },
    }]
    result["telemetry"] = {"memory_bandwidth": [{
        "domain_id": "apple:unified:0", "method": "mactop_headless_json", "scope": "system_soc_dram",
        "observed_during_benchmark": envelope(120.0, "measured", unit="GB/s", evidence={"method": "benchmark_measurement"}),
    }]}
    validate_summary(result)
    projected = scalar_summary(result)
    assert projected["hardware"]["memory_domains"][0]["bandwidth"]["theoretical"] == 410


def test_v3_rejects_non_positive_bandwidth_and_unknown_domain_reference():
    result = encode_v3(_summary())
    result["hardware"]["memory_domains"] = [{
        "id": "gpu:0", "kind": "discrete_vram", "vendor": "NVIDIA",
        "bandwidth": {"theoretical": envelope(0, "detected", unit="GB/s")},
    }]
    with pytest.raises(ResultSchemaError, match="positive"):
        validate_summary(result)
    result["hardware"]["memory_domains"][0]["bandwidth"]["theoretical"] = envelope(1, "detected", unit="GB/s")
    result["telemetry"] = {
        "memory_bandwidth": [{
            "domain_id": "missing",
            "observed_during_benchmark": envelope(1, "measured", unit="GB/s"),
        }],
    }
    with pytest.raises(ResultSchemaError, match="unknown memory domain"):
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

def test_v3_context_capability_uses_verified_provenance_and_projects_to_scalar():
    raw = _summary()
    raw["models"][0]["profiles"][0]["context_capability"] = {
        "maximum_verified_context": 131072,
        "completed_context_depths": [0, 131072],
        "requested_context_depths": [0, 131072, 262144],
        "first_failed_context": 262144,
        "limit_status": "skipped_capacity",
        "curve": [
            {
                "populated_context": 131072,
                "prefill_tps": 1200.0,
                "decode_tps": 55.0,
                "combined_tps": None,
                "result": "pass",
            },
            {
                "populated_context": 262144,
                "prefill_tps": None,
                "decode_tps": None,
                "combined_tps": None,
                "result": "oom",
            },
        ],
    }

    encoded = encode_v3(raw)
    maximum = encoded["models"][0]["profiles"][0]["context_capability"]["maximum_verified_context"]
    assert maximum == {
        "value": 131072,
        "source": "verified",
        "unit": "tokens",
        "evidence": {"method": "experimental_validation"},
    }
    validate_summary(encoded)

    projected = scalar_summary(encoded)
    assert projected["models"][0]["profiles"][0]["context_capability"]["maximum_verified_context"] == 131072


def test_v3_context_curve_rejects_negative_depth():
    raw = _summary()
    raw["models"][0]["profiles"][0]["context_capability"] = {
        "maximum_verified_context": 0,
        "completed_context_depths": [0],
        "requested_context_depths": [0],
        "first_failed_context": None,
        "limit_status": None,
        "curve": [{
            "populated_context": -1,
            "prefill_tps": 1.0,
            "decode_tps": 1.0,
            "combined_tps": None,
            "result": "pass",
        }],
    }
    with pytest.raises(ResultSchemaError, match="populated_context"):
        encode_v3(raw)



def test_v3_energy_and_efficiency_metrics_preserve_measurement_scope_and_provenance():
    raw = _summary()
    benchmark = raw["models"][0]["profiles"][0]["benchmarks"]["generation"]
    benchmark["status"] = "ok"
    benchmark["telemetry"] = {
        "telemetry_source": "nvml",
        "cpu_telemetry_source": "psutil+powercap",
        "cpu": {
            "avg_package_power_w": 100.0,
            "max_package_power_w": 125.0,
            "energy_j": 200.0,
            "energy_wh": 200.0 / 3600.0,
            "energy_source": "hardware_energy_counter",
        },
        "gpus": [{
            "index": 0,
            "energy_j": 800.0,
            "energy_wh": 800.0 / 3600.0,
            "energy_source": "sampled_power_integration",
        }],
        "power": {
            "scope": "measured_components",
            "coverage": ["cpu_package", "gpu:0"],
            "avg_component_power_w": 500.0,
            "max_component_power_w": 600.0,
            "component_energy_j": 1000.0,
            "component_energy_wh": 1000.0 / 3600.0,
            "wall_power_w": None,
            "wall_energy_j": None,
            "wall_energy_wh": None,
        },
    }
    benchmark["efficiency"] = {
        "power_scope": "measured_components",
        "power_coverage": ["cpu_package", "gpu:0"],
        "token_scope": "generated_tokens",
        "workload_tokens": 512,
        "tokens_per_joule": 0.512,
        "joules_per_1k_tokens": 1953.125,
        "wh_per_1k_tokens": 1953.125 / 3600.0,
    }

    encoded = encode_v3(raw)
    encoded_benchmark = encoded["models"][0]["profiles"][0]["benchmarks"]["generation"]

    cpu = encoded_benchmark["telemetry"]["cpu"]
    assert cpu["energy_j"]["source"] == "measured"
    assert cpu["energy_j"]["evidence"]["method"] == "hardware_energy_counter"

    gpu = encoded_benchmark["telemetry"]["gpus"][0]
    assert gpu["energy_j"]["source"] == "calculated"

    power = encoded_benchmark["telemetry"]["power"]
    assert power["component_energy_j"]["source"] == "calculated"
    assert power["component_energy_j"]["evidence"]["metadata"]["scope"] == "measured_components"
    assert power["wall_power_w"]["status"] == "unavailable"

    efficiency = encoded_benchmark["efficiency"]
    assert efficiency["tokens_per_joule"]["source"] == "calculated"
    assert efficiency["tokens_per_joule"]["unit"] == "tokens/J"

    validate_summary(encoded)
    projected = scalar_summary(encoded)
    projected_benchmark = projected["models"][0]["profiles"][0]["benchmarks"]["generation"]
    assert projected_benchmark["telemetry"]["power"]["component_energy_j"] == 1000.0
    assert projected_benchmark["efficiency"]["tokens_per_joule"] == 0.512


def test_v3_combines_energy_efficiency_and_native_kv_details_without_projection_leaks():
    raw = _summary()
    profile = raw["models"][0]["profiles"][0]
    profile["kv_cache"] = normalize_kv_cache("vllm", [
        KvCacheObservation("gpu_kv_cache_size_tokens", 8192, unit="tokens", backend_detail_key="gpu_kv_cache_size_tokens"),
    ])
    benchmark = profile["benchmarks"]["generation"]
    benchmark.update({
        "status": "ok",
        "telemetry": {"power": {"scope": "measured_components", "coverage": ["gpu:0"], "component_energy_j": 100.0}},
        "efficiency": {
            "power_scope": "measured_components", "power_coverage": ["gpu:0"],
            "token_scope": "generated_tokens", "workload_tokens": 128,
            "tokens_per_joule": 1.28, "joules_per_1k_tokens": 781.25,
            "wh_per_1k_tokens": 781.25 / 3600.0,
        },
    })
    original = copy.deepcopy(raw)
    encoded = encode_v3(raw)
    assert raw == original
    assert encoded["models"][0]["profiles"][0]["kv_cache"]["backend_details"]["vllm"]["gpu_kv_cache_size_tokens"]["value"] == 8192
    assert encoded["models"][0]["profiles"][0]["benchmarks"]["generation"]["efficiency"]["tokens_per_joule"]["source"] == "calculated"
    assert encode_v3(encoded) == encoded
    projected = scalar_summary(encoded)
    assert projected["models"][0]["profiles"][0]["benchmarks"]["generation"]["telemetry"]["power"]["component_energy_j"] == 100.0
    assert projected["models"][0]["profiles"][0]["kv_cache"]["backend_details"]["vllm"]["gpu_kv_cache_size_tokens"] == 8192


def test_v3_efficiency_rejects_wall_power_claim_disguised_as_component_scope():
    raw = _summary()
    benchmark = raw["models"][0]["profiles"][0]["benchmarks"]["generation"]
    benchmark["efficiency"] = {
        "power_scope": "wall_power",
        "power_coverage": [],
        "token_scope": "generated_tokens",
        "workload_tokens": 128,
        "tokens_per_joule": 1.0,
        "joules_per_1k_tokens": 1000.0,
        "wh_per_1k_tokens": 1000.0 / 3600.0,
    }

    with pytest.raises(ResultSchemaError, match="power_scope"):
        encode_v3(raw)
