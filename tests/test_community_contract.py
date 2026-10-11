"""Native suite fixtures and behavioral contract/privacy regressions."""
from __future__ import annotations
import copy
import json
from pathlib import Path

import pytest

from llmbench.community import policy
from llmbench.community.io import schema_text
from llmbench.community.project import project
from llmbench.community.schema import SafeError, parse_document, serialize
from llmbench.kv_cache import KvCacheObservation, normalize_kv_cache
from llmbench.result_schema import encode_v3, validate_summary

SECRET = "PRIVATE_SENTINEL-password-host-path-192.168.10.10"


def native_source(backend: str = "llama_cpp") -> dict:
    telemetry = {"sample_count": 10, "sample_interval_seconds": .5, "avg_cpu_percent": 12., "max_cpu_percent": 15., "avg_ram_bytes": 100, "max_ram_bytes": 200,
                 "cpu": {"avg_util_percent": 12., "max_util_percent": 20., "avg_frequency_mhz": 3000., "min_frequency_mhz": 2000., "max_frequency_mhz": 4000., "avg_temperature_c": 40., "max_temperature_c": 50., "avg_package_power_w": 5., "max_package_power_w": 10., "energy_j": 25., "energy_wh": 25 / 3600, "energy_source": "hardware_energy_counter", "energy_coverage_seconds": 5.},
                 "gpus": [{"index": 7, "avg_util_gpu_percent": 70., "max_util_gpu_percent": 90., "avg_memory_used_bytes": 200, "max_memory_used_bytes": 300, "memory_total_bytes": 4096, "avg_power_w": 30., "max_power_w": 40., "max_temperature_c": 60., "energy_j": 150., "energy_wh": 150 / 3600, "energy_source": "sampled_power_integration", "energy_coverage_seconds": 5., "foreign_gpu_processes": [{"pid": 123, "name": SECRET}]}],
                 "power": {"scope": "measured_components", "coverage": ["cpu_package", "gpu_7"], "avg_component_power_w": 35., "max_component_power_w": 50., "component_energy_j": 175., "component_energy_wh": 175 / 3600, "wall_power_w": None, "wall_energy_j": None, "wall_energy_wh": None},
                 "baseline": {"cpu_percent": 20., "processes": [{"name": SECRET}]}, "samples": [{"secret": SECRET}], "processes": [{"name": SECRET}], "future": SECRET}
    efficiency = {"power_scope": "measured_components", "token_scope": "prompt_tokens", "power_coverage": ["cpu_package", "gpu_7"], "workload_tokens": 128, "tokens_per_joule": 128 / 175, "joules_per_1k_tokens": 175 / 128 * 1000, "wh_per_1k_tokens": 175 / 128 / 3.6}
    kv = normalize_kv_cache(backend, [KvCacheObservation("effective_max_context", 4096, unit="tokens"), KvCacheObservation("runtime_version", "0.10.2"), KvCacheObservation("residency", "gpu"), KvCacheObservation("memory_budget_fraction", .9, unit="fraction"), KvCacheObservation("build_number" if backend == "llama_cpp" else "gpu_kv_cache_size_tokens", 1234, unit=None if backend == "llama_cpp" else "tokens", backend_detail_key="build_number" if backend == "llama_cpp" else "gpu_kv_cache_size_tokens")])
    source = {"schema_version": 2, "backend": backend, "llmbench_version": "1.6.0", "server_name": SECRET, "started_at": "2026-10-09T06:00:00-04:00", "finished_at": "2026-10-09T06:05:00-04:00", "hardware_target": "both", "status": "completed",
              "config": {"benchmark": {"repetitions": 3, "batch_size": 512, "prompt_tokens": 128, "generation_tokens": 32, "long_context_prompt_tokens": 128, "long_context_generation_tokens": 32, "context_depths": [128, 256], "flash_attention": True}, "token": SECRET},
              "hardware": {"os": "Linux 6.8 " + SECRET, "hostname": SECRET, "execution": {"token": SECRET}, "cpu": {"brand": "Example CPU", "physical_cores": 8, "logical_cores": 16, "max_frequency_mhz": 4000., "serial": SECRET}, "memory": {"total_bytes": 8192}, "gpus": [{"index": 7, "vendor": "NVIDIA", "name": "Example GPU", "driver_version": "570.0", "compute_capability": "8.9", "memory.total": 4096, "power.limit": 300., "uuid": SECRET}], "memory_domains": [{"id": SECRET, "kind": "discrete_vram", "vendor": "NVIDIA", "identity": {"gpu_index": 7, "uuid": SECRET}, "capacity_bytes": 4096, "bandwidth": {"theoretical": {"value": 800., "source": "calculated", "unit": "GB/s", "evidence": {"method": "derived_calculation", "reference": SECRET, "provider": "nvml"}}}}]},
              "tools": {"llama_bench": {"build_commit": "abcdef123456", "build_number": 100, "binary": {"sha256": "b" * 64, "path": SECRET}, "raw": SECRET}, "vllm": {"digest": "private.registry/secret@sha256:" + "c" * 64, "image": SECRET}},
              "models": [{"model": {"name": SECRET, "path": SECRET, "sha256": "a" * 64, "size_bytes": 1000, "shard_count": 1, "notes": SECRET}, "quality_gate": {"passed": True, "message": SECRET}, "profiles": [{"name": SECRET, "settings": {"gpu_layers": -1, "threads": 4, "flash_attention": True, "cache_type_k": "f16", "dtype": "auto", "custom": SECRET}, "kv_cache": kv,
                  "context_capability": {"maximum_verified_context": 128, "requested_context_depths": [128, 256], "completed_context_depths": [128], "first_failed_context": 256, "limit_status": "skipped_capacity", "curve": [{"populated_context": 128, "prefill_tps": 50., "decode_tps": 10., "combined_tps": 20., "result": "pass"}, {"populated_context": 256, "prefill_tps": None, "decode_tps": None, "result": "oom", "error": SECRET}]},
                  "benchmarks": {"prompt": {"status": "partial", "rows": [{"n_prompt": 128, "n_gen": 0, "avg_ts": 50., "stddev_ts": 1., "n_gpu_layers": -1, "n_threads": 4, "repetitions": 3, "build_commit": "abcdef123456", "test": SECRET}, {"n_prompt": 256, "avg_ts": None, "status": "timeout", "error": SECRET}], "telemetry": telemetry, "efficiency": efficiency}, "generation": {"status": "failed", "rows": [], "error": SECRET}}}],
                  "endpoint": {"status": "partial", "duration_seconds": 5., "base_url": SECRET, "warmup": {"requests": 2, "successful": 2, "request_details": SECRET}, "settings": {"max_tokens": 32, "temperature": .7, "seed": -1, "ignore_eos": True, "requests_per_level": 2, "context_size": 4096, "parallel_slots": 2, "prompt": SECRET}, "levels": [{"concurrency": 2, "requests": 2, "successful": 1, "failed": 1, "wall_seconds": 5., "total_output_tokens": 32, "system_tps": 6.4, "ttft_p50_seconds": .2, "ttft_p95_seconds": .3, "request_details": SECRET}]},
                  "soak": [{"kind": "soak", "label": "short", "status": "partial", "duration_seconds": 5., "requested_duration_seconds": 10., "cpu_profile": SECRET, "gpu_profile": SECRET, "load_settings": {"cpu_concurrency": 1, "gpu_concurrency": 2, "cpu_request_timeout_seconds": 5., "gpu_request_timeout_seconds": 6., "thread_partition_enabled": True, "available_cpu_threads": 16, "cpu_server_threads": 12, "gpu_server_threads": 4, "url": SECRET}, "cpu": {"requests": 2, "successful": 1, "failed": 1, "total_output_tokens": 32, "avg_tps": 6.4, "tps_drop_fraction": .2, "throttling_suspected": True}, "gpu": {"requests": 2, "successful": 2, "failed": 0, "avg_tps": 10., "throttling_suspected": False}, "throttling_suspected": True}]}]}
    profile = source["models"][0]["profiles"][0]
    profile["benchmarks"]["long_context"] = {"status": "partial", "rows": [{"n_prompt": 16, "n_gen": 8, "n_depth": 128, "avg_ts": 12.5, "stddev_ts": .5, "status": "ok"}, {"n_prompt": 16, "n_gen": 8, "n_depth": 256, "avg_ts": None, "status": "skipped_capacity"}]}
    source["models"][0]["profiles"].append({"name": "private-cpu-profile", "settings": {"gpu_layers": 0, "threads": 12}, "kv_cache": normalize_kv_cache(backend, [KvCacheObservation("residency", "host")]), "benchmarks": {"generation": {"status": "ok", "rows": [{"n_prompt": 0, "n_gen": 32, "avg_ts": 10., "repetitions": 3}]}}})
    source["models"][0]["soak"][0]["cpu_profile"] = "private-cpu-profile"
    if backend == "vllm":
        source["tools"].pop("llama_bench")
    encoded = encode_v3(source)
    t = copy.deepcopy(encoded["models"][0]["profiles"][0]["benchmarks"]["prompt"]["telemetry"])
    t["memory_bandwidth"] = [{"domain_id": SECRET, "observed_during_benchmark": {"value": 100., "source": "measured", "unit": "GB/s", "evidence": {"method": "benchmark_measurement", "reference": SECRET}}}]
    encoded["telemetry"] = copy.deepcopy(t)
    encoded["models"][0]["endpoint"]["telemetry"] = copy.deepcopy(t)
    encoded["models"][0]["soak"][0]["telemetry"] = copy.deepcopy(t)
    encoded["backend"]["runtime"] = {"version": {"value": "0.10.2", "source": "detected", "evidence": {"method": "backend_runtime_introspection", "provider": "runtime"}}}
    validate_summary(encoded)
    return encoded


