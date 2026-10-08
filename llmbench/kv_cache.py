"""Normalized, provenance-aware effective KV-cache observations.

Adapters return small, runtime-specific observations.  This module is the only
place where those observations become the public ``profile.kv_cache`` shape.
It deliberately does not use requested command-line/configuration values as
effective cache data.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from collections.abc import Iterable, Mapping
from typing import Any


KV_CACHE_FIELDS: dict[str, tuple[str, str | None]] = {
    "effective_max_context": ("integer", "tokens"),
    "kv_dtype": ("string", None),
    "k_dtype": ("string", None),
    "v_dtype": ("string", None),
    "memory_allocation": ("integer", "bytes"),
    "token_capacity": ("integer", "tokens"),
    "prefix_caching": ("boolean", None),
    "attention_backend": ("string", None),
    "memory_budget_fraction": ("number", "fraction"),
    "runtime_version": ("string", None),
    "residency": ("string", None),
}

RESIDENCIES = {"gpu", "host", "hybrid", "unknown"}
SOURCES = {"detected", "calculated"}
METHODS = {
    "backend_runtime_introspection",
    "backend_log_parsing",
    "cli_status_output",
    "derived_calculation",
}

# A route being supported means that an inconclusive collection is ``unknown``;
# no route means ``unavailable``.  It is intentionally conservative.
BACKEND_SUPPORT: dict[str, set[str]] = {
    "llama_cpp": {"effective_max_context", "k_dtype", "v_dtype", "runtime_version", "residency"},
    "vllm": {"kv_dtype", "prefix_caching", "memory_allocation", "runtime_version"},
}

# Native observations with backend-specific semantics.  They are deliberately
# not generic comparison fields and their keys use a restricted catalog.
BACKEND_DETAIL_FIELDS: dict[tuple[str, str], tuple[str, str | None]] = {
    ("llama_cpp", "build_number"): ("integer", None),
    ("vllm", "gpu_kv_cache_size_tokens"): ("integer", "tokens"),
    ("vllm", "executor_gpu_memory_budget_fraction"): ("number", "fraction"),
}


@dataclass(frozen=True)
class KvCacheObservation:
    field: str
    value: Any
    source: str = "detected"
    unit: str | None = None
    method: str = "backend_runtime_introspection"
    provider: str = "runtime"
    phase: str = "benchmark"
    metadata: Mapping[str, Any] | None = None
    backend_detail_key: str | None = None


def _safe_text(value: Any, *, limit: int = 120) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > limit or "/" in value or "\\" in value or "://" in value:
        return None
    if re.search(r"(?i)(token|secret|password|api[_-]?key|bearer)", value):
        return None
    return value


def _safe_value(field: str, value: Any) -> Any | None:
    kind, _unit = KV_CACHE_FIELDS[field]
    return _safe_typed_value(kind, field, value)


def _safe_typed_value(kind: str, name: str, value: Any) -> Any | None:
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            return None
        value = float(value)
        return value if 0 <= value <= 1 else None
    if kind == "boolean":
        return value if isinstance(value, bool) else None
    value = _safe_text(value)
    if value is None:
        return None
    if name == "residency" and value not in RESIDENCIES:
        return None
    return value


def _evidence(observation: KvCacheObservation) -> dict[str, Any]:
    evidence: dict[str, Any] = {"method": observation.method if observation.method in METHODS else "backend_runtime_introspection"}
    provider = _safe_text(observation.provider, limit=64)
    if provider:
        evidence["provider"] = provider
    # Scope is diagnostic but not raw logs, paths, commands, or credentials.
    phase = observation.phase if observation.phase in {"startup", "benchmark", "shutdown"} else "benchmark"
    evidence["metadata"] = {"phase": phase}
    return evidence


def _unknown(status: str, reason: str, *, unit: str | None, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"value": None, "source": None, "status": status, "reason": reason}
    if unit is not None:
        item["unit"] = unit
    if evidence:
        item["evidence"] = evidence
    return item


def empty_kv_cache(backend_id: str, *, start_failed: bool = False) -> dict[str, Any]:
    """Return a valid fixed core when collection or normalization is unavailable."""
    supported = BACKEND_SUPPORT.get(backend_id, set())
    result: dict[str, Any] = {}
    for field, (_kind, unit) in KV_CACHE_FIELDS.items():
        if start_failed:
            result[field] = _unknown("unavailable", "backend_start_failed", unit=unit)
        elif field in supported:
            result[field] = _unknown("unknown", "runtime_value_not_observed", unit=unit)
        else:
            result[field] = _unknown("unavailable", "backend_does_not_report_field", unit=unit)
    return result


def normalize_kv_cache(
    backend_id: str,
    observations: Iterable[KvCacheObservation | Mapping[str, Any]],
    *,
    start_failed: bool = False,
) -> dict[str, Any]:
    """Normalize observations without ever raising for malformed adapter data."""
    grouped: dict[str, list[KvCacheObservation]] = {field: [] for field in KV_CACHE_FIELDS}
    details: dict[str, list[KvCacheObservation]] = {}
    for candidate in observations:
        try:
            observation = candidate if isinstance(candidate, KvCacheObservation) else KvCacheObservation(**dict(candidate))
            if observation.source not in SOURCES:
                continue
            if observation.backend_detail_key is not None:
                spec = BACKEND_DETAIL_FIELDS.get((backend_id, observation.backend_detail_key))
                if spec is None or observation.unit != spec[1]:
                    continue
                if _safe_typed_value(spec[0], observation.backend_detail_key, observation.value) is not None:
                    details.setdefault(observation.backend_detail_key, []).append(observation)
            elif observation.field in KV_CACHE_FIELDS:
                expected_unit = KV_CACHE_FIELDS[observation.field][1]
                if observation.unit != expected_unit:
                    continue
                if _safe_value(observation.field, observation.value) is not None:
                    grouped[observation.field].append(observation)
        except (TypeError, ValueError):
            continue

    result = empty_kv_cache(backend_id, start_failed=start_failed)
    for field, (_kind, unit) in KV_CACHE_FIELDS.items():
        if start_failed:
            continue
        candidates = grouped[field]
        direct = [item for item in candidates if item.source == "detected"]
        selected = direct or [item for item in candidates if item.source == "calculated"]
        values: list[Any] = []
        for item in selected:
            value = _safe_value(field, item.value)
            if value not in values:
                values.append(value)
        if len(values) > 1:
            # Bound and sanitize conflict evidence; preserve values/scopes without
            # raw runtime data, commands, file paths, or exception strings.
            conflict = []
            for item in selected[:8]:
                value = _safe_value(field, item.value)
                if value is not None:
                    conflict.append({"value": value, **_evidence(item)})
            result[field] = _unknown(
                "unknown", "conflicting_runtime_observations", unit=unit,
                evidence={"method": "backend_runtime_introspection", "metadata": {"observations": conflict}},
            )
        elif values:
            item = next(item for item in selected if _safe_value(field, item.value) == values[0])
            envelope: dict[str, Any] = {"value": values[0], "source": item.source}
            if unit is not None:
                envelope["unit"] = unit
            envelope["evidence"] = _evidence(item)
            result[field] = envelope
    if not start_failed and details:
        backend_details: dict[str, dict[str, Any]] = {}
        for key, candidates in details.items():
            kind, unit = BACKEND_DETAIL_FIELDS[(backend_id, key)]
            direct = [item for item in candidates if item.source == "detected"]
            selected = direct or [item for item in candidates if item.source == "calculated"]
            detail_values: list[Any] = []
            for item in selected:
                value = _safe_typed_value(kind, key, item.value)
                if value not in detail_values:
                    detail_values.append(value)
            detail_item: dict[str, Any]
            if len(detail_values) > 1:
                conflict = [
                    {"value": _safe_typed_value(kind, key, item.value), **_evidence(item)}
                    for item in selected[:8]
                    if _safe_typed_value(kind, key, item.value) is not None
                ]
                detail_item = _unknown(
                    "unknown", "conflicting_runtime_observations", unit=unit,
                    evidence={"method": "backend_runtime_introspection", "metadata": {"observations": conflict}},
                )
            else:
                chosen = next(item for item in selected if _safe_typed_value(kind, key, item.value) == detail_values[0])
                detail_item = {"value": detail_values[0], "source": chosen.source, "evidence": _evidence(chosen)}
                if unit is not None:
                    detail_item["unit"] = unit
            backend_details.setdefault(backend_id, {})[key] = detail_item
        result["backend_details"] = backend_details
    return result


def kv_cache_scalar_fields(kv_cache: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the common scalar core only; backend details remain JSON-only."""
    values: dict[str, Any] = {}
    for field in KV_CACHE_FIELDS:
        item = (kv_cache or {}).get(field)
        if isinstance(item, Mapping):
            values[field] = item.get("value")
            values[f"{field}_source"] = item.get("source") or item.get("status") or ""
        else:
            values[field] = None
            values[f"{field}_source"] = ""
    return values
