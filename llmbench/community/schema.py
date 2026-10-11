"""Closed v1 export document validation and deterministic serialisation."""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import hashlib
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from . import policy
from .identity import validate_label
from .settings import validate_nickname

Outcome = Literal["ok", "partial", "failed", "skipped_capacity", "skipped_quality_gate", "timeout", "skipped", "unknown", "completed"]


class SafeError(ValueError):
    """Only catalog paths/codes may cross the CLI error boundary."""


def _check_envelope(name: str, item: Provenance, spec: tuple[str, str | None] | None = None) -> None:
    kind, unit = spec or policy.ENVELOPES[name]
    if item.unit != unit:
        raise ValueError("invalid_unit")
    value = item.value
    if value is None:
        return
    if kind in {"integer", "layers", "number"}:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("invalid_numeric_value")
        if kind in {"integer", "layers"} and not isinstance(value, int):
            raise ValueError("invalid_integer_value")
        if value < (-1 if kind == "layers" else 0):
            raise ValueError("negative_value")
        if unit == "fraction" and value > 1:
            raise ValueError("invalid_fraction")
    elif kind == "boolean" and not isinstance(value, bool):
        raise ValueError("invalid_boolean_value")
    elif kind in {"string", "version"}:
        if not isinstance(value, str):
            raise ValueError("invalid_text_value")
        if name in {"version", "runtime_version"} and not re.fullmatch(r"[vV]?\d+(?:\.\d+){0,4}(?:[-+][a-zA-Z0-9.]{1,32})?", value):
            raise ValueError("invalid_version")
        tokens = {"kv_dtype": policy.DTYPES, "k_dtype": policy.DTYPES, "v_dtype": policy.DTYPES, "attention_backend": policy.ATTENTION, "residency": policy.RESIDENCIES}.get(name)
        if tokens is not None and value.lower() not in tokens:
            raise ValueError("unsupported_token")


def _safe_errors(exc: ValidationError) -> SafeError:
    known = {name for cls in globals().values() if isinstance(cls, type) and issubclass(cls, BaseModel) for name in cls.model_fields}
    paths = []
    for error in exc.errors(include_input=False, include_context=False, include_url=False)[:8]:
        location = []
        for part in error["loc"]:
            if isinstance(part, int):
                location.append(f"[{part}]")
            elif part in known:
                location.append(("." if location else "") + part)
            else:
                break
        message = error["msg"].removeprefix("Value error, ")
        code = message if re.fullmatch(r"[a-z_]{1,64}", message) else "invalid_field"
        paths.append(f"{''.join(location) or '$'}: {code}" + ("_or_unknown_field" if error["type"] == "extra_forbidden" else ""))
    return SafeError("; ".join(paths))


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    @model_validator(mode="after")
    def catalog_values(self) -> ClosedModel:
        for name in type(self).model_fields:
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, Provenance) and name in policy.ENVELOPES:
                _check_envelope(name, value)
            if name in {"build_commit"} and not re.fullmatch(r"[a-fA-F0-9]{7,64}", value):
                raise ValueError("invalid_commit")
            if name == "id" and type(self).__name__ in {"Profile", "ModelExport", "Gpu", "GpuTelemetry", "MemoryDomain", "DomainReference"}:
                prefix = {"Profile": "profile", "ModelExport": "model", "Gpu": "gpu", "GpuTelemetry": "gpu", "MemoryDomain": "domain", "DomainReference": "domain"}[type(self).__name__]
                if not re.fullmatch(prefix + r"_\d+", value):
                    raise ValueError("invalid_generated_id")
            if isinstance(value, (int, float)) and not isinstance(value, bool) and not isinstance(self, Provenance):
                minimum = -1 if name in {"gpu_layers", "n_gpu_layers"} else (-273.15 if "temperature_c" in name else float("-inf") if name == "tps_drop_fraction" else 0)
                if name not in {"seed"} and value < minimum:
                    raise ValueError("negative_value")
                if "percent" in name and value > 100 and name not in {"avg_cpu_percent", "max_cpu_percent"}:
                    raise ValueError("invalid_percentage")
                if name in {"gpu_memory_utilization", "tps_drop_fraction", "memory_budget_fraction"} and value > 1:
                    raise ValueError("invalid_fraction")
        return self


class Attribution(ClosedModel):
    nickname: str = Field(min_length=1, max_length=64)

    @field_validator("nickname")
    @classmethod
    def safe_nickname(cls, value: str) -> str:
        if value != validate_nickname(value):
            raise ValueError("invalid nickname")
        return value


