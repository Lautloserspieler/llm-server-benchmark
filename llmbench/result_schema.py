"""Versioned result-summary encoding and safe scalar projections.

The benchmark keeps live values scalar.  Provenance envelopes are introduced
only when a summary is persisted or read by a public result consumer.
"""
from __future__ import annotations

import copy
import math
import re
from typing import Any


SOURCES = {"requested", "defaulted", "detected", "calculated", "measured", "verified"}
STATUSES = {"unknown", "unavailable"}
CONTEXT_RESULTS = {"pass", "oom", "timeout", "failed", "partial", "unknown"}
METHODS = {
    "user_configuration", "configuration_default", "hardware_introspection",
    "backend_runtime_introspection", "backend_log_parsing", "model_metadata",
    "derived_calculation", "benchmark_measurement", "experimental_validation",
    "hardware_energy_counter",
}


class ResultSchemaError(ValueError):
    """A persisted result does not satisfy the declared schema contract."""


def envelope(value: Any, source: str | None, *, unit: str | None = None,
             status: str | None = None, reason: str | None = None,
             evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"value": value, "source": source}
    if unit is not None:
        result["unit"] = unit
    if status is not None:
        result["status"] = status
    if reason is not None:
        result["reason"] = reason
    if evidence is not None:
        result["evidence"] = copy.deepcopy(evidence)
    return result


def _fail(path: str, detail: str) -> None:
    raise ResultSchemaError(f"Invalid schema v3 value at {path}: {detail}")


