"""Unit tests fuer den LibreHardwareMonitor-CPU-Sensor-Provider.

Da LHM/pythonnet nicht in der CI vorhanden sind, wird hier das Verhalten ohne
DLL und der WMI-Fallback simuliert.
"""
from __future__ import annotations

from unittest.mock import patch

from llmbench.cpu_sensors import (
    LibreHardwareMonitorCpu,
    _wmi_cpu_temperature,
    cpu_sensor_info,
    get_cpu_sensors,
    sample_cpu_sensors,
)


def test_cpu_sensor_info_reports_not_available_without_lhm(monkeypatch):
    monkeypatch.setattr("os.name", "posix")
    info = cpu_sensor_info()
    assert info["available"] is False
    assert "LibreHardwareMonitor" in info["error"]


def test_wmi_fallback_returns_none_on_failure(monkeypatch):
    with patch("llmbench.cpu_sensors.run_capture") as mock_run:
        mock_run.return_value.returncode = 1
        assert _wmi_cpu_temperature() is None


def test_sample_cpu_sensors_uses_wmi_fallback_when_lhm_unavailable(monkeypatch):
    lhm = LibreHardwareMonitorCpu()
    lhm._error = "DLL fehlt"
    monkeypatch.setattr("llmbench.cpu_sensors._LHM", lhm)

    with patch("llmbench.cpu_sensors._wmi_cpu_temperature", return_value=42.0):
        reading = sample_cpu_sensors()
    assert reading.temperature_c == 42.0
    assert reading.sensor_source == "wmi_fallback"


def test_lhm_provider_is_singleton():
    a = get_cpu_sensors()
    b = get_cpu_sensors()
    assert a is b