class Run(ClosedModel):
    started_at: str | None = None
    finished_at: str | None = None
    timestamp_status: Literal["recorded", "partial", "unknown"]
    hardware_target: Literal["cpu", "gpu", "gpu_overload", "both", "unknown"] = "unknown"
    status: Literal["completed", "partial", "failed", "unknown"] = "unknown"

    @model_validator(mode="after")
    def coherent_times(self) -> Run:
        if self.timestamp_status not in {"recorded", "partial", "unknown"}:
            raise ValueError("invalid timestamp status")
        parsed: list[dt.datetime] = []
        for value in (self.started_at, self.finished_at):
            if value is not None:
                if not value.endswith("Z"):
                    raise ValueError("timestamp must be UTC")
                parsed.append(dt.datetime.fromisoformat(value.replace("Z", "+00:00")))
        if len(parsed) == 2 and parsed[1] < parsed[0]:
            raise ValueError("timestamps out of order")
        if self.timestamp_status == "recorded" and len(parsed) != 2:
            raise ValueError("recorded timestamp incomplete")
        if self.timestamp_status == "unknown" and parsed or self.timestamp_status == "partial" and len(parsed) != 1:
            raise ValueError("incoherent_timestamp_status")
        return self


class Fingerprint(ClosedModel):
    algorithm: Literal["sha256", "sha256-shards-v1"]
    scope: Literal["recorded_single_file_content", "recorded_shard_content", "current_artifact_unverified", "exported_configuration_v1"]
    value: str = Field(pattern=r"^[0-9a-f]{64}$")


class Identity(ClosedModel):
    label: str | None = Field(default=None, min_length=1, max_length=128)
    label_source: Literal["user_approved"] | None = None
    public_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}/[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}$")
    revision: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{40,64}$")
    fingerprint: Fingerprint | None = None
    fingerprint_status: Literal["available", "unavailable"]
    exact_identity: Literal["content_fingerprinted", "public_reference", "unverified"]
    size_bytes: int | None = Field(default=None, ge=0)
    shard_count: int | None = Field(default=None, ge=1)

    @field_validator("label")
    @classmethod
    def safe_label(cls, value: str | None) -> str | None:
        if value is not None and value != validate_label(value):
            raise ValueError("invalid label")
        return value

    @model_validator(mode="after")
    def coherent_identity(self) -> Identity:
        if not (self.label or self.public_id or self.fingerprint):
            raise ValueError("missing_model_identity")
        if bool(self.label) != bool(self.label_source):
            raise ValueError("missing_label_approval")
        if (self.fingerprint is not None) != (self.fingerprint_status == "available"):
            raise ValueError("incoherent_fingerprint_status")
        if self.fingerprint and self.fingerprint.scope == "exported_configuration_v1":
            raise ValueError("invalid_model_fingerprint_scope")
        if self.exact_identity == "content_fingerprinted" and (not self.fingerprint or self.fingerprint.scope == "current_artifact_unverified"):
            raise ValueError("unverified_content_identity")
        if self.exact_identity == "public_reference" and not self.public_id:
            raise ValueError("missing_public_reference")
        if self.revision and not self.public_id:
            raise ValueError("revision_without_reference")
        return self


class Provenance(ClosedModel):
    value: int | float | str | bool | None
    source: Literal["requested", "defaulted", "detected", "calculated", "measured", "verified"] | None
    unit: str | None = None
    status: Literal["unknown", "unavailable"] | None = None
    reason: str | None = Field(default=None, pattern=r"^[a-z0-9_]{1,80}$")
    evidence: Evidence | None = None

    @model_validator(mode="after")
    def coherent(self) -> Provenance:
        if self.source is not None and self.source not in {"requested", "defaulted", "detected", "calculated", "measured", "verified"}:
            raise ValueError("invalid provenance source")
        if self.status is not None and self.status not in {"unknown", "unavailable"}:
            raise ValueError("invalid provenance status")
        if self.value is None and (self.source is not None or self.status not in {"unknown", "unavailable"}):
            raise ValueError("null provenance must be unavailable")
        if self.source is None and (self.status not in {"unknown", "unavailable"} or self.reason not in policy.REASONS):
            raise ValueError("missing_provenance_reason")
        if self.source is not None and self.status is not None:
            raise ValueError("known_source_with_unknown_status")
        if self.status == "unavailable" and self.value is not None:
            raise ValueError("unavailable_value_present")
        if self.reason is not None and self.reason not in policy.REASONS:
            raise ValueError("unsupported_reason")
        return self


