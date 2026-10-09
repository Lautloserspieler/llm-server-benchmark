"""Bounded public tokens and field-specific provenance contracts.

This is a projection catalog, never a blacklist of private fields.
"""
from __future__ import annotations

from llmbench.kv_cache import BACKEND_DETAIL_FIELDS as BACKEND_DETAIL_FIELDS, KV_CACHE_FIELDS as KV_CACHE_FIELDS

STATUSES = {"ok", "partial", "failed", "skipped_capacity", "skipped_quality_gate", "timeout", "skipped", "unknown", "completed"}
FAILURES = {"failed", "partial", "timeout", "skipped_capacity", "skipped_quality_gate", "skipped"}
METHODS = {"user_configuration", "configuration_default", "hardware_introspection", "backend_runtime_introspection", "backend_log_parsing", "cli_status_output", "model_metadata", "derived_calculation", "benchmark_measurement", "experimental_validation", "hardware_energy_counter"}
PROVIDERS = {"llmbench", "runtime", "cpu", "gpu", "nvidia-smi", "nvidia_smi", "psutil", "pynvml", "nvml", "rocm_smi", "rocm-smi", "amd-smi", "apple_official_catalog", "mactop", "sysfs", "rapl", "powercap", "powermetrics", "wall_power_provider", "llama_cpp", "vllm", "wmi", "system_profiler"}
SCOPES = {"measured_components", "wall", "prompt_tokens", "generated_tokens", "benchmark", "startup", "shutdown", "full", "partial", "cpu", "gpu", "cpu_package", "gpu_board", "system", "unknown"}
REASONS = {"unknown_reason", "legacy_provenance_missing", "backend_start_failed", "runtime_value_not_observed", "backend_does_not_report_field", "conflicting_runtime_observations", "hardware_not_reported", "invalid_calculation_origin", "config_origin_unknown", "no_verified_context_depth", "measurement_missing", "cpu_power_sensor_not_available", "cpu_energy_not_available", "gpu_power_samples_not_available", "component_power_not_available", "wall_power_provider_not_configured", "energy_not_available", "workload_tokens_not_available", "insufficient_energy", "no_power_coverage", "no_measured_power", "non_positive_energy", "non_positive_workload_tokens", "no_energy_measurement", "energy_unavailable"}
DTYPES = {"f32", "f16", "bf16", "float32", "float16", "bfloat16", "float", "half", "auto", "fp8", "fp8_e4m3", "fp8_e5m2", "q8_0", "q4_0", "q4_1", "q5_0", "q5_1", "iq4_nl"}
QUANTIZATIONS = DTYPES | {"q2_k", "q3_k", "q3_k_s", "q3_k_m", "q3_k_l", "q4_k", "q4_k_s", "q4_k_m", "q5_k", "q5_k_s", "q5_k_m", "q6_k", "q8_k", "iq1_s", "iq1_m", "iq2_xxs", "iq2_xs", "iq2_s", "iq2_m", "iq3_xxs", "iq3_s", "iq4_xs", "awq", "gptq", "bitsandbytes", "none"}
ATTENTION = {"flash_attn", "flash_attn_v1", "flash_attn_v2", "flash_attn_v3", "flashinfer", "torch_sdpa", "xformers", "triton_attn", "rocm_flash", "flex_attention", "auto", "on", "off", "enabled", "disabled"}
RESIDENCIES = {"gpu", "host", "hybrid", "unknown"}
ENERGY_SOURCES = {"hardware_energy_counter", "sampled_power_integration", "unknown", "unavailable"}

# A kind and the exact persisted unit. Neither strings nor booleans can masquerade as numbers.
ENVELOPES = dict(KV_CACHE_FIELDS)
ENVELOPES.update({
    "gpu_layers": ("layers", "layers"), "physical_cores": ("integer", "cores"),
    "maximum_verified_context": ("integer", "tokens"), "avg_ts": ("number", "tokens/s"),
    "version": ("version", None), "build_number": ("integer", None),
    "theoretical_bandwidth": ("number", "GB/s"), "provider_operating_bandwidth": ("number", "GB/s"), "observed_during_benchmark": ("number", "GB/s"),
    "avg_package_power_w": ("number", "W"), "max_package_power_w": ("number", "W"),
    "avg_component_power_w": ("number", "W"), "max_component_power_w": ("number", "W"), "wall_power_w": ("number", "W"),
    "energy_j": ("number", "J"), "energy_wh": ("number", "Wh"),
    "component_energy_j": ("number", "J"), "component_energy_wh": ("number", "Wh"), "wall_energy_j": ("number", "J"), "wall_energy_wh": ("number", "Wh"),
    "workload_tokens": ("integer", "tokens"), "tokens_per_joule": ("number", "tokens/J"), "joules_per_1k_tokens": ("number", "J/1k tokens"), "wh_per_1k_tokens": ("number", "Wh/1k tokens"),
})
BENCHMARK_CONFIG = {"repetitions", "delay_seconds", "batch_size", "ubatch_size", "flash_attention", "cache_type_k", "cache_type_v", "prompt_tokens", "generation_tokens", "context_depths", "long_context_prompt_tokens", "long_context_generation_tokens", "timeout_seconds", "cpu_timeout_seconds", "gpu_timeout_seconds", "auto_tune", "resource_sample_interval"}
PROFILE_CONFIG = {"gpu_layers", "threads", "batch_size", "ubatch_size", "flash_attention", "cache_type_k", "cache_type_v", "allow_oversized_gpu", "quantization", "gpu_memory_utilization", "dtype"}
ENDPOINT_CONFIG = {"max_tokens", "temperature", "seed", "ignore_eos", "requests_per_level", "context_size", "parallel_slots", "concurrency"}
SOAK_CONFIG = ENDPOINT_CONFIG | {"cpu_concurrency", "gpu_concurrency", "cpu_request_timeout_seconds", "gpu_request_timeout_seconds", "thread_partition_enabled", "available_cpu_threads", "cpu_server_threads", "gpu_server_threads"}
ENERGY_FIELDS = {"power", "efficiency", "energy_j", "energy_wh", "energy_source", "energy_coverage_seconds", "avg_package_power_w", "max_package_power_w", "avg_power_w", "max_power_w"}
TELEMETRY_FIELDS = {"sample_count", "sample_interval_seconds", "avg_cpu_percent", "max_cpu_percent", "avg_ram_bytes", "max_ram_bytes", "avg_utilization_percent", "max_utilization_percent", "avg_frequency_mhz", "min_frequency_mhz", "max_frequency_mhz", "avg_temperature_c", "max_temperature_c", "avg_memory_used_bytes", "max_memory_used_bytes", "memory_total_bytes", "foreign_gpu_load_detected", "baseline_busy"}
CAPABILITY_FIELDS = {"effective_kv_cache", "context_capability", "memory_bandwidth", "domain_references", "theoretical_bandwidth", "provider_operating_bandwidth"}
