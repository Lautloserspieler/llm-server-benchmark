"""Explicit allowlist projection from result summaries to public documents."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Any


from .schema import CommunityExport, SafeError, validate_export
from .identity_v1 import resolve_identity
from . import policy
from llmbench.result_schema import validate_summary, ResultSchemaError

class ProjectionError(SafeError):
    pass


def _mapping(value: object) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ProjectionError("$: invalid_object")
    return value


def _safe_scalar(value: object) -> object | None:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, bool) or value is None or isinstance(value, (str, int, float)):
        return value
    return None


def _allow(value: object, *, keep: set[str]) -> dict[str, Any]:
    source = _mapping(value)
    result: dict[str, Any] = {}
    for key in keep:
        candidate = source.get(key)
        if isinstance(candidate, Mapping):
            # Provenance envelopes are only preserved when their compact keys are safe.
            item = _envelope(candidate)
            if item:
                result[key] = item
        elif key in source:
            result[key] = candidate
    return result


def _envelope(source: Mapping[str, object]) -> dict[str, object]:
    """Project a v3 envelope without copying free text or arbitrary metadata."""
    result: dict[str, object] = {}
    value = source.get("value")
    if _safe_scalar(value) is not None or value is None:
        result["value"] = value
    origin = source.get("source")
    if isinstance(origin, str) and origin in {"requested", "defaulted", "detected", "calculated", "measured", "verified"} or origin is None:
        result["source"] = origin
    unit = source.get("unit")
    if isinstance(unit, str) and len(unit) <= 32:
        result["unit"] = unit
    status = source.get("status")
    if isinstance(status, str) and status in {"unknown", "unavailable"}:
        result["status"] = status
    reason = source.get("reason")
    if reason is not None:
        result["reason"] = reason if isinstance(reason, str) and reason in policy.REASONS else "unknown_reason"
    evidence = _mapping(source.get("evidence"))
    method = evidence.get("method")
    provider = evidence.get("provider")
    if isinstance(method, str) and method in policy.METHODS or isinstance(provider, str) and provider in policy.PROVIDERS:
        safe_evidence: dict[str, object] = {"method": method} if isinstance(method, str) and method in policy.METHODS else {}
        if isinstance(provider, str) and provider in policy.PROVIDERS:
            safe_evidence["provider"] = evidence["provider"]
        # These are catalog tokens, never a free-form provider or diagnostic.
        metadata = _mapping(evidence.get("metadata"))
        for key in ("phase", "scope", "power_scope", "token_scope"):
            item = evidence.get(key, metadata.get(key))
            if isinstance(item, str) and item in policy.SCOPES:
                safe_evidence[key] = item
        coverage = evidence.get("coverage", metadata.get("coverage"))
        if isinstance(coverage, list) and all(isinstance(item, str) and (item in {"cpu_package", "gpu_board", "cpu", "gpu"} or re.fullmatch(r"gpu_\d+", item)) for item in coverage):
            safe_evidence["coverage"] = coverage
        for key in ("selected_gpu_layers", "selected_tps", "successful_candidates", "duration_seconds", "sample_count"):
            item = metadata.get(key)
            if _safe_scalar(item) is not None:
                safe_evidence[key] = item
        for key, token in (("protocol", "mactop-v2-headless-json"), ("field", "soc_metrics.DRAMBWCombined"), ("qualifier", "at_current_memory_clock")):
            if evidence.get(key) == token:
                safe_evidence[key] = token
        catalog_version = evidence.get("catalog_version")
        if isinstance(catalog_version, str) and re.fullmatch(r"\d{4}\.\d{2}", catalog_version):
            safe_evidence["catalog_version"] = catalog_version
        for key in ("memory_bus_width_bits", "max_memory_clock_mhz"):
            if key in metadata:
                safe_evidence[key] = metadata[key]
        result["evidence"] = safe_evidence
    return result


def _utc(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _legacy(value: object, name: str) -> dict[str, object]:
    if isinstance(value, Mapping):
        return _envelope(value)
    _kind, unit = policy.ENVELOPES[name]
    result = {"value": value, "source": None, "status": "unknown", "reason": "legacy_provenance_missing"}
    if unit is not None:
        result["unit"] = unit
    return result


def _settings(raw: object, keep: set[str]) -> dict[str, object]:
    result = _allow(raw, keep=keep)
    for key, value in list(result.items()):
        if isinstance(value, Mapping) and key != "gpu_layers":
            result[key] = value.get("value")
    for key, tokens in (("quantization", policy.QUANTIZATIONS), ("dtype", policy.DTYPES), ("cache_type_k", policy.DTYPES), ("cache_type_v", policy.DTYPES)):
        token = result.get(key)
        if isinstance(token, str) and token.lower() not in tokens:
            result.pop(key)
    return result


def _profile(profile: Mapping[str, Any], index: int, excluded: set[str]) -> dict[str, Any]:
    configured = _settings(profile.get("settings"), policy.PROFILE_CONFIG)
    if "gpu_layers" in configured:
        configured["gpu_layers"] = _legacy(_mapping(profile.get("settings"))["gpu_layers"], "gpu_layers")
    # Persisted v3 settings are provenance envelopes; configured values retain
    # their value while gpu_layers keeps its requested/calculated provenance.
    for key, value in list(configured.items()):
        if isinstance(value, Mapping) and "value" in value and key != "gpu_layers":
            configured[key] = value.get("value")
    benchmarks: dict[str, object] = {}
    raw_benches = _mapping(profile.get("benchmarks"))
    for kind in ("prompt", "generation", "long_context"):
        raw = raw_benches.get(kind)
        if isinstance(raw, Mapping):
            rows = [_allow(row, keep={"n_prompt", "n_gen", "n_depth", "n_threads", "n_gpu_layers", "avg_ts", "stddev_ts", "model_n_params", "model_size", "build_commit", "build_number", "status", "repetitions"}) for row in raw.get("rows", []) if isinstance(row, Mapping)]
            for row in rows:
                if "avg_ts" in row:
                    row["avg_ts"] = _legacy(row["avg_ts"], "avg_ts")
                if type(row.get("n_depth")) is int:
                    row["test"] = f"depth{row['n_depth']}"
                elif type(row.get("n_prompt")) is int and row["n_prompt"]:
                    row["test"] = f"pp{row['n_prompt']}" + (f"+tg{row['n_gen']}" if type(row.get("n_gen")) is int and row["n_gen"] else "")
                elif type(row.get("n_gen")) is int:
                    row["test"] = f"tg{row['n_gen']}"
            if rows or "status" in raw:
                public_benchmark: dict[str, object] = {"rows": rows}
                if "status" in raw:
                    public_benchmark["status"] = raw["status"]
                if raw.get("status") in policy.FAILURES:
                    public_benchmark["failure_reason"] = "capacity" if raw.get("capacity_limited") is True or raw.get("status") == "skipped_capacity" else "timeout" if raw.get("status") == "timeout" else "failure_reason_unknown"
                telemetry = _telemetry(raw.get("telemetry"))
                if telemetry:
                    public_benchmark["telemetry"] = telemetry
                if "energy" not in excluded:
                    efficiency = _mapping(raw.get("efficiency"))
                    if efficiency:
                        efficiency_fields: dict[str, object] = {}
                        for key in ("workload_tokens", "tokens_per_joule", "joules_per_1k_tokens", "wh_per_1k_tokens"):
                            value = efficiency.get(key)
                            if isinstance(value, Mapping):
                                efficiency_fields[key] = _envelope(value)
                            elif key in efficiency:
                                efficiency_fields[key] = _legacy(value, key)
                        public_benchmark["efficiency"] = {
                            "measurement_scope": efficiency.get("token_scope"),
                            "power_scope": efficiency.get("power_scope"),
                            "energy_coverage": efficiency.get("power_coverage", []),
                            **efficiency_fields,
                        }
                benchmarks[kind] = public_benchmark
    result: dict[str, object] = {"id": f"profile_{index}", "configured_settings": configured, "benchmarks": benchmarks}
    if "capabilities" not in excluded:
        if isinstance(profile.get("kv_cache"), Mapping):
            kv: dict[str, Any] = {name: _legacy(profile["kv_cache"][name], name) for name in policy.KV_CACHE_FIELDS if name in profile["kv_cache"]}
            details = []
            for backend, entries in _mapping(_mapping(profile["kv_cache"]).get("backend_details")).items():
                if backend not in {"llama_cpp", "vllm"} or not isinstance(entries, Mapping):
                    continue
                for field, value in entries.items():
                    if (backend, field) not in {("llama_cpp", "build_number"), ("vllm", "gpu_kv_cache_size_tokens"), ("vllm", "executor_gpu_memory_budget_fraction")} or not isinstance(value, Mapping):
                        continue
                    details.append({"backend": backend, "field": field, "value": _envelope(value)})
            if details:
                kv["backend_details"] = details
            result["effective_kv_cache"] = kv
        context = _mapping(profile.get("context_capability"))
        if context:
            capability = _allow(context, keep={"maximum_verified_context", "requested_context_depths", "completed_context_depths", "first_failed_context", "limit_status"})
            if "maximum_verified_context" in context:
                capability["maximum_verified_context"] = _legacy(context["maximum_verified_context"], "maximum_verified_context")
            curve = []
            for row in context.get("curve", []):
                if isinstance(row, Mapping) and isinstance(row.get("populated_context"), int) and not isinstance(row.get("populated_context"), bool):
                    curve.append(_allow(row, keep={"populated_context", "prefill_tps", "decode_tps", "combined_tps", "result"}))
            capability["curve"] = curve
            result["context_capability"] = capability
    return result


def _source_shapes(summary: Mapping[str, Any]) -> None:
    def array(raw: object, path: str) -> list:
        if not isinstance(raw, list):
            raise ProjectionError(f"{path}: invalid_array")
        return raw
    for model_index, model in enumerate(array(summary.get("models", []), "models")):
        model = _mapping(model)
        for profile_index, profile in enumerate(array(model.get("profiles", []), "models.profiles")):
            profile = _mapping(profile)
            _mapping(profile.get("settings"))
            benches = _mapping(profile.get("benchmarks"))
            for kind in ("prompt", "generation", "long_context"):
                if kind in benches:
                    benchmark = _mapping(benches[kind])
                    for row in array(benchmark.get("rows", []), f"models[{model_index}].profiles[{profile_index}].benchmarks.{kind}.rows"):
                        _mapping(row)
            if "context_capability" in profile:
                for row in array(_mapping(profile["context_capability"]).get("curve", []), "models.profiles.context_capability.curve"):
                    _mapping(row)
        if "endpoint" in model:
            for row in array(_mapping(model["endpoint"]).get("levels", []), "models.endpoint.levels"):
                _mapping(row)
        for item in array(model.get("soak", []), "models.stability"):
            _mapping(item)
    hardware = _mapping(summary.get("hardware"))
    for name in ("gpus", "memory_domains"):
        for item in array(hardware.get(name, []), "hardware." + name):
            _mapping(item)


def project(summary: Mapping[str, Any], *, nickname: str | None, excluded: set[str], labels: Mapping[int, str] | None = None, rehash_models: bool = False, rehash_positions: set[int] | None = None, identity_cache: dict | None = None) -> CommunityExport:
    _source_shapes(summary)
    try:
        source_version = validate_summary(summary)
    except ResultSchemaError as exc:
        match = re.search(r" at ([^:]+):", str(exc))
        path = match.group(1) if match else "schema_version"
        allowed = {"schema_version", "backend", "config", "hardware", "cpu", "physical_cores", "memory_domains", "bandwidth", "theoretical", "provider_operating", "telemetry", "memory_bandwidth", "models", "profiles", "settings", "gpu_layers", "kv_cache", "context_capability", "maximum_verified_context", "requested_context_depths", "completed_context_depths", "benchmarks", "prompt", "generation", "long_context", "rows", "avg_ts", "efficiency", "power", "gpus"} | set(policy.ENVELOPES)
        safe = []
        for part in path.split("."):
            token = re.fullmatch(r"([a-z_]+)(\[\d+\])?", part)
            if not token or token.group(1) not in allowed:
                break
            safe.append(part)
        raise ProjectionError(f"{'.'.join(safe) or '$'}: invalid_source_schema") from exc
    except (TypeError, ValueError) as exc:
        raise ProjectionError("$: invalid_source_schema") from exc
    if isinstance(source_version, bool) or not isinstance(source_version, int) or source_version not in {1, 2, 3}:
        raise ProjectionError("unsupported summary schema")
    raw_backend = summary.get("backend")
    backend_id = raw_backend if isinstance(raw_backend, str) else _mapping(raw_backend).get("id")
    if backend_id not in {"llama_cpp", "vllm"}:
        raise ProjectionError("summary lacks a supported backend")
    started, finished = _utc(summary.get("started_at")), _utc(summary.get("finished_at"))
    timestamp_status = "recorded" if started and finished else ("partial" if started or finished else "unknown")
    models: list[dict[str, Any]] = []
    for model_index, raw_model in enumerate(summary.get("models", []), start=1):
        if not isinstance(raw_model, Mapping):
            continue
        metadata = _mapping(raw_model.get("model"))
        identity = resolve_identity(metadata, label=(labels or {}).get(model_index), rehash=rehash_models or model_index in (rehash_positions or set()), cache=identity_cache)
        profiles = [_profile(profile, profile_index, excluded) for profile_index, profile in enumerate(raw_model.get("profiles", []), start=1) if isinstance(profile, Mapping)]
        entry: dict[str, object] = {"id": f"model_{model_index}", "identity": identity, "profiles": profiles}
        endpoint = _mapping(raw_model.get("endpoint"))
        if endpoint:
            levels = [_allow(level, keep={"concurrency", "requests", "successful", "failed", "wall_seconds", "total_output_tokens", "system_tps", "avg_interactivity_tps", "ttft_p50_seconds", "ttft_p95_seconds", "short_responses"}) for level in endpoint.get("levels", []) if isinstance(level, Mapping)]
            endpoint_public = _allow(endpoint, keep={"status", "duration_seconds"})
            if endpoint_public:
                endpoint_settings = _settings(endpoint.get("settings"), policy.ENDPOINT_CONFIG)
                if endpoint_settings:
                    endpoint_public["settings"] = endpoint_settings
                for source_key, output_key in (("requests", "warmup_requests"), ("successful", "warmup_successful")):
                    if source_key in _mapping(endpoint.get("warmup")):
                        endpoint_public[output_key] = endpoint["warmup"][source_key]
                endpoint_public["levels"] = levels
                telemetry = _telemetry(endpoint.get("telemetry"))
                if telemetry:
                    endpoint_public["telemetry"] = telemetry
                entry["endpoint"] = endpoint_public
        soak = []
        for item in raw_model.get("soak", []):
            if isinstance(item, Mapping):
                public = _allow(item, keep={"kind", "status", "duration_seconds", "requested_duration_seconds", "throttling_suspected"})
                kind = item.get("kind")
                public["kind"] = kind if kind in {"soak", "standard", "short", "long"} else "unknown"
                if item.get("label") in {"short", "long", "standard"}:
                    public["label"] = item["label"]
                load_settings = _settings(item.get("load_settings") or item.get("settings"), policy.SOAK_CONFIG)
                if load_settings:
                    public["load_settings"] = load_settings
                for source_key, output_key in (("cpu_profile", "cpu_profile_id"), ("gpu_profile", "gpu_profile_id")):
                    # Only generated IDs leave the boundary; custom names are not exported.
                    source_profile = item.get(source_key)
                    names = {profile.get("name"): f"profile_{i}" for i, profile in enumerate(raw_model.get("profiles", []), 1) if isinstance(profile, Mapping) and isinstance(profile.get("name"), str)}
                    if isinstance(source_profile, str) and source_profile in names:
                        public[output_key] = names[source_profile]
                    elif type(source_profile) is int and 0 < source_profile <= len(profiles):
                        public[output_key] = f"profile_{source_profile}"
                for side in ("cpu", "gpu"):
                    if isinstance(item.get(side), Mapping):
                        public[side] = _allow(item[side], keep={"requests", "successful", "failed", "total_output_tokens", "avg_tps", "early_window_avg_tps", "late_window_avg_tps", "tps_drop_fraction", "throttling_suspected"})
                telemetry = _telemetry(item.get("telemetry"))
                if telemetry:
                    public["telemetry"] = telemetry
                soak.append(public)
        if soak:
            entry["stability"] = soak
        for key in ("status", "failure_reason", "quality_gate"):
            value = raw_model.get(key)
            if key in raw_model and key != "quality_gate" or isinstance(value, str):
                entry[key] = value if key != "failure_reason" else "failure_reason_unknown"
        gate = _mapping(raw_model.get("quality_gate"))
        if type(gate.get("passed")) is bool:
            entry["quality_gate"] = "passed" if gate["passed"] else "failed"
        elif "passed" in gate:
            raise ProjectionError("models.quality_gate: invalid_boolean_value")
        telemetry = _telemetry(raw_model.get("telemetry"))
        if telemetry:
            entry["telemetry"] = telemetry
        if raw_model.get("status") in policy.FAILURES:
            entry["failure_reason"] = "capacity" if raw_model.get("capacity_limited") is True or raw_model.get("status") == "skipped_capacity" else "timeout" if raw_model.get("status") == "timeout" else "failure_reason_unknown"
        models.append(entry)
    if not models:
        raise ProjectionError("summary has no exportable models")
    backend: dict[str, object] = {"id": backend_id}
    tools = _mapping(summary.get("tools"))
    llama = _mapping(tools.get("llama_bench"))
    if llama:
        binary = _mapping(llama.get("binary"))
        measurement = _allow(llama, keep={"build_commit", "build_number", "binary_sha256"})
        binary_hash = binary.get("sha256")
        if binary_hash is not None:
            measurement["binary_sha256"] = binary_hash
        measurement["id"] = "llama_bench"
        backend["measurement_tool"] = measurement
    vllm = _mapping(tools.get("vllm"))
    digest = vllm.get("digest")
    if isinstance(digest, str) and re.search(r"(?:^|@)sha256:[0-9a-f]{64}$", digest):
        backend["container_digest"] = digest.rsplit("@", 1)[-1]
    elif isinstance(vllm.get("image"), str):
        match = re.search(r"@(?P<digest>sha256:[0-9a-f]{64})$", vllm["image"])
        if match:
            backend["container_digest"] = match.group("digest")
    runtime = _mapping(raw_backend.get("runtime")) if isinstance(raw_backend, Mapping) else {}
    if runtime:
        backend["runtime"] = {field: _legacy(runtime[field], field) for field in ("version", "build_number") if field in runtime}
    configuration = _settings(_mapping(summary.get("config")).get("benchmark"), policy.BENCHMARK_CONFIG)
    for key, value in list(configuration.items()):
        if isinstance(value, Mapping) and "value" in value:
            configuration[key] = value.get("value")
    outcome = summary.get("status") or summary.get("outcome")
    run_status = outcome if outcome in {"completed", "partial", "failed", "unknown"} else ("completed" if finished else "unknown")
    target = summary.get("hardware_target")
    target = target if target in {"cpu", "gpu", "gpu_overload", "both", "unknown"} else "unknown"
    document: dict[str, Any] = {"export_schema_version": 1, "source_schema_version": source_version, "llmbench_version": summary.get("llmbench_version"), "run": {"started_at": started, "finished_at": finished, "timestamp_status": timestamp_status, "hardware_target": target, "status": run_status}, "backend": backend, "models": models, "omitted_groups": sorted(excluded)}
    if nickname:
        document["attribution"] = {"nickname": nickname}
    canonical = json_bytes({"backend": backend_id, "benchmark": configuration, "models": [{"profiles": [profile["configured_settings"] for profile in model["profiles"]], "endpoint": _mapping(model.get("endpoint")).get("settings", {}), "stability": [_mapping(soak).get("load_settings", {}) for soak in model.get("stability", [])]} for model in models]})
    document["benchmark_configuration"] = {"values": configuration, "completeness": "retained_configured_fields", "fingerprint": {"algorithm": "sha256", "scope": "exported_configuration_v1", "value": hashlib.sha256(canonical).hexdigest()}}
    if "hardware" not in excluded:
        raw_hardware = _mapping(summary.get("hardware"))
        if raw_hardware:
            cpu = _mapping(raw_hardware.get("cpu"))
            public_cpu = {"product_name": cpu.get("brand") or cpu.get("name"), "physical_cores": _legacy(cpu["physical_cores"], "physical_cores") if "physical_cores" in cpu else None, "logical_cores": cpu.get("logical_cores"), "max_frequency_mhz": cpu.get("max_frequency_mhz")}
            public_cpu = {key: value for key, value in public_cpu.items() if _safe_scalar(value) is not None or isinstance(value, Mapping)}
            public_gpus = []
            for index, gpu in enumerate(raw_hardware.get("gpus", [])):
                if isinstance(gpu, Mapping):
                    public_gpus.append({"id": f"gpu_{index}", **_allow(gpu, keep={"vendor", "driver_version", "compute_capability"}), "product_name": gpu.get("name"), "memory_bytes": gpu.get("memory_total_bytes", int(gpu["memory.total"] * 1024 * 1024) if gpu.get("vendor") == "NVIDIA" and type(gpu.get("memory.total")) in {int, float} else None), "power_limit_w": gpu.get("power.limit")})
            domains = []
            for index, domain in enumerate(raw_hardware.get("memory_domains", [])):
                if isinstance(domain, Mapping):
                    bandwidth = _mapping(domain.get("bandwidth"))
                    domains.append({"id": f"domain_{index}", "kind": domain.get("kind"), "vendor": domain.get("vendor"), "capacity_bytes": domain.get("capacity_bytes"), "theoretical_bandwidth": _legacy(bandwidth["theoretical"], "theoretical_bandwidth") if "theoretical" in bandwidth else None, "provider_operating_bandwidth": _legacy(bandwidth["provider_operating"], "provider_operating_bandwidth") if "provider_operating" in bandwidth else None})
                    gpu_index = _mapping(domain.get("identity")).get("gpu_index")
                    source_gpus = raw_hardware.get("gpus", [])
                    for i, gpu in enumerate(source_gpus):
                        if isinstance(gpu, Mapping) and type(gpu_index) is int and gpu.get("index", i) == gpu_index:
                            domains[-1]["device_id"] = f"gpu_{i}"
            memory = _mapping(raw_hardware.get("memory"))
            os_value = raw_hardware.get("os")
            os_family = next((name for name in ("Windows", "Linux", "Darwin") if isinstance(os_value, str) and re.match(name, os_value, re.I)), None)
            document["hardware"] = {"os_family": os_family, "cpu": public_cpu or None, "memory_total_bytes": memory.get("total_bytes"), "gpus": public_gpus, "memory_domains": domains}
            for name in ("os_version", "architecture"):
                if name in raw_hardware:
                    document["hardware"][name] = raw_hardware[name]
    telemetry = _telemetry(summary.get("telemetry"))
    if telemetry:
        document["telemetry"] = telemetry
    _finish_groups(document, summary, excluded)
    from .schema import serialize
    clean = json_bytes_for_configuration(document)
    configuration_public = _mapping(document["benchmark_configuration"])
    document["benchmark_configuration"] = {**configuration_public, "fingerprint": {**_mapping(configuration_public["fingerprint"]), "value": hashlib.sha256(json_bytes(json.loads(serialize(clean)))).hexdigest()}}
    return validate_export(document)


def json_bytes_for_configuration(document: Mapping[str, Any]) -> dict[str, Any]:
    return {"backend": document["backend"]["id"], "benchmark": document["benchmark_configuration"]["values"], "models": [{"profiles": [profile["configured_settings"] for profile in model["profiles"]], "endpoint": _mapping(model.get("endpoint")).get("settings", {}), "stability": [_mapping(soak).get("load_settings", {}) for soak in model.get("stability", [])]} for model in document["models"]]}


def _finish_groups(document: dict[str, object], summary: Mapping[str, Any], excluded: set[str]) -> None:
    raw_hardware = _mapping(summary.get("hardware"))
    domains = {domain.get("id"): f"domain_{index}" for index, domain in enumerate(raw_hardware.get("memory_domains", [])) if isinstance(domain, Mapping) and isinstance(domain.get("id"), str)}
    devices = {f"gpu_source_{gpu.get('index', index)}": f"gpu_{index}" for index, gpu in enumerate(raw_hardware.get("gpus", [])) if isinstance(gpu, Mapping)}
    def visit(value: object) -> None:
        if isinstance(value, dict):
            if "memory_bandwidth" in value:
                references = []
                for row in value["memory_bandwidth"]:
                    raw_id = row.get("domain_id")
                    if raw_id not in domains:
                        raise ProjectionError("telemetry.memory_bandwidth: unresolved_domain_reference")
                    row["domain_id"] = domains[raw_id]
                    if "hardware" in excluded and {"id": domains[raw_id]} not in references:
                        references.append({"id": domains[raw_id]})
                if references:
                    value["domain_references"] = references
            if isinstance(value.get("id"), str) and value["id"].startswith("gpu_source_"):
                value["id"] = devices.get(value["id"], value["id"].replace("gpu_source_", "gpu_"))
            for name in ("coverage", "energy_coverage"):
                if isinstance(value.get(name), list):
                    value[name] = [devices.get("gpu_source_" + item.removeprefix("gpu_"), item) if isinstance(item, str) and item.startswith("gpu_") else item for item in value[name]]
            for name in list(value):
                if ("energy" in excluded and name in policy.ENERGY_FIELDS) or ("telemetry" in excluded and name in policy.TELEMETRY_FIELDS) or ("capabilities" in excluded and name in policy.CAPABILITY_FIELDS):
                    del value[name]
                else:
                    visit(value[name])
            for name in ("telemetry", "cpu", "power"):
                if value.get(name) == {}:
                    del value[name]
            if "gpus" in value:
                value["gpus"] = [gpu for gpu in value["gpus"] if len(gpu) > 1 or "hardware" in value]
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(document)


def json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _telemetry(raw: object) -> dict[str, Any] | None:
    source = _mapping(raw)
    if not source:
        return None
    result = _allow(source, keep={"sample_count", "sample_interval_seconds", "avg_cpu_percent", "max_cpu_percent", "avg_ram_bytes", "max_ram_bytes"})
    cpu = _mapping(source.get("cpu"))
    if cpu:
        public_cpu = _allow(cpu, keep={"avg_frequency_mhz", "min_frequency_mhz", "max_frequency_mhz", "avg_temperature_c", "max_temperature_c", "avg_package_power_w", "max_package_power_w", "energy_j", "energy_wh", "energy_source", "energy_coverage_seconds"})
        for name in public_cpu.keys() & {"avg_package_power_w", "max_package_power_w", "energy_j", "energy_wh"}:
            public_cpu[name] = _legacy(cpu[name], name)
        for output, native in (("avg_utilization_percent", "avg_util_percent"), ("max_utilization_percent", "max_util_percent")):
            if _safe_scalar(cpu.get(native)) is not None:
                public_cpu[output] = cpu[native]
        result["cpu"] = public_cpu
    gpus = []
    for index, gpu in enumerate(source.get("gpus", [])):
        if isinstance(gpu, Mapping):
            public_gpu = _allow(gpu, keep={"avg_memory_used_bytes", "max_memory_used_bytes", "memory_total_bytes", "avg_power_w", "max_power_w", "max_temperature_c", "energy_j", "energy_wh", "energy_source", "energy_coverage_seconds"})
            for name in public_gpu.keys() & {"energy_j", "energy_wh"}:
                public_gpu[name] = _legacy(gpu[name], name)
            for output, native in (("avg_utilization_percent", "avg_util_gpu_percent"), ("max_utilization_percent", "max_util_gpu_percent")):
                if _safe_scalar(gpu.get(native)) is not None:
                    public_gpu[output] = gpu[native]
            gpus.append({"id": f"gpu_source_{gpu.get('index', index)}", **public_gpu})
    if gpus:
        result["gpus"] = gpus
    power = _mapping(source.get("power"))
    if power:
        result["power"] = _allow(power, keep={"scope", "coverage", "avg_component_power_w", "max_component_power_w", "component_energy_j", "component_energy_wh", "wall_energy_j", "wall_energy_wh", "wall_power_w"})
        for name in result["power"].keys() & policy.ENVELOPES.keys():
            result["power"][name] = _legacy(power[name], name)
    observations = []
    for item in source.get("memory_bandwidth", []):
        if isinstance(item, Mapping):
            observed = item.get("observed_during_benchmark") or item.get("observed")
            if isinstance(observed, Mapping):
                observations.append({"domain_id": item.get("domain_id"), "observed_during_benchmark": _envelope(observed)})
    if observations:
        result["memory_bandwidth"] = observations
    if "foreign_gpu_processes" in source or any("foreign_gpu_processes" in gpu for gpu in source.get("gpus", []) if isinstance(gpu, Mapping)):
        result["foreign_gpu_load_detected"] = bool(source.get("foreign_gpu_processes")) or any(bool(gpu.get("foreign_gpu_processes")) for gpu in source.get("gpus", []) if isinstance(gpu, Mapping))
    baseline = _mapping(source.get("baseline"))
    values = [baseline.get("cpu_percent"), baseline.get("utilization_percent")]
    values += [gpu.get("util_gpu_percent") for gpu in baseline.get("gpus", []) if isinstance(gpu, Mapping)]
    numeric = [item for item in values if isinstance(item, (int, float)) and not isinstance(item, bool)]
    if numeric:
        result["baseline_busy"] = any(item > 10 for item in numeric)
    return result or None
