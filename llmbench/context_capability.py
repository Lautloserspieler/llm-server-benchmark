"""Normalize long-context benchmark results into explicit capability data."""

from __future__ import annotations

from typing import Any


def _as_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _boundary_result(result: dict[str, Any]) -> str:
    limit_status = str(result.get("limit_status") or result.get("status") or "")
    if bool(result.get("capacity_limited")) or limit_status == "skipped_capacity":
        return "oom"
    if limit_status == "timeout":
        return "timeout"
    if limit_status in {"failed", "partial"}:
        return "failed"
    return limit_status or "unknown"


def build_context_capability(result: dict[str, Any]) -> dict[str, Any]:
    """Build a normalized context-capability summary from a long-context result.

    A depth is verified only after prompt processing and text generation both
    completed for that populated context. Partial rows remain visible in the
    curve but never raise the maximum verified context.
    """
    rows = result.get("rows") or []
    grouped: dict[int, dict[str, Any]] = {}
    parts: dict[int, set[str]] = {}

    for row in rows:
        if not isinstance(row, dict):
            continue
        depth = _as_int(row.get("n_depth"))
        if depth is None or depth < 0:
            continue
        entry = grouped.setdefault(
            depth,
            {
                "populated_context": depth,
                "prefill_tps": None,
                "decode_tps": None,
                "combined_tps": None,
                "result": "partial",
            },
        )
        seen = parts.setdefault(depth, set())
        n_prompt = _as_int(row.get("n_prompt")) or 0
        n_gen = _as_int(row.get("n_gen")) or 0
        avg_ts = _as_number(row.get("avg_ts"))

        if n_prompt > 0:
            seen.add("prompt")
        if n_gen > 0:
            seen.add("generation")

        if n_prompt > 0 and n_gen == 0:
            entry["prefill_tps"] = avg_ts
        elif n_gen > 0 and n_prompt == 0:
            entry["decode_tps"] = avg_ts
        elif n_prompt > 0 and n_gen > 0:
            entry["combined_tps"] = avg_ts

    completed = sorted(
        depth
        for depth, seen in parts.items()
        if {"prompt", "generation"}.issubset(seen)
    )
    for depth, entry in grouped.items():
        if depth in completed:
            entry["result"] = "pass"

    requested: list[int] = []
    for value in result.get("requested_context_depths") or []:
        depth = _as_int(value)
        if depth is not None and depth >= 0 and depth not in requested:
            requested.append(depth)
    requested.sort()

    failed_depth = _as_int(result.get("failed_context_depth"))
    if failed_depth is not None and failed_depth >= 0:
        boundary_result = _boundary_result(result)
        if failed_depth not in grouped:
            grouped[failed_depth] = {
                "populated_context": failed_depth,
                "prefill_tps": None,
                "decode_tps": None,
                "combined_tps": None,
                "result": boundary_result,
            }
        elif grouped[failed_depth]["result"] != "pass":
            grouped[failed_depth]["result"] = boundary_result

    curve = [grouped[depth] for depth in sorted(grouped)]
    maximum_verified = max(completed) if completed else None

    return {
        "maximum_verified_context": maximum_verified,
        "completed_context_depths": completed,
        "requested_context_depths": requested,
        "first_failed_context": failed_depth,
        "limit_status": result.get("limit_status"),
        "curve": curve,
    }