@pytest.mark.parametrize("backend", ["llama_cpp", "vllm"])
def test_native_projection_preserves_actual_scopes_and_provenance(backend: str) -> None:
    source = native_source(backend)
    before = copy.deepcopy(source)
    doc = project(source, nickname="public-user", excluded=set())
    data = json.loads(serialize(doc))
    assert source == before and SECRET not in serialize(doc).decode()
    assert data["run"]["started_at"] == "2026-10-09T10:00:00Z"
    assert data["backend"]["container_digest"] == "sha256:" + "c" * 64
    if backend == "llama_cpp":
        assert data["backend"]["measurement_tool"]["binary_sha256"] == "b" * 64
    else:
        assert "measurement_tool" not in data["backend"]
    model = data["models"][0]
    profile = model["profiles"][0]
    assert len(profile["benchmarks"]["prompt"]["rows"]) == 2
    avg = profile["benchmarks"]["prompt"]["rows"][0]["avg_ts"]
    assert avg["source"] == ("measured" if backend == "llama_cpp" else None)
    assert avg["value"] == 50.
    assert profile["benchmarks"]["prompt"]["efficiency"]["tokens_per_joule"]["source"] == "calculated"
    assert profile["context_capability"]["curve"][1]["result"] == "oom"
    assert profile["effective_kv_cache"]["backend_details"][0]["backend"] == backend
    assert model["endpoint"]["warmup_requests"] == 2
    assert model["endpoint"]["settings"]["ignore_eos"] is True
    assert model["stability"][0]["kind"] == "soak" and model["stability"][0]["label"] == "short"
    assert model["stability"][0]["cpu_profile_id"] == "profile_2"
    assert model["stability"][0]["cpu"]["throttling_suspected"] is True
    assert data["hardware"]["gpus"][0]["memory_bytes"] == 4096 * 1024 * 1024
    assert data["hardware"]["memory_domains"][0]["device_id"] == "gpu_0"
    assert data["telemetry"]["memory_bandwidth"][0]["domain_id"] == "domain_0"
    assert data["telemetry"]["foreign_gpu_load_detected"] is True
    assert data["telemetry"]["baseline_busy"] is True
    assert data["telemetry"]["cpu"]["energy_j"]["source"] == "measured"
    assert data["telemetry"]["power"]["wall_energy_j"]["value"] is None
    assert "source" in data["telemetry"]["power"]["wall_energy_j"]


