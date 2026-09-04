import json
import subprocess

from llmbench.hardware import (
    _nvidia_smi_info,
    _power_scheme,
    _rocm_smi_info,
    _xpu_smi_info,
    collect_hardware,
    linux_power_state,
)


def _cp(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(["cmd"], returncode, stdout=stdout, stderr=stderr)


def test_nvidia_smi_info_parses_csv_output(monkeypatch):
    csv_out = "0, RTX 4090, 550.54, 24564, 8.9, 12345.67, 450.00\n"
    monkeypatch.setattr("llmbench.hardware.run_capture", lambda _cmd, **_kwargs: _cp(stdout=csv_out))

    gpus = _nvidia_smi_info()
    assert len(gpus) == 1
    gpu = gpus[0]
    assert gpu["vendor"] == "NVIDIA"
    assert gpu["telemetry"] == "nvml"
    assert gpu["name"] == "RTX 4090"
    assert gpu["index"] == 0
    assert gpu["memory.total"] == 24564
    assert gpu["power.limit"] == 450.0


def test_nvidia_smi_info_returns_empty_list_when_command_fails(monkeypatch):
    monkeypatch.setattr("llmbench.hardware.run_capture", lambda _cmd, **_kwargs: _cp(returncode=1))
    assert _nvidia_smi_info() == []


def test_nvidia_smi_info_returns_empty_list_when_command_is_missing(monkeypatch):
    def _raise(_cmd, **_kwargs):
        raise FileNotFoundError("nvidia-smi not found")

    monkeypatch.setattr("llmbench.hardware.run_capture", _raise)
    assert _nvidia_smi_info() == []


def test_nvidia_smi_info_skips_malformed_lines(monkeypatch):
    csv_out = "not enough fields\n0, RTX 4090, 550.54, 24564, 8.9, 12345.67, 450.00\n"
    monkeypatch.setattr("llmbench.hardware.run_capture", lambda _cmd, **_kwargs: _cp(stdout=csv_out))
    gpus = _nvidia_smi_info()
    assert len(gpus) == 1


def test_rocm_smi_info_parses_json_output_and_marks_no_telemetry(monkeypatch):
    payload = json.dumps({
        "card0": {
            "Card series": "Radeon RX 7900",
            "Driver version": "6.2.0",
            "VBIOS version": "113-XYZ",
        },
        "system": {"foo": "bar"},
    })
    monkeypatch.setattr("llmbench.hardware.run_capture", lambda _cmd, **_kwargs: _cp(stdout=payload))

    gpus = _rocm_smi_info()
    assert len(gpus) == 1
    gpu = gpus[0]
    assert gpu["vendor"] == "AMD"
    assert gpu["name"] == "Radeon RX 7900"
    assert gpu["telemetry"] == "none"


def test_rocm_smi_info_returns_empty_list_when_command_fails(monkeypatch):
    monkeypatch.setattr("llmbench.hardware.run_capture", lambda _cmd, **_kwargs: _cp(returncode=1))
    assert _rocm_smi_info() == []


def test_xpu_smi_info_parses_json_output_and_marks_no_telemetry(monkeypatch):
    payload = json.dumps({
        "device_list": [
            {"device_id": 0, "device_name": "Intel Arc A770", "memory_physical_size_mb": 16384, "driver_version": "1.0"}
        ]
    })
    monkeypatch.setattr("llmbench.hardware.run_capture", lambda _cmd, **_kwargs: _cp(stdout=payload))

    gpus = _xpu_smi_info()
    assert len(gpus) == 1
    gpu = gpus[0]
    assert gpu["vendor"] == "Intel"
    assert gpu["telemetry"] == "none"
    assert gpu["memory.total"] == 16384


def test_xpu_smi_info_returns_empty_list_on_invalid_json(monkeypatch):
    monkeypatch.setattr("llmbench.hardware.run_capture", lambda _cmd, **_kwargs: _cp(stdout="not json"))
    assert _xpu_smi_info() == []


def test_linux_power_state_reads_power_profiles_daemon(monkeypatch):
    monkeypatch.setattr("llmbench.hardware.command_exists", lambda name: name == "powerprofilesctl")
    monkeypatch.setattr("llmbench.hardware.run_capture", lambda _cmd, **_kwargs: _cp(stdout="balanced\n"))
    monkeypatch.setattr(
        "llmbench.hardware.Path.glob",
        lambda _self, _pattern: [],
    )

    state = linux_power_state()
    assert state["profile"] == "balanced"


def test_linux_power_state_returns_empty_dict_without_powerprofilesctl(monkeypatch):
    monkeypatch.setattr("llmbench.hardware.command_exists", lambda _name: False)
    monkeypatch.setattr("llmbench.hardware.Path.glob", lambda _self, _pattern: [])

    assert linux_power_state() == {}


def test_power_scheme_combines_profile_and_governor_on_linux(monkeypatch):
    monkeypatch.setattr("llmbench.hardware.sys.platform", "linux")
    monkeypatch.setattr(
        "llmbench.hardware.linux_power_state",
        lambda: {"profile": "balanced", "governors": ["schedutil"]},
    )

    assert _power_scheme() == "power-profile=balanced, scaling_governor=schedutil"


def test_collect_hardware_combines_all_gpu_vendors(monkeypatch, tmp_path):
    monkeypatch.setattr("llmbench.hardware._nvidia_smi_info", lambda: [{"vendor": "NVIDIA"}])
    monkeypatch.setattr("llmbench.hardware._rocm_smi_info", lambda: [{"vendor": "AMD"}])
    monkeypatch.setattr("llmbench.hardware._xpu_smi_info", lambda: [{"vendor": "Intel"}])
    monkeypatch.setattr("llmbench.hardware._power_scheme", lambda: None)
    monkeypatch.setattr("llmbench.hardware._cpu_name", lambda: "Test CPU")

    hw = collect_hardware(tmp_path)
    vendors = {g["vendor"] for g in hw["gpus"]}
    assert vendors == {"NVIDIA", "AMD", "Intel"}
    assert hw["cpu"]["name"] == "Test CPU"
    assert "collected_at" in hw
    assert hw["disk"]["free_bytes"] >= 0
