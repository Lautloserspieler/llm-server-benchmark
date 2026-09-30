from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .base import BenchmarkBackend
from ..capacity import CapacityLimitError, profile_vram_issue_for_path
from ..endpoint import (
    start_llama_server,
    stop_llama_server,
    wait_health,
)
from ..llama_bench import run_llama_bench


VRAM_RELEASE_TIMEOUT_SECONDS = 12.0
VRAM_RELEASE_TOLERANCE_MIB = 96.0


def _available_cpu_threads() -> int:
    """Return the logical CPUs that this process is actually allowed to use.

    On Linux ``os.cpu_count()`` can include CPUs hidden by taskset/cgroups.  The
    scheduler affinity is therefore the best source for CPU-only benchmark
    profiles.  psutil is a fallback for platforms without sched_getaffinity.
    """
    with contextlib.suppress(AttributeError, OSError):
        affinity = os.sched_getaffinity(0)
        if affinity:
            return len(affinity)

    with contextlib.suppress(Exception):
        import psutil

        affinity = psutil.Process().cpu_affinity()
        if affinity:
            return len(affinity)

    return max(1, int(os.cpu_count() or 1))


def _is_cpu_profile(profile: dict[str, Any]) -> bool:
    try:
        return int(profile.get("gpu_layers", -1)) == 0
    except (TypeError, ValueError):
        return False


def _is_gpu_profile(profile: dict[str, Any]) -> bool:
    value = profile.get("gpu_layers", -1)
    return str(value).strip().lower() not in {"0", "none"}


