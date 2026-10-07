from __future__ import annotations

import contextlib
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

import psutil

from .execution import collect_execution_environment
from .utils import command_exists, run_capture, utc_now_iso


# The catalog deliberately has a small, auditable surface.  Entries must be
# backed by an Apple specification; a missing or ambiguous local identity is
# represented as unknown rather than guessed from a product-family name.
APPLE_MEMORY_BANDWIDTH_CATALOG_VERSION = "2026.10"
APPLE_MEMORY_BANDWIDTH_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "chip": "Apple M4 Pro", "gpu_cores": 20, "bandwidth_gb_s": 273,
        "reference": "https://www.apple.com/macbook-pro/specs/",
    },
    {
        "chip": "Apple M4 Max", "gpu_cores": 32, "bandwidth_gb_s": 410,
        "reference": "https://www.apple.com/mac-studio/specs/",
    },
    {
        "chip": "Apple M4 Max", "gpu_cores": 40, "bandwidth_gb_s": 546,
        "reference": "https://www.apple.com/mac-studio/specs/",
    },
    {
        "chip": "Apple M3 Ultra", "gpu_cores": 80, "bandwidth_gb_s": 819,
        "reference": "https://www.apple.com/mac-studio/specs/",
    },
)


def _unavailable(reason: str) -> dict[str, Any]:
    return {"value": None, "source": None, "unit": "GB/s", "status": "unavailable", "reason": reason}


def _unknown(reason: str) -> dict[str, Any]:
    return {"value": None, "source": None, "unit": "GB/s", "status": "unknown", "reason": reason}


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


def linux_power_state() -> dict[str, Any]:
    """CPU-Governor und - falls vorhanden - das aktive power-profiles-daemon-Profil.

    Ubuntu Desktop (z. B. 24.04 LTS mit GNOME) setzt standardmaessig auf
    `power-profiles-daemon` statt auf einen fest konfigurierten `cpupower`-
    Governor wie auf vielen Headless-Servern. Der Standardwert dort ist
    "balanced", nicht "performance" - das kostet spuerbar Tokens/s und wird
    beim Serververgleich leicht uebersehen, weil `scaling_governor` alleine
    das nicht immer zuverlaessig zeigt (z. B. bei "schedutil").
    """
    state: dict[str, Any] = {}
    governors: set[str] = set()
    with contextlib.suppress(Exception):
        for path in Path("/sys/devices/system/cpu").glob("cpu*/cpufreq/scaling_governor"):
            governors.add(path.read_text().strip())
    if governors:
        state["governors"] = sorted(governors)

    if command_exists("powerprofilesctl"):
        with contextlib.suppress(Exception):
            p = run_capture(["powerprofilesctl", "get"], timeout=5)
            if p.returncode == 0 and p.stdout.strip():
                state["profile"] = p.stdout.strip()
    return state


def _power_scheme() -> str | None:
    """Der Energieplan aendert die Ergebnisse deutlich und wird beim
    Serververgleich regelmaessig uebersehen."""
    if os.name == "nt":
        p = run_capture(["powercfg", "/getactivescheme"], timeout=10)
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.strip()
        return None
    if sys.platform.startswith("linux"):
        state = linux_power_state()
        parts = []
        if state.get("profile"):
            parts.append("power-profile=" + state["profile"])
        if state.get("governors"):
            parts.append("scaling_governor=" + ",".join(state["governors"]))
        if parts:
            return ", ".join(parts)
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
                # AmdProvider (telemetry.py) liest hierfuer live rocm-smi aus.
                "telemetry": "rocm_smi",
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


