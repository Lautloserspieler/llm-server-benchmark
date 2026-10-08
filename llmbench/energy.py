"""Energy-efficiency helpers for benchmark results.

Efficiency is only calculated when both the measured-component energy and the
amount of useful benchmark work are known. Long-context runs are intentionally
excluded for now because their populated-context work is backend-dependent and
must not be guessed.
"""
from __future__ import annotations

from typing import Any


_TOKEN_FIELDS = {
    "prompt": ("n_prompt", "prompt_tokens"),
    "generation": ("n_gen", "generated_tokens"),
}


def _row_repetitions(row: dict[str, Any], default_repetitions: int) -> int | None:
    samples = row.get("samples_ts")
    if isinstance(samples, list) and samples:
        return len(samples)

    value = row.get("repetitions")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value

    if default_repetitions > 0:
        return default_repetitions
    return None


def apply_energy_efficiency(
    result: dict[str, Any],
    *,
    default_repetitions: int = 1,
) -> None:
    """Attach conservative measured-component efficiency metrics in-place.

    Prompt runs count prompt tokens. Generation runs count generated tokens.
    Partial/failed and long-context runs are deliberately left without an
    efficiency claim.
    """
    if result.get("status") != "ok":
        return

    kind = str(result.get("kind") or "")
    token_spec = _TOKEN_FIELDS.get(kind)
    if token_spec is None:
        return

    telemetry = result.get("telemetry") or {}
    power = telemetry.get("power") or {}
    energy_j = power.get("component_energy_j")
    if isinstance(energy_j, bool) or not isinstance(energy_j, (int, float)):
        return
    energy_j = float(energy_j)
    if energy_j <= 0:
        return

    token_field, token_scope = token_spec
    workload_tokens = 0
    for row in result.get("rows") or []:
        if not isinstance(row, dict):
            continue
        token_count = row.get(token_field)
        if isinstance(token_count, bool) or not isinstance(token_count, int) or token_count <= 0:
            continue
        repetitions = _row_repetitions(row, default_repetitions)
        if repetitions is None:
            continue
        workload_tokens += token_count * repetitions

    if workload_tokens <= 0:
        return

    result["efficiency"] = {
        "power_scope": "measured_components",
        "power_coverage": list(power.get("coverage") or []),
        "token_scope": token_scope,
        "workload_tokens": workload_tokens,
        "tokens_per_joule": workload_tokens / energy_j,
        "joules_per_1k_tokens": energy_j * 1000.0 / workload_tokens,
        "wh_per_1k_tokens": (energy_j / 3600.0) * 1000.0 / workload_tokens,
    }