def _number(value: Any, path: str, integer: bool = False, positive: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(path, "value must be a number" if not integer else "value must be an integer")
    if not math.isfinite(float(value)):
        _fail(path, "value must be finite")
    if integer and not isinstance(value, int):
        _fail(path, "value must be an integer")
    if positive and value <= 0:
        _fail(path, "value must be positive")


def validate_envelope(item: Any, path: str, *, kind: str, unit: str | None = None,
                      positive: bool = False) -> None:
    if not isinstance(item, dict):
        _fail(path, "must be an object")
    if "value" not in item or "source" not in item:
        _fail(path, "requires value and source")
    source = item["source"]
    value = item["value"]
    if source is None:
        if not isinstance(item.get("status"), str) or item.get("status") not in STATUSES or not isinstance(item.get("reason"), str) or not item["reason"]:
            _fail(path, "a missing source requires status unknown/unavailable and a reason")
    elif not isinstance(source, str) or source not in SOURCES:
        _fail(path, f"unsupported source {source!r}")
    elif item.get("status") is not None:
        _fail(path, "known source cannot include unknown/unavailable status")
    if item.get("status") == "unavailable" and value is not None:
        _fail(path, "unavailable requires a null value")
    if value is None and source is not None:
        _fail(path, "null value requires unknown or unavailable state")
    if unit is None:
        if "unit" in item:
            _fail(path, "does not allow a unit")
    elif item.get("unit") != unit:
        _fail(path, f"requires unit {unit!r}")
    if value is not None:
        if kind == "integer":
            _number(value, path, integer=True, positive=positive)
        elif kind == "number":
            _number(value, path, positive=positive)
        elif kind == "string" and not isinstance(value, str):
            _fail(path, "value must be a string")
        elif kind == "boolean" and not isinstance(value, bool):
            _fail(path, "value must be a boolean")
    evidence = item.get("evidence")
    if evidence is not None:
        if not isinstance(evidence, dict):
            _fail(path, "evidence must be an object")
        for key in ("method", "reference", "provider"):
            if key in evidence and not isinstance(evidence[key], str):
                _fail(path, f"evidence.{key} must be a string")
        method = evidence.get("method")
        if method is not None and not (method in METHODS or method.startswith("custom:")):
            # Unknown names are allowed as future extensions; only structure is strict.
            pass


def _validate_context_capability(item: Any, path: str) -> None:
    if not isinstance(item, dict):
        _fail(path, "must be an object")

    if "maximum_verified_context" in item:
        maximum = item["maximum_verified_context"]
        validate_envelope(
            maximum,
            f"{path}.maximum_verified_context",
            kind="integer",
            unit="tokens",
        )
        if maximum.get("value") is not None and maximum.get("source") != "verified":
            _fail(
                f"{path}.maximum_verified_context",
                "a successful context maximum must use source 'verified'",
            )

    for key in ("completed_context_depths", "requested_context_depths"):
        values = item.get(key, [])
        if not isinstance(values, list):
            _fail(f"{path}.{key}", "must be an array")
        for index, value in enumerate(values):
            _number(value, f"{path}.{key}[{index}]", integer=True)
            if value < 0:
                _fail(f"{path}.{key}[{index}]", "must not be negative")

    failed = item.get("first_failed_context")
    if failed is not None:
        _number(failed, f"{path}.first_failed_context", integer=True)
        if failed < 0:
            _fail(f"{path}.first_failed_context", "must not be negative")

    limit_status = item.get("limit_status")
    if limit_status is not None and not isinstance(limit_status, str):
        _fail(f"{path}.limit_status", "must be a string or null")

    curve = item.get("curve", [])
    if not isinstance(curve, list):
        _fail(f"{path}.curve", "must be an array")
    for index, row in enumerate(curve):
        row_path = f"{path}.curve[{index}]"
        if not isinstance(row, dict):
            _fail(row_path, "must be an object")
        if "populated_context" not in row:
            _fail(row_path, "requires populated_context")
        _number(row["populated_context"], f"{row_path}.populated_context", integer=True)
        if row["populated_context"] < 0:
            _fail(f"{row_path}.populated_context", "must not be negative")
        for key in ("prefill_tps", "decode_tps", "combined_tps"):
            if row.get(key) is not None:
                _number(row[key], f"{row_path}.{key}")
        result = row.get("result")
        if not isinstance(result, str) or result not in CONTEXT_RESULTS:
            _fail(f"{row_path}.result", f"unsupported result {result!r}")


def _validate_kv_cache(item: Any, path: str) -> None:
    """Validate the additive effective KV-cache core for schema v3.

    Generic envelopes intentionally support requested/defaulted values elsewhere
    in v3.  Effective KV-cache values are stricter: only runtime detection or a
    documented calculation may establish a non-null value.
    """
    from .kv_cache import KV_CACHE_FIELDS, RESIDENCIES

    if not isinstance(item, dict):
        _fail(path, "must be an object")
    for field, (kind, unit) in KV_CACHE_FIELDS.items():
        field_path = f"{path}.{field}"
        if field not in item:
            _fail(field_path, "is required")
        value = item[field]
        validate_envelope(value, field_path, kind=kind, unit=unit)
        source = value.get("source") if isinstance(value, dict) else None
        if source is not None and source not in {"detected", "calculated"}:
            _fail(field_path, "effective KV-cache values require detected or calculated source")
        if source is None and value.get("value") is not None:
            _fail(field_path, "unknown/unavailable effective value must be null")
        if field == "memory_budget_fraction" and value.get("value") is not None:
            fraction = value["value"]
            if not 0 <= float(fraction) <= 1:
                _fail(field_path, "must be between 0 and 1")
        if field == "residency" and value.get("value") is not None and value["value"] not in RESIDENCIES:
            _fail(field_path, "unsupported residency")
    details = item.get("backend_details")
    if details is not None:
        if not isinstance(details, dict):
            _fail(f"{path}.backend_details", "must be an object")
        for backend, entries in details.items():
            if not isinstance(backend, str) or not backend or not isinstance(entries, dict):
                _fail(f"{path}.backend_details", "requires backend object namespaces")
            for name, entry in entries.items():
                if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name):
                    _fail(f"{path}.backend_details.{backend}", "field names must be bounded identifiers")
                # Backend detail semantics are private, but it is still an envelope.
                detail_path = f"{path}.backend_details.{backend}.{name}"
                if not isinstance(entry, dict):
                    _fail(detail_path, "must be an envelope")
                detail_value = entry.get("value")
                detail_kind = (
                    "boolean" if isinstance(detail_value, bool) else
                    "integer" if isinstance(detail_value, int) else
                    "number" if isinstance(detail_value, float) else "string"
                )
                validate_envelope(entry, detail_path, kind=detail_kind, unit=entry.get("unit"))