class CountEnvelope(Provenance):
    value: int | None = Field(ge=0)
    unit: Literal["tokens"]


class LayersEnvelope(Provenance):
    value: int | None = Field(ge=-1)
    unit: Literal["layers"]


class CoresEnvelope(Provenance):
    value: int | None = Field(gt=0)
    unit: Literal["cores"]


class BytesEnvelope(Provenance):
    value: int | None = Field(ge=0)
    unit: Literal["bytes"]


class RateEnvelope(Provenance):
    value: int | float | None = Field(ge=0)
    unit: Literal["tokens/s"]


class BandwidthEnvelope(Provenance):
    value: int | float | None = Field(gt=0)
    unit: Literal["GB/s"]


class WattsEnvelope(Provenance):
    value: int | float | None = Field(ge=0)
    unit: Literal["W"]


class JoulesEnvelope(Provenance):
    value: int | float | None = Field(ge=0)
    unit: Literal["J"]


class WhEnvelope(Provenance):
    value: int | float | None = Field(ge=0)
    unit: Literal["Wh"]


class FractionEnvelope(Provenance):
    value: int | float | None = Field(ge=0, le=1)
    unit: Literal["fraction"]


class TextEnvelope(Provenance):
    value: str | None
    unit: None = None


class BooleanEnvelope(Provenance):
    value: bool | None
    unit: None = None


class IntegerEnvelope(Provenance):
    value: int | None = Field(ge=0)
    unit: None = None


class TokensPerJouleEnvelope(Provenance):
    value: int | float | None
    unit: Literal["tokens/J"]


class JoulesPerThousandEnvelope(Provenance):
    value: int | float | None
    unit: Literal["J/1k tokens"]


class WhPerThousandEnvelope(Provenance):
    value: int | float | None
    unit: Literal["Wh/1k tokens"]


class Evidence(ClosedModel):
    method: str | None = None
    provider: str | None = None
    phase: str | None = None
    coverage: list[str] | None = None
    scope: str | None = None
    selected_gpu_layers: int | None = None
    selected_tps: float | None = None
    successful_candidates: int | None = None
    token_scope: str | None = None
    power_scope: str | None = None
    duration_seconds: float | None = None
    sample_count: int | None = None
    protocol: Literal["mactop-v2-headless-json"] | None = None
    field: Literal["soc_metrics.DRAMBWCombined"] | None = None
    qualifier: Literal["at_current_memory_clock"] | None = None
    catalog_version: str | None = Field(default=None, pattern=r"^\d{4}\.\d{2}$")
    memory_bus_width_bits: int | None = Field(default=None, gt=0)
    max_memory_clock_mhz: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def evidence_catalog(self) -> Evidence:
        if self.method is not None and self.method not in policy.METHODS or self.provider is not None and self.provider not in policy.PROVIDERS:
            raise ValueError("unsupported_evidence_token")
        for value in (self.phase, self.scope, self.token_scope, self.power_scope):
            if value is not None and value not in policy.SCOPES:
                raise ValueError("unsupported_evidence_scope")
        if self.coverage and any(value not in {"cpu_package", "gpu_board", "cpu", "gpu"} and not re.fullmatch(r"gpu_\d+", value) for value in self.coverage):
            raise ValueError("unsupported_coverage")
        return self


class BackendRuntime(ClosedModel):
    version: TextEnvelope | None = None
    build_number: IntegerEnvelope | None = None


class MeasurementTool(ClosedModel):
    id: Literal["llama_bench", "http_bench"]
    build_commit: str | None = None
    build_number: int | None = None
    binary_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class BenchmarkRow(ClosedModel):
    test: str | None = Field(default=None, pattern=r"^(pp\d+|tg\d+|pp\d+\+tg\d+|depth\d+)$")
    n_prompt: int | None = None
    n_gen: int | None = None
    n_depth: int | None = None
    n_threads: int | None = None
    n_gpu_layers: int | None = None
    avg_ts: float | RateEnvelope | None = None
    stddev_ts: float | None = None
    model_n_params: float | None = None
    model_size: float | None = None
    build_commit: str | None = None
    build_number: int | None = None
    status: Outcome | None = None
    repetitions: int | None = Field(default=None, ge=1)


