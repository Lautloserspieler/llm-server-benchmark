from __future__ import annotations

from collections import namedtuple

from llmbench.cpu_telemetry import (
    LinuxRaplCpuProvider,
    PsutilCpuProvider,
    _RaplEnergyReader,
)


def test_rapl_reader_derives_package_power_from_energy_delta(tmp_path):
    zone = tmp_path / "intel-rapl:0"
    zone.mkdir()
    (zone / "name").write_text("package-0\n", encoding="utf-8")
    energy = zone / "energy_uj"
    energy.write_text("1000000\n", encoding="utf-8")
    (zone / "max_energy_range_uj").write_text("100000000\n", encoding="utf-8")

    times = iter([10.0, 10.5])
    reader = _RaplEnergyReader(tmp_path, clock=lambda: next(times))
    assert reader.initialize() is True
    assert reader.sample_power_w() is None

    energy.write_text("56000000\n", encoding="utf-8")
    assert reader.sample_power_w() == 110.0


def test_rapl_reader_handles_energy_counter_wrap(tmp_path):
    zone = tmp_path / "intel-rapl:0"
    zone.mkdir()
    (zone / "name").write_text("package-0\n", encoding="utf-8")
    energy = zone / "energy_uj"
    energy.write_text("95000000\n", encoding="utf-8")
    (zone / "max_energy_range_uj").write_text("100000000\n", encoding="utf-8")

    times = iter([1.0, 2.0])
    reader = _RaplEnergyReader(tmp_path, clock=lambda: next(times))
    assert reader.initialize() is True
    assert reader.sample_power_w() is None

    energy.write_text("5000000\n", encoding="utf-8")
    assert reader.sample_power_w() == 10.0


def test_rapl_reader_ignores_non_package_domains(tmp_path):
    package = tmp_path / "intel-rapl:0"
    package.mkdir()
    (package / "name").write_text("package-0\n", encoding="utf-8")
    (package / "energy_uj").write_text("1000\n", encoding="utf-8")

    dram = tmp_path / "intel-rapl:1"
    dram.mkdir()
    (dram / "name").write_text("dram\n", encoding="utf-8")
    (dram / "energy_uj").write_text("2000\n", encoding="utf-8")

    reader = _RaplEnergyReader(tmp_path)
    assert reader.initialize() is True
    assert len(reader._zones) == 1
    assert reader._zones[0][0] == package / "energy_uj"


def test_psutil_cpu_provider_collects_frequency_and_prefers_cpu_temperature(monkeypatch):
    Freq = namedtuple("Freq", "current min max")
    Temp = namedtuple("Temp", "label current high critical")

    monkeypatch.setattr(
        "llmbench.cpu_telemetry.psutil.cpu_freq",
        lambda: Freq(4210.0, 800.0, 4500.0),
    )
    monkeypatch.setattr(
        "llmbench.cpu_telemetry.psutil.sensors_temperatures",
        lambda _fahrenheit=False: {
            "nvme": [Temp("Composite", 55.0, 80.0, 90.0)],
            "k10temp": [Temp("Tctl", 73.5, 95.0, 100.0)],
        },
    )

    provider = PsutilCpuProvider()
    assert provider.initialize() is True
    sample = provider.sample_cpu()
    assert sample.frequency_mhz == 4210.0
    assert sample.temperature_c == 73.5
    assert sample.package_power_w is None


def test_psutil_cpu_provider_gracefully_handles_missing_temperature_api(monkeypatch):
    Freq = namedtuple("Freq", "current min max")
    monkeypatch.setattr(
        "llmbench.cpu_telemetry.psutil.cpu_freq",
        lambda: Freq(3500.0, 800.0, 4500.0),
    )
    monkeypatch.delattr(
        "llmbench.cpu_telemetry.psutil.sensors_temperatures",
        raising=False,
    )

    provider = PsutilCpuProvider()
    provider.initialize()
    sample = provider.sample_cpu()
    assert sample.frequency_mhz == 3500.0
    assert sample.temperature_c is None


def test_linux_rapl_provider_combines_psutil_metrics_with_power(monkeypatch, tmp_path):
    Freq = namedtuple("Freq", "current min max")
    monkeypatch.setattr(
        "llmbench.cpu_telemetry.psutil.cpu_freq",
        lambda: Freq(4000.0, 800.0, 4500.0),
    )
    monkeypatch.setattr(
        "llmbench.cpu_telemetry.PsutilCpuProvider._temperature_c",
        classmethod(lambda _cls: 70.0),
    )

    zone = tmp_path / "intel-rapl:0"
    zone.mkdir()
    (zone / "name").write_text("package-0\n", encoding="utf-8")
    energy = zone / "energy_uj"
    energy.write_text("0\n", encoding="utf-8")
    (zone / "max_energy_range_uj").write_text("1000000000\n", encoding="utf-8")

    times = iter([5.0, 6.0])
    provider = LinuxRaplCpuProvider(tmp_path, clock=lambda: next(times))
    assert provider.initialize() is True
    assert provider.sample_cpu().package_power_w is None

    energy.write_text("125000000\n", encoding="utf-8")
    sample = provider.sample_cpu()
    assert sample.frequency_mhz == 4000.0
    assert sample.temperature_c == 70.0
    assert sample.package_power_w == 125.0
