from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any

import psutil

from .utils import run_capture, utc_now_iso


def _cpu_name() -> str:
    name = platform.processor().strip()
    if name:
        return name
    if os.name == "nt":
        p = run_capture(["wmic", "cpu", "get", "name"], timeout=10)
        lines = [x.strip() for x in p.stdout.splitlines() if x.strip() and "Name" not in x]
        if lines:
            return lines[0]
    return platform.machine()


def _nvidia_smi_info() -> list[dict[str, Any]]:
    fields = ["index", "name", "driver_version", "memory.total", "compute_cap", "vbios_version", "power.limit"]
    cmd = ["nvidia-smi", f"--query-gpu={','.join(fields)}", "--format=csv,noheader,nounits"]
    try:
        cp = run_capture(cmd, timeout=10)
        if cp.returncode != 0:
            return []
        gpus = []
        for line in cp.stdout.splitlines():
            parts = [x.strip() for x in line.split(",")]
            if len(parts) < len(fields):
                continue
            item: dict[str, Any] = dict(zip(fields, parts))
            for key in ["index", "memory.total"]:
                try:
                    item[key] = int(float(item[key]))
                except Exception:
                    pass
            try:
                item["power.limit"] = float(item["power.limit"])
            except Exception:
                pass
            gpus.append(item)
        return gpus
    except Exception:
        return []


def collect_hardware() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    disk_root = Path.cwd().anchor or "/"
    try:
        disk = psutil.disk_usage(disk_root)
        disk_info = {"root": disk_root, "total_bytes": disk.total, "free_bytes": disk.free}
    except Exception:
        disk_info = {}
    return {
        "collected_at": utc_now_iso(),
        "hostname": platform.node(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu": {
            "name": _cpu_name(),
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True),
            "max_frequency_mhz": getattr(psutil.cpu_freq(), "max", None) if psutil.cpu_freq() else None,
        },
        "memory": {"total_bytes": vm.total, "available_bytes": vm.available},
        "disk": disk_info,
        "gpus": _nvidia_smi_info(),
    }