class Benchmark(ClosedModel):
    rows: list[BenchmarkRow] = Field(default_factory=list)
    status: Outcome | None = None
    failure_reason: Literal["capacity", "timeout", "failure_reason_unknown"] | None = None
    telemetry: Telemetry | None = None
    efficiency: Efficiency | None = None


class Efficiency(ClosedModel):
    measurement_scope: Literal["prompt_tokens", "generated_tokens"] | None = None
    power_scope: Literal["measured_components"] | None = None
    energy_coverage: list[str] = Field(default_factory=list)
    workload_tokens: CountEnvelope | None = None
    tokens_per_joule: TokensPerJouleEnvelope | None = None
    joules_per_1k_tokens: JoulesPerThousandEnvelope | None = None
    wh_per_1k_tokens: WhPerThousandEnvelope | None = None


class CurvePoint(ClosedModel):
    populated_context: int = Field(ge=0)
    prefill_tps: float | None = None
    decode_tps: float | None = None
    combined_tps: float | None = None
    result: Literal["pass", "oom", "timeout", "failed", "partial", "unknown"]


class ContextCapability(ClosedModel):
    maximum_verified_context: CountEnvelope | None = None
    requested_context_depths: list[int] = Field(default_factory=list)
    completed_context_depths: list[int] = Field(default_factory=list)
    first_failed_context: int | None = None
    limit_status: Literal["ok", "partial", "failed", "skipped_capacity", "timeout", "unknown", "completed"] | None = None

    @model_validator(mode="after")
    def coherent_curve(self) -> ContextCapability:
        requested, completed = self.requested_context_depths, self.completed_context_depths
        if any(value < 0 for value in requested + completed) or len(set(requested)) != len(requested) or len(set(completed)) != len(completed):
            raise ValueError("invalid_context_depths")
        if not set(completed) <= set(requested):
            raise ValueError("unrequested_completed_depth")
        curve_depths = [point.populated_context for point in self.curve]
        if len(set(curve_depths)) != len(curve_depths) or not set(curve_depths) <= set(requested):
            raise ValueError("invalid_curve_depths")
        if {point.populated_context for point in self.curve if point.result == "pass"} != set(completed):
            raise ValueError("incoherent_completed_curve")
        maximum = self.maximum_verified_context
        if maximum and maximum.value is not None and (maximum.source not in {"verified", None} or not completed or maximum.value != max(completed)):
            raise ValueError("incoherent_verified_maximum")
        if self.first_failed_context is not None and (self.first_failed_context not in requested or self.first_failed_context in completed):
            raise ValueError("incoherent_failed_boundary")
        return self
    curve: list[CurvePoint] = Field(default_factory=list)


class Settings(ClosedModel):
    repetitions: int | None = None
    delay_seconds: float | None = None
    batch_size: int | None = None
    ubatch_size: int | None = None
    flash_attention: bool | str | None = None
    cache_type_k: str | None = None
    cache_type_v: str | None = None
    prompt_tokens: int | list[int] | None = None
    generation_tokens: int | list[int] | None = None
    context_depths: list[int] | None = None
    long_context_prompt_tokens: int | None = None
    long_context_generation_tokens: int | None = None
    timeout_seconds: float | None = None
    cpu_timeout_seconds: float | None = None
    gpu_timeout_seconds: float | None = None
    auto_tune: bool | None = None
    resource_sample_interval: float | None = None
    gpu_layers: int | LayersEnvelope | None = None
    threads: int | None = None
    allow_oversized_gpu: bool | None = None
    quantization: str | None = None
    gpu_memory_utilization: float | None = None
    dtype: str | None = None

    @model_validator(mode="after")
    def settings_catalog(self) -> Settings:
        for field, tokens in (("cache_type_k", policy.DTYPES), ("cache_type_v", policy.DTYPES), ("quantization", policy.QUANTIZATIONS), ("dtype", policy.DTYPES)):
            value = getattr(self, field)
            if value is not None and value.lower() not in tokens:
                raise ValueError("unsupported_setting_token")
        if isinstance(self.flash_attention, str) and self.flash_attention not in {"on", "off", "auto", "enabled", "disabled"}:
            raise ValueError("unsupported_attention_token")
        for field in ("prompt_tokens", "generation_tokens", "context_depths"):
            value = getattr(self, field)
            if isinstance(value, list) and any(item < 0 for item in value):
                raise ValueError("negative_setting_value")
        for field in ("repetitions", "batch_size", "ubatch_size", "threads"):
            if getattr(self, field) == 0:
                raise ValueError("positive_setting_required")
        return self