@pytest.mark.parametrize("mask", range(16))
def test_all_exclusion_combinations_really_remove_metrics_and_keep_references(mask: int) -> None:
    groups = ("hardware", "energy", "capabilities", "telemetry")
    excluded = {group for i, group in enumerate(groups) if mask & (1 << i)}
    data = json.loads(serialize(project(native_source(), nickname=None, excluded=excluded)))
    assert data["omitted_groups"] == sorted(excluded)
    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value))
        return set()
    present = keys(data)
    for group, forbidden in (("energy", policy.ENERGY_FIELDS), ("telemetry", policy.TELEMETRY_FIELDS), ("capabilities", policy.CAPABILITY_FIELDS)):
        if group in excluded:
            assert not present & forbidden
    assert ("hardware" in data) == ("hardware" not in excluded)
    if "energy" not in excluded:
        assert "energy_j" in present and "tokens_per_joule" in present
    if "capabilities" not in excluded:
        assert "context_capability" in present and "memory_bandwidth" in present
    if "hardware" in excluded and "capabilities" not in excluded:
        assert data["telemetry"]["domain_references"] == [{"id": "domain_0"}]
    assert data["models"][0]["profiles"][0]["benchmarks"]["prompt"]["rows"][0]["n_prompt"] == 128
    parse_document(json.dumps(data))


