from __future__ import annotations

import contextlib
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

import psutil

from .utils import run_capture, utc_now_iso


def _cpu_name() -> str:
    name = platform.processor().strip()
    if name and name != "unknown" and not name.startswith("x86_64"):
        return name
    if os.name == "nt":
        # wmic ist auf aktuellen Windows-Versionen entfernt, CIM ist der Nachfolger.
        p = run_capture(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Processor).Name"],
            timeout=20,
        )
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.strip().splitlines()[0].strip()
        p = run_capture(["wmic", "cpu", "get", "name"], timeout=10)
        lines = [x.strip() for x in p.stdout.splitlines() if x.strip() and "Name" not in x]
        if lines:
            return lines[0]
    elif sys.platform == "darwin":
        p = run_capture(["sysctl", "-n", "machdep.cpu.brand_string"], timeout=5)
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.strip()
    elif sys.platform.startswith("linux"):
        with contextlib.suppress(Exception), open("/proc/cpuinfo") as f:
            for line in f:
                if "model name" in line:
                    return line.split(":", 1)[1].strip()
    return name or platform.machine()


def _power_scheme() -> str | None:
    """Der Energieplan aendert die Ergebnisse deutlich und wird beim
    Serververgleich regelmaessig uebersehen."""
    if os.name == "nt":
        p = run_capture(["powercfg", "/getactivescheme"], timeout=10)
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.strip()
        return None
    if sys.platform.startswith("linux"):
        governors: set[str] = set()
        with contextlib.suppress(Exception):
            for path in Path("/sys/devices/system/cpu").glob("cpu*/cpufreq/scaling_governor"):
                governors.add(path.read_text().strip())
        if governors:
            return "scaling_governor=" + ",".join(sorted(governors))
    return None


def _nvidia_smi_info() -> list[dict[str, Any]]:
    fields = ["index", "name", "driver_version", "memory.total", "compute_cap",
              "vbios_version", "power.limit"]
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
            item: dict[str, Any] = dict(zip(fields, parts, strict=False))
            item["vendor"] = "NVIDIA"
            item["telemetry"] = "nvml"
            for key in ["index", "memory.total"]:
                with contextlib.suppress(Exception):
                    item[key] = int(float(item[key]))
            with contextlib.suppress(Exception):
                item["power.limit"] = float(item["power.limit"])
            gpus.append(item)
        return gpus
    except Exception:
        return []


def _rocm_smi_info() -> list[dict[str, Any]]:
    try:
        cp = run_capture(
            ["rocm-smi", "--showid", "--showproductname", "--showvbios", "--showdriverversion",
             "--json"],
            timeout=10,
        )
        if cp.returncode != 0:
            return []
        data = json.loads(cp.stdout)
        gpus = []
        for idx, (gpu_id, info) in enumerate(data.items()):
            if not gpu_id.startswith("card"):
                continue
            name = (
                info.get("Card series")
                or info.get("Card model")
                or info.get("Device ID")
                or f"AMD GPU {gpu_id}"
            )
            gpus.append({
                "index": idx,
                "vendor": "AMD",
                "name": name,
                "driver_version": info.get("Driver version"),
                "vbios_version": info.get("VBIOS version", "unbekannt"),
                # Ehrlich benennen: der Monitor kann derzeit nur NVML lesen.
                "telemetry": "none",
            })
        return gpus
    except Exception:
        return []


def _xpu_smi_info() -> list[dict[str, Any]]:
    try:
        cp = run_capture(["xpu-smi", "discovery", "-j"], timeout=10)
        if cp.returncode != 0:
            return []
        data = json.loads(cp.stdout)
        gpus = []
        for dev in data.get("device_list", []):
            gpus.append({
                "index": dev.get("device_id", 0),
                "vendor": "Intel",
                "name": dev.get("device_name", "Intel GPU"),
                "memory.total": dev.get("memory_physical_size_mb", 0),
                "driver_version": dev.get("driver_version"),
                "telemetry": "none",
            })
        return gpus
    except Exception:
        return []


def collect_hardware(output_dir: str | Path | None = None) -> dict[str, Any]:
    vm = psutil.virtual_memory()
    disk_target = Path(output_dir) if output_dir else Path.cwd()
    while output_dir and not disk_target.exists() and disk_target != disk_target.parent:
        disk_target = disk_target.parent
    try:
        disk = psutil.disk_usage(str(disk_target))
        disk_info = {"root": str(disk_target), "total_bytes": disk.total, "free_bytes": disk.free}
    except Exception:
        disk_info = {}

    freq = None
    with contextlib.suppress(Exception):
        freq = psutil.cpu_freq()

    gpus: list[dict[str, Any]] = []
    gpus.extend(_nvidia_smi_info())
    gpus.extend(_rocm_smi_info())
    gpus.extend(_xpu_smi_info())

    return {
        "collected_at": utc_now_iso(),
        "hostname": platform.node(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "power_scheme": _power_scheme(),
        "cpu": {
            "name": _cpu_name(),
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True),
            "max_frequency_mhz": getattr(freq, "max", None) if freq else None,
        },
        "memory": {"total_bytes": vm.total, "available_bytes": vm.available},
        "disk": disk_info,
        "gpus": gpus,
    }