def _validate_energy_telemetry(item: Any, path: str) -> None:
    if not isinstance(item, dict):
        _fail(path, "must be an object")

    cpu = item.get("cpu")
    if cpu is not None:
        if not isinstance(cpu, dict):
            _fail(f"{path}.cpu", "must be an object")
        for field, unit in (
            ("avg_package_power_w", "W"),
            ("max_package_power_w", "W"),
            ("energy_j", "J"),
            ("energy_wh", "Wh"),
        ):
            if field in cpu:
                validate_envelope(
                    cpu[field],
                    f"{path}.cpu.{field}",
                    kind="number",
                    unit=unit,
                )

    gpus = item.get("gpus")
    if gpus is not None:
        if not isinstance(gpus, list):
            _fail(f"{path}.gpus", "must be an array")
        for index, gpu in enumerate(gpus):
            if not isinstance(gpu, dict):
                _fail(f"{path}.gpus[{index}]", "must be an object")
            for field, unit in (
                ("energy_j", "J"),
                ("energy_wh", "Wh"),
            ):
                if field in gpu:
                    validate_envelope(
                        gpu[field],
                        f"{path}.gpus[{index}].{field}",
                        kind="number",
                        unit=unit,
                    )

    power = item.get("power")
    if power is not None:
        if not isinstance(power, dict):
            _fail(f"{path}.power", "must be an object")
        if power.get("scope") not in {None, "measured_components"}:
            _fail(f"{path}.power.scope", "unsupported measurement scope")
        coverage = power.get("coverage", [])
        if not isinstance(coverage, list) or not all(
            isinstance(value, str) for value in coverage
        ):
            _fail(f"{path}.power.coverage", "must be an array of strings")
        for field, unit in (
            ("avg_component_power_w", "W"),
            ("max_component_power_w", "W"),
            ("component_energy_j", "J"),
            ("component_energy_wh", "Wh"),
            ("wall_power_w", "W"),
            ("wall_energy_j", "J"),
            ("wall_energy_wh", "Wh"),
        ):
            if field in power:
                validate_envelope(
                    power[field],
                    f"{path}.power.{field}",
                    kind="number",
                    unit=unit,
                )


def _validate_efficiency(item: Any, path: str) -> None:
    if not isinstance(item, dict):
        _fail(path, "must be an object")
    if item.get("power_scope") != "measured_components":
        _fail(f"{path}.power_scope", "must be 'measured_components'")
    if item.get("token_scope") not in {"prompt_tokens", "generated_tokens"}:
        _fail(f"{path}.token_scope", "unsupported token scope")
    coverage = item.get("power_coverage", [])
    if not isinstance(coverage, list) or not all(
        isinstance(value, str) for value in coverage
    ):
        _fail(f"{path}.power_coverage", "must be an array of strings")
    for field, kind, unit in (
        ("workload_tokens", "integer", "tokens"),
        ("tokens_per_joule", "number", "tokens/J"),
        ("joules_per_1k_tokens", "number", "J/1k tokens"),
        ("wh_per_1k_tokens", "number", "Wh/1k tokens"),
    ):
        if field not in item:
            _fail(f"{path}.{field}", "is required")
        validate_envelope(
            item[field],
            f"{path}.{field}",
            kind=kind,
            unit=unit,
            positive=True,
        )


