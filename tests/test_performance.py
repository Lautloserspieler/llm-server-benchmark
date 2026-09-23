from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from llmbench import performance
from llmbench.performance import PerformanceMode, restore_from_state


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], tuple[int, str]] | None = None):
        self.responses = responses or {}
        self.calls: list[list[str]] = []

    def __call__(self, argv, **_kwargs):
        self.calls.append(list(argv))
        for prefix, (rc, out) in self.responses.items():
            if tuple(argv[: len(prefix)]) == prefix:
                return subprocess.CompletedProcess(argv, rc, out, "")
        return subprocess.CompletedProcess(argv, 0, "", "")


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def linux_sysfs(tmp_path):
    root = tmp_path / "sysfs"
    cpu = root / "sys/devices/system/cpu"
    for n in (0, 1):
        pol = cpu / f"cpufreq/policy{n}"
        _write(pol / "scaling_governor", "powersave\n")
        _write(pol / "scaling_available_governors", "performance powersave\n")
        _write(pol / "energy_performance_preference", "balance_power\n")
        _write(pol / "energy_performance_available_preferences", "default performance balance_power power\n")
        _write(pol / "cpuinfo_max_freq", "5000000\n")
        _write(pol / "scaling_max_freq", "3000000\n")
    _write(cpu / "intel_pstate/no_turbo", "1\n")
    _write(cpu / "intel_pstate/max_perf_pct", "100\n")
    _write(root / "sys/firmware/acpi/platform_profile", "balanced\n")
    _write(root / "sys/firmware/acpi/platform_profile_choices", "low-power balanced performance\n")
    rapl = root / "sys/class/powercap/intel-rapl:0"
    _write(rapl / "constraint_0_power_limit_uw", "65000000\n")
    _write(rapl / "constraint_0_max_power_uw", "125000000\n")
    _write(root / "sys/module/pcie_aspm/parameters/policy", "[default] performance powersave powersupersave\n")
    amd = root / "sys/class/drm/card0/device"
    _write(amd / "vendor", "0x1002\n")
    _write(amd / "power_dpm_force_performance_level", "auto\n")
    _write(amd / "hwmon/hwmon3/power1_cap", "200000000\n")
    _write(amd / "hwmon/hwmon3/power1_cap_max", "300000000\n")
    return root


@pytest.fixture
def no_tools(monkeypatch):
    monkeypatch.setattr(performance, "command_exists", lambda _name: False)


@pytest.mark.usefixtures("no_tools")
def test_linux_sets_everything_and_restores_it(tmp_path, linux_sysfs):
    mode = PerformanceMode(tmp_path, platform_name="linux", sysfs_root=linux_sysfs, runner=FakeRunner(), is_admin=True)
    with mode:
        cpu = linux_sysfs / "sys/devices/system/cpu"
        assert (cpu / "cpufreq/policy0/scaling_governor").read_text() == "performance"
        assert (cpu / "cpufreq/policy1/energy_performance_preference").read_text() == "performance"
        assert (cpu / "cpufreq/policy0/scaling_max_freq").read_text() == "5000000"
        assert (cpu / "intel_pstate/no_turbo").read_text() == "0"
        assert (linux_sysfs / "sys/firmware/acpi/platform_profile").read_text() == "performance"
        rapl = linux_sysfs / "sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw"
        assert rapl.read_text() == "125000000"
        assert (linux_sysfs / "sys/module/pcie_aspm/parameters/policy").read_text() == "performance"
        amd = linux_sysfs / "sys/class/drm/card0/device"
        assert (amd / "hwmon/hwmon3/power1_cap").read_text() == "300000000"
        assert (amd / "power_dpm_force_performance_level").read_text() == "high"
        assert (tmp_path / performance.STATE_FILE).is_file()
        assert not mode.failed_steps()

    cpu = linux_sysfs / "sys/devices/system/cpu"
    assert (cpu / "cpufreq/policy0/scaling_governor").read_text() == "powersave"
    assert (cpu / "intel_pstate/no_turbo").read_text() == "1"
    assert (linux_sysfs / "sys/module/pcie_aspm/parameters/policy").read_text() == "default"
    assert (linux_sysfs / "sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw").read_text() == "65000000"
    assert not (tmp_path / performance.STATE_FILE).exists()


