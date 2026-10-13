"""Windows CPU-Sensoren ueber LibreHardwareMonitor (LHM).

Bietet CPU-Temperatur (Package/Max-Core) und CPU-Package-Leistung. LHM ist der
zuverlaessigste Weg auf Windows, weil es Motherboard-Sensoren, AMD-und Intel-
MSR-Werte konsolidiert. `pythonnet` wird lazy importiert, damit es eine
optionale Abhaengigkeit bleibt.
"""
from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .utils import run_capture


@dataclass
class CpuSensorReading:
    temperature_c: float | None
    power_w: float | None
    sensor_source: str


def _wmi_cpu_temperature() -> float | None:
    """Fallback ueber WMI, falls LHM nicht verfuegbar ist."""
    try:
        cp = run_capture(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance MSAcpi_ThermalZoneTemperature -Namespace root/wmi).CurrentTemperature | "
             "Sort-Object -Descending | Select-Object -First 1"],
            timeout=10,
        )
        if cp.returncode == 0 and cp.stdout.strip():
            tenths = float(cp.stdout.strip().splitlines()[0].strip())
            return (tenths / 10.0) - 273.15
    except Exception:
        return None
    return None


class LibreHardwareMonitorCpu:
    """Wrapper um LibreHardwareMonitorLib.dll via pythonnet."""

    def __init__(self) -> None:
        self._computer: Any | None = None
        self._initialized: bool = False
        self._error: str | None = None

    def initialize(self) -> bool:
        if self._initialized:
            return True
        if os.name != "nt":
            self._error = "LibreHardwareMonitor ist nur auf Windows verfuegbar."
            return False
        try:
            import clr  # type: ignore[import-untyped]  # pythonnet
        except Exception as exc:
            self._error = (
                "pythonnet ist nicht installiert. "
                "Installiere es mit: pip install pythonnet"
            )
            return False

        # LHM-Bibliothek im Projektordner oder im PATH suchen
        candidates = [
            Path("LibreHardwareMonitorLib.dll"),
            Path(__file__).parent / "LibreHardwareMonitorLib.dll",
            Path.home() / ".llmbench" / "LibreHardwareMonitorLib.dll",
        ]
        dll_path = None
        for c in candidates:
            if c.exists():
                dll_path = c
                break
        if dll_path is None:
            self._error = "LibreHardwareMonitorLib.dll nicht gefunden."
            return False

        try:
            clr.AddReference(str(dll_path.resolve()))
            import LibreHardwareMonitor.Hardware  # type: ignore[import-untyped]

            self._computer = LibreHardwareMonitor.Hardware.Computer()
            self._computer.IsCpuEnabled = True
            self._computer.Open()
            self._initialized = True
            return True
        except Exception as exc:
            self._error = f"LHM-Initialisierung fehlgeschlagen: {exc}"
            return False

    def read(self) -> CpuSensorReading:
        if not self._initialized or not self._computer:
            temp = _wmi_cpu_temperature()
            return CpuSensorReading(temperature_c=temp, power_w=None, sensor_source="wmi_fallback")

        max_temp: float | None = None
        package_power: float | None = None

        try:
            for hardware in self._computer.Hardware:
                if hardware.HardwareType.ToString() != "CPU":
                    continue
                hardware.Update()
                for sensor in hardware.Sensors:
                    stype = sensor.SensorType.ToString()
                    name = sensor.Name
                    if sensor.Value is None:
                        continue
                    value = float(sensor.Value)
                    if stype == "Temperature" and (name == "CPU Package" or "Tctl" in name or "Tdie" in name):
                        max_temp = value if max_temp is None else max(max_temp, value)
                    elif stype == "Power" and "Package" in name:
                        package_power = value if package_power is None else max(package_power, value)
        except Exception:
            pass

        if max_temp is None:
            max_temp = _wmi_cpu_temperature()

        source = "librehardwaremonitor" if (max_temp is not None or package_power is not None) else "wmi_fallback"
        return CpuSensorReading(temperature_c=max_temp, power_w=package_power, sensor_source=source)

    def shutdown(self) -> None:
        if self._computer:
            with contextlib.suppress(Exception):
                self._computer.Close()
        self._computer = None
        self._initialized = False


# Singleton fuer wiederholte Abfragen innerhalb eines Prozesses
_LHM: LibreHardwareMonitorCpu | None = None


def get_cpu_sensors() -> LibreHardwareMonitorCpu:
    global _LHM
    if _LHM is None:
        _LHM = LibreHardwareMonitorCpu()
    return _LHM


def sample_cpu_sensors() -> CpuSensorReading:
    """Einmalige bequeme Funktion fuer Monitor und Hardware-Erfassung."""
    lhm = get_cpu_sensors()
    if not lhm._initialized:
        lhm.initialize()
    return lhm.read()


def cpu_sensor_info() -> dict[str, Any]:
    lhm = get_cpu_sensors()
    initialized = lhm.initialize()
    return {
        "available": initialized,
        "error": lhm._error,
        "library_path": str(__file__),
    }