class EndpointSettings(ClosedModel):
    max_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = None
    seed: int | None = None
    ignore_eos: bool | None = None
    requests_per_level: int | None = Field(default=None, ge=1)
    context_size: int | None = Field(default=None, ge=1)
    parallel_slots: int | None = Field(default=None, ge=1)
    concurrency: int | list[int] | None = None

    @field_validator("concurrency")
    @classmethod
    def positive_concurrency(cls, value: int | list[int] | None) -> int | list[int] | None:
        if value is not None and any(item < 1 for item in (value if isinstance(value, list) else [value])):
            raise ValueError("invalid_concurrency")
        return value


class LoadSettings(EndpointSettings):
    cpu_concurrency: int | None = Field(default=None, ge=1)
    gpu_concurrency: int | None = Field(default=None, ge=1)
    cpu_request_timeout_seconds: float | None = Field(default=None, gt=0)
    gpu_request_timeout_seconds: float | None = Field(default=None, gt=0)
    thread_partition_enabled: bool | None = None
    available_cpu_threads: int | None = Field(default=None, ge=1)
    cpu_server_threads: int | None = Field(default=None, ge=1)
    gpu_server_threads: int | None = Field(default=None, ge=1)


class Benchmarks(ClosedModel):
    prompt: Benchmark | None = None
    generation: Benchmark | None = None
    long_context: Benchmark | None = None


class Profile(ClosedModel):
    id: str
    configured_settings: Settings
    benchmarks: Benchmarks
    effective_kv_cache: KvCache | None = None
    context_capability: ContextCapability | None = None


class EndpointLevel(ClosedModel):
    concurrency: int | None = Field(default=None, ge=1)
    requests: int | None = None
    successful: int | None = None
    failed: int | None = None
    wall_seconds: float | None = None
    total_output_tokens: int | None = None
    system_tps: float | None = None
    avg_interactivity_tps: float | None = None
    ttft_p50_seconds: float | None = None
    ttft_p95_seconds: float | None = None
    short_responses: int | None = None


class Endpoint(ClosedModel):
    status: Outcome
    duration_seconds: float | None = None
    settings: EndpointSettings | None = None
    warmup_requests: int | None = Field(default=None, ge=0)
    warmup_successful: int | None = Field(default=None, ge=0)
    levels: list[EndpointLevel] = Field(default_factory=list)
    telemetry: Telemetry | None = None


class SoakSide(ClosedModel):
    requests: int | None = None
    successful: int | None = None
    failed: int | None = None
    total_output_tokens: int | None = None
    avg_tps: float | None = None
    early_window_avg_tps: float | None = None
    late_window_avg_tps: float | None = None
    tps_drop_fraction: float | None = None
    throttling_suspected: bool | None = None


class Stability(ClosedModel):
    kind: Literal["soak", "standard", "short", "long", "unknown"] | None = None
    label: Literal["short", "long", "standard"] | None = None
    status: Outcome
    duration_seconds: float | None = None
    requested_duration_seconds: float | None = None
    throttling_suspected: bool | None = None
    load_settings: LoadSettings | None = None
    cpu_profile_id: str | None = None
    gpu_profile_id: str | None = None
    cpu: SoakSide | None = None
    gpu: SoakSide | None = None
    telemetry: Telemetry | None = None


class KvCache(ClosedModel):
    effective_max_context: CountEnvelope | None = None
    kv_dtype: TextEnvelope | None = None
    k_dtype: TextEnvelope | None = None
    v_dtype: TextEnvelope | None = None
    memory_allocation: BytesEnvelope | None = None
    token_capacity: CountEnvelope | None = None
    prefix_caching: BooleanEnvelope | None = None
    attention_backend: TextEnvelope | None = None
    memory_budget_fraction: FractionEnvelope | None = None
    runtime_version: TextEnvelope | None = None
    residency: TextEnvelope | None = None
    backend_details: list[BackendDetail] = Field(default_factory=list)


class BackendDetail(ClosedModel):
    backend: Literal["llama_cpp", "vllm"]
    field: str
    value: Provenance

    @model_validator(mode="after")
    def detail_catalog(self) -> BackendDetail:
        spec = policy.BACKEND_DETAIL_FIELDS.get((self.backend, self.field))
        if spec is None:
            raise ValueError("unsupported_backend_detail")
        _check_envelope(self.field, self.value, spec)
        return self