def _encode_telemetry_energy_v3(telemetry: dict[str, Any]) -> None:
    cpu = telemetry.get("cpu")
    if isinstance(cpu, dict):
        cpu_provider = str(
            telemetry.get("cpu_telemetry_source")
            or cpu.get("telemetry_source")
            or "cpu"
        )
        power_evidence = {
            "method": (
                "hardware_energy_counter"
                if cpu.get("energy_source") == "hardware_energy_counter"
                else "hardware_introspection"
            ),
            "provider": cpu_provider,
        }
        for field in ("avg_package_power_w", "max_package_power_w"):
            if field in cpu and not isinstance(cpu[field], dict):
                value = cpu[field]
                cpu[field] = (
                    envelope(value, "measured", unit="W", evidence=power_evidence)
                    if value is not None
                    else envelope(
                        None,
                        None,
                        unit="W",
                        status="unavailable",
                        reason="cpu_power_sensor_not_available",
                    )
                )

        energy_source = cpu.get("energy_source")
        energy_origin = "measured" if energy_source == "hardware_energy_counter" else "calculated"
        energy_method = (
            "hardware_energy_counter"
            if energy_source == "hardware_energy_counter"
            else "derived_calculation"
        )
        for field, unit in (("energy_j", "J"), ("energy_wh", "Wh")):
            if field in cpu and not isinstance(cpu[field], dict):
                value = cpu[field]
                cpu[field] = (
                    envelope(
                        value,
                        energy_origin,
                        unit=unit,
                        evidence={"method": energy_method, "provider": cpu_provider},
                    )
                    if value is not None
                    else envelope(
                        None,
                        None,
                        unit=unit,
                        status="unavailable",
                        reason="cpu_energy_not_available",
                    )
                )

    gpu_provider = str(telemetry.get("telemetry_source") or "gpu")
    for gpu in telemetry.get("gpus") or []:
        if not isinstance(gpu, dict):
            continue
        for field, unit in (("energy_j", "J"), ("energy_wh", "Wh")):
            if field in gpu and not isinstance(gpu[field], dict):
                value = gpu[field]
                gpu[field] = (
                    envelope(
                        value,
                        "calculated",
                        unit=unit,
                        evidence={
                            "method": "derived_calculation",
                            "provider": gpu_provider,
                        },
                    )
                    if value is not None
                    else envelope(
                        None,
                        None,
                        unit=unit,
                        status="unavailable",
                        reason="gpu_power_samples_not_available",
                    )
                )

    power = telemetry.get("power")
    if isinstance(power, dict):
        for field, unit in (
            ("avg_component_power_w", "W"),
            ("max_component_power_w", "W"),
            ("component_energy_j", "J"),
            ("component_energy_wh", "Wh"),
        ):
            if field in power and not isinstance(power[field], dict):
                value = power[field]
                power[field] = (
                    envelope(
                        value,
                        "calculated",
                        unit=unit,
                        evidence={
                            "method": "derived_calculation",
                            "provider": "llmbench",
                            "metadata": {
                                "scope": "measured_components",
                                "coverage": list(power.get("coverage") or []),
                            },
                        },
                    )
                    if value is not None
                    else envelope(
                        None,
                        None,
                        unit=unit,
                        status="unavailable",
                        reason="component_power_not_available",
                    )
                )
        for field, unit in (
            ("wall_power_w", "W"),
            ("wall_energy_j", "J"),
            ("wall_energy_wh", "Wh"),
        ):
            if field in power and not isinstance(power[field], dict):
                value = power[field]
                power[field] = (
                    envelope(
                        value,
                        "measured",
                        unit=unit,
                        evidence={
                            "method": "hardware_introspection",
                            "provider": "wall_power_provider",
                        },
                    )
                    if value is not None
                    else envelope(
                        None,
                        None,
                        unit=unit,
                        status="unavailable",
                        reason="wall_power_provider_not_configured",
                    )
                )


def _encode_efficiency_v3(efficiency: dict[str, Any]) -> None:
    for field, unit in (
        ("workload_tokens", "tokens"),
        ("tokens_per_joule", "tokens/J"),
        ("joules_per_1k_tokens", "J/1k tokens"),
        ("wh_per_1k_tokens", "Wh/1k tokens"),
    ):
        if field in efficiency and not isinstance(efficiency[field], dict):
            value = efficiency[field]
            efficiency[field] = envelope(
                value,
                "calculated",
                unit=unit,
                evidence={
                    "method": "derived_calculation",
                    "provider": "llmbench",
                    "metadata": {
                        "power_scope": efficiency.get("power_scope"),
                        "token_scope": efficiency.get("token_scope"),
                    },
                },
            )