def _runtime_profile(profile: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Create the profile that is passed to llama.cpp.

    Only settings that can be resolved without changing benchmark semantics are
    adjusted here. In particular, an oversized Full-GPU profile is *not*
    converted to ``gpu_layers='auto'``: llama-bench expects a numeric ``-ngl``
    value and recent builds reject the string ``auto``. Capacity handling is
    therefore performed explicitly by the backend before launching llama.cpp.
    """
    runtime = dict(profile)
    adjustments: list[dict[str, Any]] = []

    threads = runtime.get("threads", "auto")
    if _is_cpu_profile(runtime) and threads in (None, "auto", -1, "-1"):
        resolved = _available_cpu_threads()
        runtime["threads"] = resolved
        adjustments.append({
            "type": "cpu_threads",
            "requested": threads,
            "effective": resolved,
            "reason": "CPU-only benchmark uses all logical CPUs allowed by the OS affinity mask.",
        })

    return runtime, adjustments


def _capacity_adjustment(
    profile: dict[str, Any],
    reason: str,
    *,
    attempted: bool = False,
) -> dict[str, Any]:
    return {
        "type": "capacity_preflight",
        "requested": profile.get("gpu_layers", -1),
        "effective": "attempted_oversized_gpu" if attempted else None,
        "reason": reason,
    }


def _strict_capacity_issue(model_path: str, profile: dict[str, Any]) -> str | None:
    """Run the normal VRAM preflight even when overload mode bypasses it."""
    strict_profile = dict(profile)
    strict_profile.pop("allow_oversized_gpu", None)
    return profile_vram_issue_for_path(model_path, strict_profile)


def _looks_like_capacity_failure(result: dict[str, Any]) -> bool:
    if result.get("status") == "timeout":
        return True
    text = " ".join(
        str(result.get(key) or "")
        for key in ("error", "error_detail", "stderr_tail")
    ).lower()
    markers = (
        "failed to load model",
        "out of memory",
        "cuda out of memory",
        "failed to allocate",
        "allocation failed",
        "insufficient memory",
        "not enough memory",
    )
    return any(marker in text for marker in markers)


def _nvidia_vram_used_mib() -> float | None:
    """Return aggregate NVIDIA VRAM usage, or None when nvidia-smi is absent."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        cp = subprocess.run(
            [exe, "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except Exception:
        return None
    if cp.returncode != 0:
        return None

    values: list[float] = []
    for line in (cp.stdout or "").splitlines():
        text = line.strip().split()[0] if line.strip() else ""
        with contextlib.suppress(ValueError):
            values.append(float(text))
    return sum(values) if values else None


def _wait_for_vram_release(baseline_mib: float | None) -> None:
    """Wait briefly until CUDA allocations from the previous run are gone.

    llama.cpp processes normally release VRAM immediately at exit, but on Linux
    the NVIDIA driver can report the old allocation for a short moment. Starting
    the next model in that window can make its memory-fit decision too small.
    """
    if baseline_mib is None:
        return

    deadline = time.monotonic() + VRAM_RELEASE_TIMEOUT_SECONDS
    target = baseline_mib + VRAM_RELEASE_TOLERANCE_MIB
    stable_samples = 0
    while time.monotonic() < deadline:
        current = _nvidia_vram_used_mib()
        if current is None:
            return
        if current <= target:
            stable_samples += 1
            if stable_samples >= 2:
                return
        else:
            stable_samples = 0
        time.sleep(0.25)


class LlamaCppBackend(BenchmarkBackend):
    """Implementation of the benchmark backend for llama.cpp."""

    def __init__(self, llama_bench_exe: str, llama_server_exe: str):
        self.llama_bench_exe = llama_bench_exe
        self.llama_server_exe = llama_server_exe

    def run_benchmark(
        self,
        model_path: str,
        profile: dict[str, Any],
        kind: str,
        out_dir: Path,
        bench_cfg: dict[str, Any],
        on_progress=None,
    ) -> dict[str, Any]:
        capacity_issue = profile_vram_issue_for_path(model_path, profile)
        if capacity_issue:
            return {
                "kind": kind,
                "status": "skipped_capacity",
                "error": capacity_issue,
                "runtime_adjustments": [_capacity_adjustment(profile, capacity_issue)],
            }

        strict_capacity_issue = _strict_capacity_issue(model_path, profile)
        overload_attempt = bool(profile.get("allow_oversized_gpu") and strict_capacity_issue)

        runtime_profile, adjustments = _runtime_profile(profile)
        baseline_mib = _nvidia_vram_used_mib() if _is_gpu_profile(runtime_profile) else None
        try:
            result = run_llama_bench(
                self.llama_bench_exe,
                model_path,
                bench_cfg,
                runtime_profile,
                kind,
                out_dir,
                on_progress=on_progress,
            )
        finally:
            _wait_for_vram_release(baseline_mib)

        if overload_attempt and _looks_like_capacity_failure(result):
            original_status = result.get("status")
            result = dict(result)
            result["status"] = "skipped_capacity"
            result["overload_original_status"] = original_status
            result["overload_attempted"] = True
            result["error"] = (
                "GPU-Overload wurde bewusst versucht, konnte das Modell aber nicht "
                "innerhalb der verfuegbaren VRAM-/Unified-Memory-Grenzen laden oder "
                "abschliessen. " + str(strict_capacity_issue)
            )
            adjustments.append(
                _capacity_adjustment(profile, str(strict_capacity_issue), attempted=True)
            )
        elif overload_attempt:
            result = dict(result)
            result["overload_attempted"] = True
            warnings = list(result.get("warnings") or [])
            warnings.append(
                "GPU-Overload-Modus aktiv: Das Modell ueberschreitet den konservativen "
                "VRAM-Preflight, der erzwungene Versuch war jedoch erfolgreich."
            )
            result["warnings"] = warnings
            adjustments.append(
                _capacity_adjustment(profile, str(strict_capacity_issue), attempted=True)
            )

        if adjustments:
            result = dict(result)
            result["runtime_adjustments"] = adjustments
        return result

    def start_server(
        self,
        model_path: str,
        profile: dict[str, Any],
        endpoint_cfg: dict[str, Any],
        bench_cfg: dict[str, Any],
        log_path: Path,
    ) -> tuple[Any, str]:
        capacity_issue = profile_vram_issue_for_path(model_path, profile)
        if capacity_issue:
            raise CapacityLimitError(capacity_issue)

        runtime_profile, adjustments = _runtime_profile(profile)
        baseline_mib = _nvidia_vram_used_mib() if _is_gpu_profile(runtime_profile) else None
        proc, command = start_llama_server(
            self.llama_server_exe,
            model_path,
            runtime_profile,
            endpoint_cfg,
            bench_cfg,
            log_path,
        )
        # Popen accepts custom attributes; suppress errors for test doubles.
        with contextlib.suppress(Exception):
            proc._llmbench_vram_baseline_mib = baseline_mib  # type: ignore[attr-defined]
            proc._llmbench_runtime_adjustments = adjustments  # type: ignore[attr-defined]
        return proc, command

    def stop_server(self, proc: Any) -> None:
        baseline_mib = getattr(proc, "_llmbench_vram_baseline_mib", None)
        stop_llama_server(proc)
        _wait_for_vram_release(baseline_mib)

    def wait_health(
        self, base_url: str, timeout_s: float, headers: dict[str, str] | None = None, proc: Any = None
    ) -> float:
        return wait_health(base_url, timeout_s, headers, proc)