@pytest.mark.parametrize("path,value", [
    (("export_schema_version",), True), (("export_schema_version",), 2), (("source_schema_version",), 4),
    (("backend", "id"), "private-backend"), (("run", "status"), "secret-status"),
    (("models", 0, "profiles", 0, "configured_settings", "threads"), True),
    (("models", 0, "profiles", 0, "configured_settings", "threads"), -1),
    (("models", 0, "profiles", 0, "benchmarks", "prompt", "rows", 0, "avg_ts", "unit"), "ms"),
    (("models", 0, "profiles", 0, "benchmarks", "prompt", "rows", 0, "avg_ts", "value"), True),
    (("models", 0, "profiles", 0, "benchmarks", "prompt", "rows", 0, "avg_ts", "source"), "requested_secret"),
    (("models", 0, "profiles", 0, "context_capability", "maximum_verified_context", "value"), 256),
    (("models", 0, "endpoint", "levels", 0, "failed"), 3),
    (("models", 0, "stability", 0, "cpu_profile_id"), "profile_999"),
    (("telemetry", "memory_bandwidth", 0, "domain_id"), "domain_999"),
    (("telemetry", "cpu", "energy_j", "status"), "unknown"),
    (("models", 0, "identity", "fingerprint", "algorithm"), "hash-of-hostname"),
])
def test_crafted_export_known_fields_fail_safely(path: tuple, value: object) -> None:
    data = json.loads(serialize(project(native_source(), nickname=None, excluded=set())))
    current = data
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value
    with pytest.raises(SafeError) as caught:
        parse_document(json.dumps(data))
    assert SECRET not in str(caught.value)
    if isinstance(value, str) and value not in {"unknown"}:
        assert value not in str(caught.value)


def test_native_source_validation_is_mandatory_even_when_group_excluded() -> None:
    source = native_source()
    source["backend"].pop("config")
    with pytest.raises(SafeError, match="backend.*invalid_source_schema"):
        project(source, nickname=None, excluded={"capabilities", "hardware"})
    source = native_source()
    source["models"][0]["profiles"][0]["benchmarks"][SECRET] = {"rows": [{"avg_ts": {"value": 1, "source": SECRET}}]}
    with pytest.raises(SafeError) as caught:
        project(source, nickname=None, excluded=set())
    assert SECRET not in str(caught.value)


def test_minimum_structured_benchmark_failure_and_legacy_label() -> None:
    source = {"schema_version": 1, "backend": "llama_cpp", "models": [{"model": {"path": "/missing/private.gguf"}, "profiles": [{"settings": {}, "benchmarks": {"prompt": {"status": "failed", "rows": []}}}]}]}
    document = project(source, nickname=None, excluded=set(), labels={1: "Historic model"})
    assert document.models[0].identity.exact_identity == "unverified"
    assert document.run.status == "unknown"
    source["models"][0]["profiles"][0]["benchmarks"]["prompt"] = {"rows": []}
    with pytest.raises(SafeError):
        project(source, nickname=None, excluded=set(), labels={1: "Historic model"})


def test_schema_copies_match_generation_and_are_closed() -> None:
    expected = schema_text()
    root = Path(__file__).resolve().parents[1]
    assert (root / "docs/schemas/community-export-v1.schema.json").read_bytes() == expected
    assert (root / "llmbench/community/schemas/community-export-v1.schema.json").read_bytes() == expected
    for definition in json.loads(expected)["$defs"].values():
        if definition.get("type") == "object":
            assert definition["additionalProperties"] is False


def test_published_native_partial_legacy_and_redacted_examples_validate() -> None:
    root = Path(__file__).resolve().parents[1]
    examples = root / "docs/examples/community"
    assert {path.name for path in examples.glob("*.json")} == {"happy.llama_cpp.json", "happy.vllm.json", "partial.json", "legacy.json", "redacted.json"}
    for path in examples.glob("*.json"):
        document = parse_document(path.read_text(encoding="utf-8"))
        assert SECRET not in serialize(document).decode()
    assert parse_document((examples / "redacted.json").read_text()).omitted_groups == ["capabilities", "energy", "hardware", "telemetry"]