def _walk_v3(summary: dict[str, Any]) -> None:
    backend = summary.get("backend")
    if not isinstance(backend, dict) or not isinstance(backend.get("id"), str) or not backend["id"]:
        _fail("backend", "requires a non-empty id")
    assert isinstance(backend, dict)
    if "name" in backend and not isinstance(backend["name"], str):
        _fail("backend.name", "must be a string")
    if "config" not in backend or not isinstance(backend["config"], dict):
        _fail("backend.config", "requires an object")
    hardware = summary.get("hardware", {})
    if not isinstance(hardware, dict):
        _fail("hardware", "must be an object")
    cpu = hardware.get("cpu", {})
    if not isinstance(cpu, dict):
        _fail("hardware.cpu", "must be an object")
    if "physical_cores" in cpu:
        validate_envelope(cpu["physical_cores"], "hardware.cpu.physical_cores", kind="integer", unit="cores", positive=True)
    domains = hardware.get("memory_domains", [])
    if not isinstance(domains, list):
        _fail("hardware.memory_domains", "must be an array")
    domain_ids: set[str] = set()
    for index, domain in enumerate(domains):
        path = f"hardware.memory_domains[{index}]"
        if not isinstance(domain, dict):
            _fail(path, "must be an object")
        identifier = domain.get("id")
        if not isinstance(identifier, str) or not identifier:
            _fail(path, "requires a non-empty id")
        if identifier in domain_ids:
            _fail(path, "id must be unique")
        domain_ids.add(identifier)
        if not isinstance(domain.get("kind"), str) or not domain["kind"]:
            _fail(path, "requires a kind")
        if not isinstance(domain.get("vendor"), str) or not domain["vendor"]:
            _fail(path, "requires a vendor")
        bandwidth = domain.get("bandwidth", {})
        if not isinstance(bandwidth, dict):
            _fail(f"{path}.bandwidth", "must be an object")
        for key in ("theoretical", "provider_operating"):
            if key in bandwidth:
                validate_envelope(bandwidth[key], f"{path}.bandwidth.{key}", kind="number", unit="GB/s", positive=True)
    telemetry = summary.get("telemetry", {})
    if telemetry is not None and not isinstance(telemetry, dict):
        _fail("telemetry", "must be an object")
    bandwidth_rows = (telemetry or {}).get("memory_bandwidth", [])
    if not isinstance(bandwidth_rows, list):
        _fail("telemetry.memory_bandwidth", "must be an array")
    for index, row in enumerate(bandwidth_rows):
        path = f"telemetry.memory_bandwidth[{index}]"
        if not isinstance(row, dict) or not isinstance(row.get("domain_id"), str):
            _fail(path, "requires a domain_id")
        if row["domain_id"] not in domain_ids:
            _fail(path, "references an unknown memory domain")
        observed = row.get("observed_during_benchmark")
        if observed is not None:
            validate_envelope(observed, f"{path}.observed_during_benchmark", kind="number", unit="GB/s", positive=True)
    models = summary.get("models", [])
    if not isinstance(models, list):
        _fail("models", "must be an array")
    for mi, model in enumerate(models):
        if not isinstance(model, dict):
            _fail(f"models[{mi}]", "must be an object")
        profiles = model.get("profiles", [])
        if not isinstance(profiles, list):
            _fail(f"models[{mi}].profiles", "must be an array")
        for pi, profile in enumerate(profiles):
            if not isinstance(profile, dict):
                _fail(f"models[{mi}].profiles[{pi}]", "must be an object")
            settings = profile.get("settings", {})
            if not isinstance(settings, dict):
                _fail(f"models[{mi}].profiles[{pi}].settings", "must be an object")
            if "gpu_layers" in settings:
                validate_envelope(settings["gpu_layers"], f"models[{mi}].profiles[{pi}].settings.gpu_layers", kind="integer", unit="layers")
            if "context_capability" in profile:
                _validate_context_capability(
                    profile["context_capability"],
                    f"models[{mi}].profiles[{pi}].context_capability",
                )
            if "kv_cache" in profile:
                _validate_kv_cache(profile["kv_cache"], f"models[{mi}].profiles[{pi}].kv_cache")
            all_benchmarks = profile.get("benchmarks", {})
            if not isinstance(all_benchmarks, dict):
                _fail(f"models[{mi}].profiles[{pi}].benchmarks", "must be an object")
            for kind, benchmark in all_benchmarks.items():
                if not isinstance(benchmark, dict):
                    _fail(
                        f"models[{mi}].profiles[{pi}].benchmarks.{kind}",
                        "must be an object",
                    )
                telemetry = benchmark.get("telemetry")
                if telemetry is not None:
                    _validate_energy_telemetry(
                        telemetry,
                        f"models[{mi}].profiles[{pi}].benchmarks.{kind}.telemetry",
                    )
                efficiency = benchmark.get("efficiency")
                if efficiency is not None:
                    _validate_efficiency(
                        efficiency,
                        f"models[{mi}].profiles[{pi}].benchmarks.{kind}.efficiency",
                    )
            if backend.get("id") == "llama_cpp":
                benchmarks = all_benchmarks
                if not isinstance(benchmarks, dict):
                    _fail(f"models[{mi}].profiles[{pi}].benchmarks", "must be an object")
                for kind, benchmark in benchmarks.items():
                    if not isinstance(benchmark, dict):
                        _fail(f"models[{mi}].profiles[{pi}].benchmarks.{kind}", "must be an object")
                    rows = benchmark.get("rows", [])
                    if not isinstance(rows, list):
                        _fail(f"models[{mi}].profiles[{pi}].benchmarks.{kind}.rows", "must be an array")
                    for ri, row in enumerate(rows):
                        if not isinstance(row, dict):
                            _fail(f"models[{mi}].profiles[{pi}].benchmarks.{kind}.rows[{ri}]", "must be an object")
                        if "avg_ts" in row:
                            validate_envelope(row["avg_ts"], f"models[{mi}].profiles[{pi}].benchmarks.{kind}.rows[{ri}].avg_ts", kind="number", unit="tokens/s")