@pytest.mark.usefixtures("no_tools")
def test_stays_active_without_restore_and_off_reverts(tmp_path, linux_sysfs):
    gov = linux_sysfs / "sys/devices/system/cpu/cpufreq/policy0/scaling_governor"
    with PerformanceMode(tmp_path, platform_name="linux", sysfs_root=linux_sysfs, runner=FakeRunner(),
                         is_admin=True, restore_on_exit=False):
        pass
    assert gov.read_text() == "performance"

    # Ein zweiter Start darf die hochgesetzten Werte nicht als "Original" speichern.
    with PerformanceMode(tmp_path, platform_name="linux", sysfs_root=linux_sysfs, runner=FakeRunner(),
                         is_admin=True, restore_on_exit=False):
        pass
    plan = json.loads((tmp_path / performance.STATE_FILE).read_text())["restore"]
    assert {"kind": "write", "path": str(gov), "value": "powersave"} in plan

    assert restore_from_state(tmp_path, runner=FakeRunner())
    assert gov.read_text() == "powersave"
    assert not restore_from_state(tmp_path, runner=FakeRunner())


@pytest.mark.usefixtures("no_tools")
def test_already_performance_changes_nothing(tmp_path, linux_sysfs):
    for gov in linux_sysfs.glob("sys/devices/system/cpu/cpufreq/policy*/scaling_governor"):
        gov.write_text("performance")
    mode = PerformanceMode(tmp_path, platform_name="linux", sysfs_root=linux_sysfs, runner=FakeRunner(), is_admin=True)
    mode.apply()
    governor = next(s for s in mode.steps if s["name"] == "CPU-Governor")
    assert governor["status"] == "already"


def test_nvidia_power_limit_raised_and_restored(tmp_path, monkeypatch):
    monkeypatch.setattr(performance, "command_exists", lambda name: name == "nvidia-smi")
    runner = FakeRunner({("nvidia-smi", "--query-gpu=index,persistence_mode,power.limit,power.max_limit"):
                         (0, "0, Disabled, 350.00, 450.00\n1, Enabled, [N/A], [N/A]\n")})
    mode = PerformanceMode(tmp_path, platform_name="linux", sysfs_root=tmp_path / "empty", runner=runner, is_admin=True)
    with mode:
        assert ["nvidia-smi", "-i", "0", "-pl", "450"] in runner.calls
        assert ["nvidia-smi", "-i", "0", "-pm", "1"] in runner.calls
    assert ["nvidia-smi", "-i", "0", "-pl", "350"] in runner.calls
    assert ["nvidia-smi", "-i", "0", "-pm", "0"] in runner.calls
    assert any(s["status"] == "skipped" and "GPU 1" in s["name"] for s in mode.steps)


def test_nvidia_on_windows_without_admin_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(performance, "command_exists", lambda name: name == "nvidia-smi")
    runner = FakeRunner({
        ("powercfg", "/getactivescheme"): (1, ""),
        ("nvidia-smi", "--query-gpu=index,persistence_mode,power.limit,power.max_limit"):
            (0, "0, [N/A], 300.00, 400.00\n"),
    })
    mode = PerformanceMode(tmp_path, platform_name="windows", runner=runner, is_admin=False)
    mode.apply()
    assert not any("-pl" in call for call in runner.calls)
    assert any(s["status"] == "skipped" and "NVIDIA" in s["name"] for s in mode.steps)


def test_windows_creates_scheme_and_restores_original(tmp_path, monkeypatch):
    monkeypatch.setattr(performance, "command_exists", lambda _name: False)
    original = "381b4222-f694-41f0-9685-ff5bb260df2e"
    new = "11111111-2222-3333-4444-555555555555"
    runner = FakeRunner({
        ("powercfg", "/getactivescheme"): (0, f"Power Scheme GUID: {original}  (Balanced)"),
        ("powercfg", "/duplicatescheme"): (0, f"Power Scheme GUID: {new}  (Ultimate Performance)"),
    })
    with PerformanceMode(tmp_path, platform_name="windows", runner=runner, is_admin=False) as mode:
        assert ["powercfg", "/duplicatescheme", performance.WINDOWS_ULTIMATE_PERFORMANCE] in runner.calls
        assert ["powercfg", "/setacvalueindex", new, "SUB_PROCESSOR", "PROCTHROTTLEMIN", "100"] in runner.calls
        assert ["powercfg", "/setactive", new] in runner.calls
        assert mode.steps[0]["status"] == "applied"
    tail = runner.calls[-2:]
    assert tail == [["powercfg", "/setactive", original], ["powercfg", "/delete", new]]


def test_disabled_in_config_does_nothing():
    from llmbench.cli import _performance_mode

    with _performance_mode({"performance": {"enabled": False}}) as perf:
        assert perf is None
    with _performance_mode({"performance": {"enabled": True}}, disabled=True) as perf:
        assert perf is None


def test_config_defaults_to_full_performance():
    from llmbench.config import RootConfig, default_config

    cfg = default_config()
    assert cfg["performance"] == {"enabled": True, "restore_after_run": False, "use_sudo": True}
    assert RootConfig(**cfg).performance.enabled is True