class ModelExport(ClosedModel):
    id: str
    identity: Identity
    profiles: list[Profile]
    endpoint: Endpoint | None = None
    stability: list[Stability] | None = None
    status: Outcome | None = None
    failure_reason: Literal["capacity", "timeout", "failure_reason_unknown"] | None = None
    quality_gate: Literal["passed", "failed", "skipped", "unknown", "ok", "partial", "skipped_quality_gate"] | None = None
    telemetry: Telemetry | None = None


class Backend(ClosedModel):
    id: Literal["llama_cpp", "vllm"]
    runtime: BackendRuntime | None = None
    measurement_tool: MeasurementTool | None = None
    container_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")


class Cpu(ClosedModel):
    product_name: str | None = None
    physical_cores: CoresEnvelope | None = None
    logical_cores: int | None = None
    max_frequency_mhz: float | None = None


class Gpu(ClosedModel):
    id: str
    vendor: Literal["NVIDIA", "AMD", "Intel", "Apple", "unknown"] | None = None
    product_name: str | None = None
    driver_version: str | None = Field(default=None, pattern=r"^\d+(?:\.\d+){0,5}$")
    memory_bytes: int | None = None
    power_limit_w: float | None = None
    compute_capability: str | None = Field(default=None, pattern=r"^\d+(?:\.\d+){0,2}$")


class MemoryDomain(ClosedModel):
    id: str
    kind: Literal["dram", "vram", "unified", "host", "gpu", "unknown", "discrete_vram", "unified_memory"] | None = None
    vendor: Literal["NVIDIA", "AMD", "Intel", "Apple", "unknown"] | None = None
    capacity_bytes: int | None = None
    theoretical_bandwidth: BandwidthEnvelope | None = None
    provider_operating_bandwidth: BandwidthEnvelope | None = None
    device_id: str | None = Field(default=None, pattern=r"^gpu_\d+$")


class Hardware(ClosedModel):
    os_family: Literal["Windows", "Linux", "Darwin"] | None = None
    os_version: str | None = Field(default=None, pattern=r"^\d+(?:\.\d+){0,4}$")
    architecture: Literal["x86_64", "aarch64", "arm64", "x86", "armv7l"] | None = None
    cpu: Cpu | None = None
    memory_total_bytes: int | None = None
    gpus: list[Gpu] = Field(default_factory=list)
    memory_domains: list[MemoryDomain] = Field(default_factory=list)


class Power(ClosedModel):
    scope: Literal["measured_components", "wall", "unknown"] | None = None
    coverage: list[str] = Field(default_factory=list)
    avg_component_power_w: float | WattsEnvelope | None = None
    max_component_power_w: float | WattsEnvelope | None = None
    component_energy_j: JoulesEnvelope | None = None
    component_energy_wh: WhEnvelope | None = None
    wall_energy_j: JoulesEnvelope | None = None
    wall_energy_wh: WhEnvelope | None = None
    wall_power_w: WattsEnvelope | None = None


class Telemetry(ClosedModel):
    sample_count: int | None = None
    sample_interval_seconds: float | None = None
    avg_cpu_percent: float | None = None
    max_cpu_percent: float | None = None
    avg_ram_bytes: int | None = None
    max_ram_bytes: int | None = None
    power: Power | None = None
    cpu: CpuTelemetry | None = None
    gpus: list[GpuTelemetry] = Field(default_factory=list)
    memory_bandwidth: list[BandwidthObservation] = Field(default_factory=list)
    domain_references: list[DomainReference] = Field(default_factory=list)
    foreign_gpu_load_detected: bool | None = None
    baseline_busy: bool | None = None


class CpuTelemetry(ClosedModel):
    avg_utilization_percent: float | None = None
    max_utilization_percent: float | None = None
    avg_frequency_mhz: float | None = None
    min_frequency_mhz: float | None = None
    max_frequency_mhz: float | None = None
    avg_temperature_c: float | None = None
    max_temperature_c: float | None = None
    avg_package_power_w: WattsEnvelope | None = None
    max_package_power_w: WattsEnvelope | None = None
    energy_j: JoulesEnvelope | None = None
    energy_wh: WhEnvelope | None = None
    energy_source: Literal["hardware_energy_counter", "sampled_power_integration", "unknown", "unavailable"] | None = None
    energy_coverage_seconds: float | None = None