def _nvidia_memory_domains(gpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect safe NVML inputs without guessing an effective transfer rate."""
    if not gpus:
        return []
    try:
        import pynvml

        pynvml.nvmlInit()
    except Exception:
        return [
            {
                "id": f"nvidia:{gpu.get('index', index)}", "kind": "discrete_vram",
                "vendor": "NVIDIA", "name": gpu.get("name"),
                "identity": {"gpu_index": gpu.get("index", index)},
                "bandwidth": {"theoretical": _unavailable("nvml_unavailable")},
            }
            for index, gpu in enumerate(gpus)
        ]

    domains: list[dict[str, Any]] = []
    try:
        for index, gpu in enumerate(gpus):
            bus_width = max_clock = None
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(int(gpu.get("index", index)))
                bus_width = pynvml.nvmlDeviceGetMemoryBusWidth(handle)
                max_clock = pynvml.nvmlDeviceGetMaxClockInfo(handle, pynvml.NVML_CLOCK_MEM)
            except Exception:
                # Per-device NVML enrichment is optional: retain the domain
                # and mark its theoretical bandwidth unknown when it fails.
                pass
            inputs: dict[str, Any] = {}
            if isinstance(bus_width, int) and bus_width > 0:
                inputs["memory_bus_width_bits"] = bus_width
            if isinstance(max_clock, int) and max_clock > 0:
                inputs["max_memory_clock_mhz"] = max_clock
            domains.append({
                "id": f"nvidia:{gpu.get('index', index)}", "kind": "discrete_vram",
                "vendor": "NVIDIA", "name": gpu.get("name"),
                "identity": {"gpu_index": gpu.get("index", index)},
                "properties": inputs,
                "bandwidth": {
                    # NVML documents the two inputs, not one cross-architecture
                    # data-rate multiplier.  Do not turn a clock into a spec.
                    "theoretical": _unknown("unverified_data_rate"),
                },
            })
    finally:
        with contextlib.suppress(Exception):
            pynvml.nvmlShutdown()
    return domains


def _find_number(value: Any, keys: set[str]) -> float | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in keys and isinstance(child, (int, float)) and not isinstance(child, bool):
                return float(child)
            found = _find_number(child, keys)
            if found is not None:
                return found
    if isinstance(value, list):
        for child in value:
            found = _find_number(child, keys)
            if found is not None:
                return found
    return None


def _amd_smi_bandwidths() -> dict[int, float]:
    """Best-effort optional AMD SMI data, separate from legacy rocm-smi."""
    if not command_exists("amd-smi"):
        return {}
    try:
        cp = run_capture(["amd-smi", "static", "--vram", "--json"], timeout=10)
        if cp.returncode != 0:
            return {}
        payload = json.loads(cp.stdout)
        output: dict[int, float] = {}
        devices = payload.get("gpu") if isinstance(payload, dict) else payload
        if not isinstance(devices, (dict, list)):
            return output
        iterable = devices.items() if isinstance(devices, dict) else enumerate(devices)
        for raw_index, device in iterable:
            try:
                index = int(str(raw_index).split(":")[-1])
            except ValueError:
                continue
            value = _find_number(device, {"vram_max_bandwidth", "max_bandwidth"})
            if value is not None and value > 0:
                output[index] = value
        return output
    except Exception:
        return {}


def _amd_memory_domains(gpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reported = _amd_smi_bandwidths()
    domains: list[dict[str, Any]] = []
    for index, gpu in enumerate(gpus):
        gpu_index = int(gpu.get("index", index))
        bandwidth: dict[str, Any] = {"theoretical": _unknown("board_spec_not_reported")}
        if gpu_index in reported:
            bandwidth["provider_operating"] = {
                "value": reported[gpu_index], "source": "detected", "unit": "GB/s",
                "evidence": {
                    "method": "hardware_introspection", "provider": "amd-smi",
                    "qualifier": "at_current_memory_clock",
                },
            }
        else:
            bandwidth["provider_operating"] = _unavailable("amd_smi_vram_bandwidth_unavailable")
        domains.append({
            "id": f"amd:{gpu_index}", "kind": "discrete_vram", "vendor": "AMD",
            "name": gpu.get("name"), "identity": {"gpu_index": gpu_index}, "bandwidth": bandwidth,
        })
    return domains


def _apple_identity() -> dict[str, Any] | None:
    if sys.platform != "darwin":
        return None
    try:
        cp = run_capture(["system_profiler", "SPHardwareDataType", "SPDisplaysDataType", "-json"], timeout=15)
        if cp.returncode != 0:
            return None
        payload = json.loads(cp.stdout)
        hardware = (payload.get("SPHardwareDataType") or [{}])[0]
        displays = (payload.get("SPDisplaysDataType") or [{}])[0]
        chip = hardware.get("chip_type") or hardware.get("_name")
        cores = displays.get("sppci_cores") or displays.get("spdisplays_cores")
        gpu_cores = int(cores) if str(cores).isdigit() else None
        model = run_capture(["sysctl", "-n", "hw.model"], timeout=5).stdout.strip()
        if not isinstance(chip, str) or not chip.startswith("Apple"):
            return None
        identity: dict[str, Any] = {"chip": chip, "machine_model": model or None}
        if gpu_cores:
            identity["gpu_cores"] = gpu_cores
        return identity
    except Exception:
        return None


def _apple_memory_domain() -> dict[str, Any] | None:
    identity = _apple_identity()
    if not identity:
        return None
    matches = [
        row for row in APPLE_MEMORY_BANDWIDTH_CATALOG
        if row["chip"] == identity["chip"] and row["gpu_cores"] == identity.get("gpu_cores")
    ]
    if len(matches) == 1:
        row = matches[0]
        theoretical: dict[str, Any] = {
            "value": row["bandwidth_gb_s"], "source": "detected", "unit": "GB/s",
            "evidence": {
                "method": "hardware_introspection", "provider": "apple_official_catalog",
                "reference": row["reference"], "catalog_version": APPLE_MEMORY_BANDWIDTH_CATALOG_VERSION,
            },
        }
    else:
        theoretical = _unknown("apple_catalog_identity_ambiguous" if identity.get("chip") else "apple_identity_missing")
    return {
        "id": "apple:unified:0", "kind": "unified_memory", "vendor": "Apple",
        "name": identity["chip"], "identity": identity,
        "bandwidth": {"theoretical": theoretical},
    }


def _memory_domains(gpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    domains: list[dict[str, Any]] = []
    domains.extend(_nvidia_memory_domains([gpu for gpu in gpus if gpu.get("vendor") == "NVIDIA"]))
    domains.extend(_amd_memory_domains([gpu for gpu in gpus if gpu.get("vendor") == "AMD"]))
    apple = _apple_memory_domain()
    if apple:
        domains.append(apple)
    return domains


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
        "execution": collect_execution_environment(),
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
        # Keep legacy gpus intact.  A memory domain can also represent Apple
        # unified memory, which is not safely modelled as a GPU-only property.
        "memory_domains": _memory_domains(gpus),
    }