def validate_summary(summary: Any) -> int:
    if not isinstance(summary, dict):
        raise ResultSchemaError("Summary must be an object")
    version = summary.get("schema_version", 1)
    if isinstance(version, bool) or not isinstance(version, int):
        raise ResultSchemaError("Invalid schema_version: expected an integer")
    if version > 3:
        raise ResultSchemaError(f"Unsupported schema_version {version}; update llmbench")
    if version < 1:
        raise ResultSchemaError(f"Invalid schema_version {version}")
    if version == 3:
        _walk_v3(summary)
    return version


def scalar_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Return a scalar projection for existing calculation/report consumers.

    The input remains unchanged and this is idempotent for v1/v2 values.
    """
    version = validate_summary(summary)
    data = copy.deepcopy(summary)
    if version != 3:
        return data
    backend = data.get("backend") or {}
    data["backend"] = backend.get("id")

    def unwrap(value: Any) -> Any:
        if isinstance(value, dict):
            if "value" in value and "source" in value:
                return value["value"]
            return {k: unwrap(v) for k, v in value.items()}
        if isinstance(value, list):
            return [unwrap(v) for v in value]
        return value

    projected = unwrap(data)
    projected["schema_version"] = 2
    projected["_source_schema_version"] = 3
    return projected


def provenance_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract only reference-field provenance for compact public reports."""
    version = validate_summary(summary)
    rows: list[dict[str, Any]] = []

    def add(path: str, item: Any) -> None:
        if isinstance(item, dict) and "value" in item and "source" in item:
            rows.append({**copy.deepcopy(item), "path": path})

    cpu = (summary.get("hardware") or {}).get("cpu") or {}
    if version != 3:
        if "physical_cores" in cpu:
            rows.append({"path": "hardware.cpu.physical_cores", "value": cpu["physical_cores"], "source": None, "status": "unknown", "reason": "legacy_provenance_missing", "unit": "cores"})
        for model in summary.get("models") or []:
            for profile in model.get("profiles") or []:
                settings = profile.get("settings") or {}
                if "gpu_layers" in settings:
                    rows.append({"path": f"{model.get('model', {}).get('name', '?')}/{profile.get('name', '?')}: gpu_layers", "value": settings["gpu_layers"], "source": None, "status": "unknown", "reason": "legacy_provenance_missing", "unit": "layers"})
                capability = profile.get("context_capability") or {}
                if "maximum_verified_context" in capability:
                    rows.append({
                        "path": f"{model.get('model', {}).get('name', '?')}/{profile.get('name', '?')}: maximum_verified_context",
                        "value": capability["maximum_verified_context"],
                        "source": None,
                        "status": "unknown",
                        "reason": "legacy_provenance_missing",
                        "unit": "tokens",
                    })
                for kind, benchmark in (profile.get("benchmarks") or {}).items():
                    for index, row in enumerate(benchmark.get("rows") or []):
                        if "avg_ts" in row:
                            context = row.get("test") or f"row {index}"
                            if row.get("n_depth") is not None:
                                context += f", depth {row['n_depth']}"
                            rows.append({"path": f"{model.get('model', {}).get('name', '?')}/{profile.get('name', '?')}/{kind}/{context}: avg_ts", "value": row["avg_ts"], "source": None, "status": "unknown", "reason": "legacy_provenance_missing", "unit": "tokens/s"})
        return rows
    add("hardware.cpu.physical_cores", cpu.get("physical_cores"))
    for domain in (summary.get("hardware") or {}).get("memory_domains") or []:
        if isinstance(domain, dict):
            for name, item in (domain.get("bandwidth") or {}).items():
                add(f"hardware.memory_domains.{domain.get('id', '?')}.bandwidth.{name}", item)
    for row in (summary.get("telemetry") or {}).get("memory_bandwidth") or []:
        if isinstance(row, dict):
            add(
                f"telemetry.memory_bandwidth.{row.get('domain_id', '?')}.observed_during_benchmark",
                row.get("observed_during_benchmark"),
            )
    for model in summary.get("models") or []:
        for profile in model.get("profiles") or []:
            add(f"{model.get('model', {}).get('name', '?')}/{profile.get('name', '?')}: gpu_layers", (profile.get("settings") or {}).get("gpu_layers"))
            add(
                f"{model.get('model', {}).get('name', '?')}/{profile.get('name', '?')}: maximum_verified_context",
                (profile.get("context_capability") or {}).get("maximum_verified_context"),
            )
            for field, item in (profile.get("kv_cache") or {}).items():
                if field != "backend_details":
                    add(f"{model.get('model', {}).get('name', '?')}/{profile.get('name', '?')}: kv_cache.{field}", item)
            for kind, benchmark in (profile.get("benchmarks") or {}).items():
                telemetry = benchmark.get("telemetry") or {}
                cpu_telemetry = telemetry.get("cpu") or {}
                for field in (
                    "avg_package_power_w",
                    "max_package_power_w",
                    "energy_j",
                    "energy_wh",
                ):
                    add(
                        f"{model.get('model', {}).get('name', '?')}/{profile.get('name', '?')}/{kind}: cpu.{field}",
                        cpu_telemetry.get(field),
                    )
                for gpu_index, gpu in enumerate(telemetry.get("gpus") or []):
                    for field in ("energy_j", "energy_wh"):
                        add(
                            f"{model.get('model', {}).get('name', '?')}/{profile.get('name', '?')}/{kind}: gpu[{gpu_index}].{field}",
                            gpu.get(field) if isinstance(gpu, dict) else None,
                        )
                power = telemetry.get("power") or {}
                for field in (
                    "avg_component_power_w",
                    "max_component_power_w",
                    "component_energy_j",
                    "component_energy_wh",
                    "wall_power_w",
                    "wall_energy_j",
                    "wall_energy_wh",
                ):
                    add(
                        f"{model.get('model', {}).get('name', '?')}/{profile.get('name', '?')}/{kind}: power.{field}",
                        power.get(field),
                    )
                efficiency = benchmark.get("efficiency") or {}
                for field in (
                    "workload_tokens",
                    "tokens_per_joule",
                    "joules_per_1k_tokens",
                    "wh_per_1k_tokens",
                ):
                    add(
                        f"{model.get('model', {}).get('name', '?')}/{profile.get('name', '?')}/{kind}: efficiency.{field}",
                        efficiency.get(field),
                    )
                for index, row in enumerate(benchmark.get("rows") or []):
                    context = row.get("test") or f"row {index}"
                    if row.get("n_depth") is not None:
                        context += f", depth {row['n_depth']}"
                    add(f"{model.get('model', {}).get('name', '?')}/{profile.get('name', '?')}/{kind}/{context}: avg_ts", row.get("avg_ts"))
    return rows