class GpuTelemetry(ClosedModel):
    id: str
    avg_utilization_percent: float | None = None
    max_utilization_percent: float | None = None
    avg_memory_used_bytes: int | None = None
    max_memory_used_bytes: int | None = None
    memory_total_bytes: int | None = None
    avg_power_w: float | None = None
    max_power_w: float | None = None
    max_temperature_c: float | None = None
    energy_j: JoulesEnvelope | None = None
    energy_wh: WhEnvelope | None = None
    energy_source: Literal["hardware_energy_counter", "sampled_power_integration", "unknown", "unavailable"] | None = None
    energy_coverage_seconds: float | None = None


class BandwidthObservation(ClosedModel):
    domain_id: str
    observed_during_benchmark: BandwidthEnvelope | None = None


class DomainReference(ClosedModel):
    id: str
    kind: Literal["dram", "vram", "unified", "host", "gpu", "unknown"] | None = None


class Configuration(ClosedModel):
    values: Settings
    fingerprint: Fingerprint
    completeness: Literal["retained_configured_fields"] = "retained_configured_fields"


class CommunityExport(ClosedModel):
    export_schema_version: Literal[1]
    source_schema_version: Literal[1, 2, 3]
    llmbench_version: str | None = Field(default=None, pattern=r"^\d+(?:\.\d+){1,3}(?:[-+][a-zA-Z0-9.]{1,32})?$")
    run: Run
    backend: Backend
    models: list[ModelExport] = Field(min_length=1)
    omitted_groups: list[str]
    attribution: Attribution | None = None
    benchmark_configuration: Configuration | None = None
    hardware: Hardware | None = None
    telemetry: Telemetry | None = None

    @field_validator("export_schema_version", "source_schema_version", mode="before")
    @classmethod
    def strict_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("invalid_schema_version")
        return value

    @model_validator(mode="after")
    def minimum_outcome(self) -> CommunityExport:
        if self.export_schema_version != 1:
            raise ValueError("unsupported export schema")
        if isinstance(self.source_schema_version, bool) or self.source_schema_version not in {1, 2, 3}:
            raise ValueError("unsupported source schema")
        if self.run.timestamp_status not in {"recorded", "partial", "unknown"}:
            raise ValueError("invalid timestamp status")
        if any(group not in {"hardware", "energy", "capabilities", "telemetry"} for group in self.omitted_groups):
            raise ValueError("invalid omitted group")
        if len(set(self.omitted_groups)) != len(self.omitted_groups):
            raise ValueError("duplicate omitted group")
        for model in self.models:
            has_outcome = any(
                benchmark is not None and (any((row.avg_ts.value is not None if isinstance(row.avg_ts, Provenance) else row.avg_ts is not None) for row in benchmark.rows) or benchmark.status in policy.FAILURES or any(row.status in policy.FAILURES for row in benchmark.rows))
                for profile in model.profiles
                for benchmark in (profile.benchmarks.prompt, profile.benchmarks.generation, profile.benchmarks.long_context)
            )
            has_outcome = has_outcome or bool(model.endpoint and (any(level.system_tps is not None or level.avg_interactivity_tps is not None or level.failed for level in model.endpoint.levels) or model.endpoint.status in policy.FAILURES)) or any((item.cpu and item.cpu.avg_tps is not None) or (item.gpu and item.gpu.avg_tps is not None) or item.status in policy.FAILURES for item in model.stability or [])
            has_failure = model.status in policy.FAILURES
            if not has_outcome and not has_failure:
                raise ValueError("model lacks a measurement or structured outcome")
            for profile in model.profiles:
                if profile.context_capability is not None:
                    context = profile.context_capability
                    if any(value < 0 for value in context.requested_context_depths + context.completed_context_depths):
                        raise ValueError("negative context depth")
                    maximum = context.maximum_verified_context
                    if maximum and isinstance(maximum.value, int) and maximum.value not in context.completed_context_depths:
                        raise ValueError("verified context was not completed")
            if model.endpoint is not None:
                for level in model.endpoint.levels:
                    if level.requests is not None and level.successful is not None and level.failed is not None and level.successful + level.failed > level.requests:
                        raise ValueError("endpoint counts are incoherent")
            for soak in model.stability or []:
                if any(reference is not None and reference not in {profile.id for profile in model.profiles} for reference in (soak.cpu_profile_id, soak.gpu_profile_id)):
                    raise ValueError("unresolved_profile_reference")
                for side in (soak.cpu, soak.gpu):
                    if side and side.requests is not None and side.successful is not None and side.failed is not None and side.successful + side.failed > side.requests:
                        raise ValueError("stability counts are incoherent")
        if len({model.id for model in self.models}) != len(self.models):
            raise ValueError("duplicate_model_id")
        for model in self.models:
            if len({profile.id for profile in model.profiles}) != len(model.profiles):
                raise ValueError("duplicate_profile_id")
        domains = {domain.id for domain in self.hardware.memory_domains} if self.hardware else set()
        devices = {gpu.id for gpu in self.hardware.gpus} if self.hardware else set()
        if self.hardware:
            if len(domains) != len(self.hardware.memory_domains) or len(devices) != len(self.hardware.gpus):
                raise ValueError("duplicate_hardware_id")
            if any(domain.device_id is not None and domain.device_id not in devices for domain in self.hardware.memory_domains):
                raise ValueError("unresolved_device_reference")
        def inspect(item: object) -> None:
            if isinstance(item, Telemetry):
                refs = {reference.id for reference in item.domain_references}
                if any(observation.domain_id not in domains | refs for observation in item.memory_bandwidth):
                    raise ValueError("unresolved_domain_reference")
                if self.hardware and any(gpu.id not in devices for gpu in item.gpus):
                    raise ValueError("unresolved_gpu_reference")
            if isinstance(item, BaseModel):
                for name in type(item).model_fields:
                    value = getattr(item, name)
                    present = value is not None and value != []
                    if present and (("energy" in self.omitted_groups and name in policy.ENERGY_FIELDS) or ("capabilities" in self.omitted_groups and name in policy.CAPABILITY_FIELDS) or ("telemetry" in self.omitted_groups and name in policy.TELEMETRY_FIELDS)):
                        raise ValueError("excluded_metric_present")
                    inspect(value)
            elif isinstance(item, list):
                for child in item:
                    inspect(child)
        if "hardware" in self.omitted_groups and self.hardware is not None:
            raise ValueError("excluded_hardware_present")
        inspect(self)
        if self.benchmark_configuration:
            fingerprint = self.benchmark_configuration.fingerprint
            if fingerprint.scope != "exported_configuration_v1" or fingerprint.algorithm != "sha256":
                raise ValueError("invalid_configuration_fingerprint")
            from .project import json_bytes_for_configuration, json_bytes
            canonical = json_bytes_for_configuration(json.loads(serialize(self)))
            if hashlib.sha256(json_bytes(canonical)).hexdigest() != fingerprint.value:
                raise ValueError("incoherent_configuration_fingerprint")
        return self


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON values are not supported")


