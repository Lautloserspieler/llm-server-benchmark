#!/usr/bin/env python3
"""Fail if critical calculation/probe modules fall below the branch-coverage floor.

Usage: python scripts/check_module_coverage.py coverage.json [--min 85]

The JSON report comes from ``pytest --cov=llmbench --cov-branch --cov-report=json``.
Modules without any branches are checked on line coverage instead.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Modules whose results feed published numbers (throughput, context capacity,
# energy, telemetry) or that classify backend failures.
CRITICAL_MODULES = (
    "llmbench/backends/http_probe.py",
    "llmbench/backends/ollama.py",
    "llmbench/backends/tgi.py",
    "llmbench/backends/vllm.py",
    "llmbench/context_capability.py",
    "llmbench/energy.py",
    "llmbench/http_bench.py",
    "llmbench/kv_cache.py",
    "llmbench/telemetry.py",
    "llmbench/telemetry_reporting.py",
)


def module_percent(summary: dict) -> float:
    branches = summary.get("num_branches", 0)
    if branches:
        return 100.0 * summary.get("covered_branches", 0) / branches
    return float(summary.get("percent_covered", 0.0))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--min", type=float, default=85.0, dest="minimum")
    args = parser.parse_args(argv)

    files = json.loads(args.report.read_text(encoding="utf-8")).get("files", {})
    normalized = {key.replace("\\", "/"): value for key, value in files.items()}
    failures = []
    for module in CRITICAL_MODULES:
        entry = normalized.get(module)
        if entry is None:
            failures.append(f"{module}: missing from coverage report")
            continue
        percent = module_percent(entry["summary"])
        status = "ok " if percent >= args.minimum else "LOW"
        print(f"[{status}] {module}: {percent:.1f}% branch coverage")
        if percent < args.minimum:
            failures.append(f"{module}: {percent:.1f}% < {args.minimum:.0f}%")
    if failures:
        print("\nBranch coverage below the floor:", *failures, sep="\n  ", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