def encode_v3(summary: dict[str, Any], gpu_origins: dict[tuple[str, str], Any] | None = None) -> dict[str, Any]:
    """Copy a live scalar summary into schema v3 without changing the live run."""
    data = copy.deepcopy(summary)
    if data.get("schema_version") == 3:
        validate_summary(data)
        return data
    gpu_origins = gpu_origins or {}
    backend_id = str(data.get("backend") or "llama_cpp")
    data["schema_version"] = 3
    data["backend"] = {"id": backend_id, "name": "llama.cpp" if backend_id == "llama_cpp" else backend_id, "config": {}}
    cpu = (data.get("hardware") or {}).get("cpu")
    if isinstance(cpu, dict):
        value = cpu.get("physical_cores")
        cpu["physical_cores"] = envelope(value, "detected", unit="cores", evidence={"method": "hardware_introspection"}) if value is not None else envelope(None, None, unit="cores", status="unavailable", reason="hardware_not_reported")
    for model in data.get("models") or []:
        model_name = str((model.get("model") or {}).get("name") or "")
        for profile in model.get("profiles") or []:
            settings = profile.get("settings") or {}
            if "gpu_layers" in settings:
                value = settings["gpu_layers"]
                origin = gpu_origins.get((model_name, str(profile.get("name") or "")))
                origin_source = origin if isinstance(origin, str) else origin.get("source") if isinstance(origin, dict) else None
                if origin_source == "requested":
                    settings["gpu_layers"] = envelope(value, "requested", unit="layers", evidence={"method": "user_configuration"})
                elif origin_source == "defaulted":
                    settings["gpu_layers"] = envelope(value, "defaulted", unit="layers", evidence={"method": "configuration_default", "provider": "llmbench"})
                elif origin_source == "calculated" and isinstance(origin, dict):
                    evidence = origin.get("evidence")
                    metadata = evidence.get("metadata") if isinstance(evidence, dict) else None
                    if (
                        isinstance(evidence, dict)
                        and evidence.get("method") == "derived_calculation"
                        and evidence.get("provider") == "llmbench"
                        and isinstance(metadata, dict)
                        and metadata.get("selected_gpu_layers") == value
                    ):
                        settings["gpu_layers"] = envelope(value, "calculated", unit="layers", evidence=evidence)
                    else:
                        settings["gpu_layers"] = envelope(value, None, unit="layers", status="unknown", reason="invalid_calculation_origin")
                else:
                    settings["gpu_layers"] = envelope(value, None, unit="layers", status="unknown", reason="config_origin_unknown")
            capability = profile.get("context_capability")
            if isinstance(capability, dict) and "maximum_verified_context" in capability:
                value = capability["maximum_verified_context"]
                capability["maximum_verified_context"] = (
                    envelope(
                        value,
                        "verified",
                        unit="tokens",
                        evidence={"method": "experimental_validation"},
                    )
                    if value is not None
                    else envelope(
                        None,
                        None,
                        unit="tokens",
                        status="unavailable",
                        reason="no_verified_context_depth",
                    )
                )
            for benchmark in (profile.get("benchmarks") or {}).values():
                telemetry = benchmark.get("telemetry")
                if isinstance(telemetry, dict):
                    _encode_telemetry_energy_v3(telemetry)
                efficiency = benchmark.get("efficiency")
                if isinstance(efficiency, dict):
                    _encode_efficiency_v3(efficiency)
            if backend_id == "llama_cpp":
                for benchmark in (profile.get("benchmarks") or {}).values():
                    for row in benchmark.get("rows") or []:
                        if "avg_ts" in row:
                            value = row["avg_ts"]
                            row["avg_ts"] = (envelope(value, "measured", unit="tokens/s", evidence={"method": "benchmark_measurement"}) if value is not None else envelope(None, None, unit="tokens/s", status="unavailable", reason="measurement_missing"))
    validate_summary(data)
    return data