def parse_document(text: str) -> CommunityExport:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    try:
        raw = json.loads(text, object_pairs_hook=pairs, parse_constant=_reject_constant)
        return validate_export(raw)
    except SafeError:
        raise
    except ValueError as exc:
        raise SafeError("$: invalid_json") from exc


def validate_export(raw: object) -> CommunityExport:
    try:
        return CommunityExport.model_validate(raw)
    except ValidationError as exc:
        raise _safe_errors(exc) from exc


def serialize(document: CommunityExport | Mapping[str, object]) -> bytes:
    raw = document.model_dump(mode="json", exclude_none=False) if isinstance(document, CommunityExport) else dict(document)
    def compact(value: object) -> object:
        if isinstance(value, dict):
            return {item_key: compact(item) for item_key, item in value.items() if (item is not None or item_key in {"value", "source"}) and not (item == [] and item_key in {"memory_bandwidth", "domain_references", "backend_details"})}
        if isinstance(value, list):
            return [compact(item) for item in value]
        return value
    data = compact(raw)
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def json_schema() -> dict[str, object]:
    schema = CommunityExport.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://llmbench.local/schemas/community-export-v1.schema.json"
    for definition in schema.get("$defs", {}).values():
        properties = definition.get("properties", {})
        if "reason" in properties:
            properties["reason"] = {"anyOf": [{"type": "string", "enum": sorted(policy.REASONS)}, {"type": "null"}], "default": None}
    evidence = schema["$defs"]["Evidence"]["properties"]
    for field, tokens in (("method", policy.METHODS), ("provider", policy.PROVIDERS), ("phase", policy.SCOPES), ("scope", policy.SCOPES), ("power_scope", policy.SCOPES), ("token_scope", policy.SCOPES)):
        evidence[field] = {"anyOf": [{"type": "string", "enum": sorted(tokens)}, {"type": "null"}], "default": None}
    return schema
