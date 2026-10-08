import time

from llmbench.cpu_telemetry import CpuSample, CpuTelemetryProvider
from llmbench.monitor import ResourceMonitor, strip_samples
from llmbench.telemetry import GpuSample, TelemetryProvider


class FakeProvider(TelemetryProvider):
    """Deterministic stand-in for NvidiaProvider so monitor tests don't need a GPU."""

    def __init__(self, samples_sequence):
        super().__init__()
        self._sequence = list(samples_sequence)
        self.shutdown_called = False

    def initialize(self) -> bool:
        self.initialized = True
        return True

    def sample_gpus(self):
        if not self._sequence:
            return []
        return self._sequence.pop(0) if len(self._sequence) > 1 else list(self._sequence[0])

    def shutdown(self) -> None:
        self.initialized = False
        self.shutdown_called = True


class FakeCpuProvider(CpuTelemetryProvider):
    TELEMETRY_SOURCE = "test_cpu"

    def __init__(self, sample):
        super().__init__()
        self._sample = sample
        self.shutdown_called = False

    def initialize(self) -> bool:
        self.initialized = True
        return True

    def sample_cpu(self):
        return self._sample

    def shutdown(self) -> None:
        self.initialized = False
        self.shutdown_called = True


def _gpu(index=0, util=50.0, mem_used=1000, mem_total=8000, power=100.0, temp=60.0, pids=None):
    return GpuSample(
        index=index,
        util_gpu_percent=util,
        util_memory_percent=util / 2,
        memory_used_bytes=mem_used,
        memory_total_bytes=mem_total,
        temperature_c=temp,
        power_w=power,
        compute_pids=pids or [],
    )


def test_strip_samples_removes_raw_samples_but_keeps_aggregates():
    telemetry = {"avg_cpu_percent": 10.0, "samples": [{"ts": 1}, {"ts": 2}]}
    out = strip_samples(telemetry)
    assert "samples" not in out
    assert out["avg_cpu_percent"] == 10.0
    assert out["samples_stored_in"] == "raw_*.json"


def test_strip_samples_handles_empty_input():
    assert strip_samples(None) == {}
    assert strip_samples({}) == {}


def test_summary_without_any_samples_reports_zero_count():
    monitor = ResourceMonitor()
    summary = monitor.summary()
    assert summary["sample_count"] == 0
    assert summary["telemetry_source"] == "none"


def test_summary_aggregates_cpu_ram_and_gpu_metrics():
    monitor = ResourceMonitor()
    monitor._samples = [
        {"cpu_percent": 10.0, "ram_used_bytes": 1000, "gpus": [_gpu(util=40.0, power=100.0).__dict__]},
        {"cpu_percent": 20.0, "ram_used_bytes": 2000, "gpus": [_gpu(util=60.0, power=140.0).__dict__]},
    ]
    summary = monitor.summary()
    assert summary["sample_count"] == 2
    assert summary["avg_cpu_percent"] == 15.0
    assert summary["max_cpu_percent"] == 20.0
    assert summary["avg_ram_used_bytes"] == 1500.0
    gpu0 = summary["gpus"][0]
    assert gpu0["avg_util_gpu_percent"] == 50.0
    assert gpu0["max_util_gpu_percent"] == 60.0
    assert gpu0["avg_power_w"] == 120.0
    assert gpu0["memory_total_bytes"] == 8000


def test_summary_detects_foreign_gpu_processes():
    monitor = ResourceMonitor()
    monitor._own_pids = {111}
    monitor._seen_gpu_pids = {111, 222}
    monitor._samples = [{"cpu_percent": 1.0, "ram_used_bytes": 1, "gpus": []}]
    summary = monitor.summary()
    assert [p["pid"] for p in summary["foreign_gpu_processes"]] == [222]
    assert any("Fremde Prozesse" in w for w in summary["warnings"])


def test_summary_warns_when_gpu_was_busy_before_the_run():
    monitor = ResourceMonitor()
    monitor._samples = [{"cpu_percent": 1.0, "ram_used_bytes": 1, "gpus": []}]
    monitor._baseline = {"gpus": [_gpu(util=42.0).__dict__]}
    summary = monitor.summary()
    assert any("nicht im Ruhezustand" in w for w in summary["warnings"])


def test_summary_does_not_warn_when_gpu_was_idle_before_the_run():
    monitor = ResourceMonitor()
    monitor._samples = [{"cpu_percent": 1.0, "ram_used_bytes": 1, "gpus": []}]
    monitor._baseline = {"gpus": [_gpu(util=2.0).__dict__]}
    summary = monitor.summary()
    assert summary["warnings"] == []


def test_set_target_pid_adds_pid_to_own_pids():
    monitor = ResourceMonitor()
    monitor.set_target_pid(999)
    assert 999 in monitor._own_pids


def test_start_and_stop_collect_samples_via_the_telemetry_provider(monkeypatch):
    provider = FakeProvider([[_gpu(util=77.0)]])
    monkeypatch.setattr("llmbench.monitor.get_telemetry_provider", lambda: provider)

    monitor = ResourceMonitor(interval=0.02, idle_wait_seconds=0)
    monitor.start()
    
    # Wait for at least one sample instead of a fixed sleep to prevent flakiness
    start_time = time.time()
    while len(monitor._samples) == 0 and time.time() - start_time < 2.0:
        time.sleep(0.01)
        
    summary = monitor.stop()

    assert summary["sample_count"] >= 1
    assert summary["gpus"][0]["avg_util_gpu_percent"] == 77.0
    assert provider.shutdown_called is True


def test_summary_reports_telemetry_source_from_provider_attribute(monkeypatch):
    provider = FakeProvider([[_gpu(util=77.0)]])
    provider.TELEMETRY_SOURCE = "rocm_smi"
    monkeypatch.setattr("llmbench.monitor.get_telemetry_provider", lambda: provider)

    monitor = ResourceMonitor(interval=0.02, idle_wait_seconds=0)
    monitor.start()

    start_time = time.time()
    while len(monitor._samples) == 0 and time.time() - start_time < 2.0:
        time.sleep(0.01)

    summary = monitor.stop()
    assert summary["telemetry_source"] == "rocm_smi"


def test_summary_falls_back_to_cpu_only_when_provider_has_no_telemetry_source_attribute():
    monitor = ResourceMonitor()
    monitor._provider = object()  # test double without a TELEMETRY_SOURCE attribute
    monitor._samples = [{"cpu_percent": 1.0, "ram_used_bytes": 1, "gpus": []}]
    summary = monitor.summary()
    assert summary["telemetry_source"] == "cpu_only"


def test_latest_returns_baseline_before_any_sample_is_collected(monkeypatch):
    provider = FakeProvider([[_gpu(util=10.0)]])
    monkeypatch.setattr("llmbench.monitor.get_telemetry_provider", lambda: provider)

    monitor = ResourceMonitor(interval=10.0)
    # Statt start() aufzurufen, was den Hintergrund-Thread startet (Race-Condition),
    # setzen wir einfach _baseline und pruefen, ob latest() das korrekte Verhalten zeigt,
    # wenn _samples leer ist.
    monitor._baseline = {"ram_used_bytes": 1024}
    monitor._samples = []
    assert monitor.latest() is monitor._baseline


def test_start_waits_until_gpu_is_idle_before_taking_the_baseline(monkeypatch):
    # Direkt nach einem GPU-Test laeuft die Karte kurz nach - das ist kein "ausgelastet".
    busy_then_idle = iter([80.0, 40.0, 3.0])
    provider = FakeProvider([[_gpu(util=next(busy_then_idle, 3.0))] for _ in range(50)])
    monkeypatch.setattr("llmbench.monitor.get_telemetry_provider", lambda: provider)
    monkeypatch.setattr("llmbench.monitor.time.sleep", lambda _s: None)

    monitor = ResourceMonitor(interval=10.0, idle_wait_seconds=15)
    monitor._provider = provider
    baseline = monitor._wait_for_idle_gpu()
    assert baseline["gpus"][0]["util_gpu_percent"] == 3.0


def test_idle_wait_gives_up_after_the_limit():
    provider = FakeProvider([[_gpu(util=90.0)] for _ in range(50)])
    monitor = ResourceMonitor(interval=10.0, idle_wait_seconds=0)
    monitor._provider = provider
    assert monitor._wait_for_idle_gpu()["gpus"][0]["util_gpu_percent"] == 90.0


def test_windows_system_process_is_not_reported_as_foreign():
    # nvidia-smi fuehrt unter Windows den Kernel-Prozess "System" (PID 4) als GPU-Nutzer.
    monitor = ResourceMonitor()
    monitor._own_pids = {111}
    monitor._seen_gpu_pids = {0, 4, 111}
    monitor._samples = [{"cpu_percent": 1.0, "ram_used_bytes": 1, "gpus": []}]
    summary = monitor.summary()
    assert summary["foreign_gpu_processes"] == []
    assert not any("Fremde Prozesse" in w for w in summary["warnings"])


def test_summary_aggregates_cpu_frequency_temperature_and_package_power():
    monitor = ResourceMonitor()
    monitor._cpu_provider = FakeCpuProvider(
        CpuSample(frequency_mhz=4000.0, temperature_c=70.0, package_power_w=100.0)
    )
    monitor._samples = [
        {
            "cpu_percent": 50.0,
            "ram_used_bytes": 1000,
            "cpu": {
                "util_percent": 50.0,
                "frequency_mhz": 3900.0,
                "temperature_c": 68.0,
                "package_power_w": 90.0,
            },
            "gpus": [],
        },
        {
            "cpu_percent": 80.0,
            "ram_used_bytes": 2000,
            "cpu": {
                "util_percent": 80.0,
                "frequency_mhz": 4300.0,
                "temperature_c": 76.0,
                "package_power_w": 130.0,
            },
            "gpus": [],
        },
    ]

    summary = monitor.summary()
    cpu = summary["cpu"]
    assert cpu["avg_util_percent"] == 65.0
    assert cpu["avg_frequency_mhz"] == 4100.0
    assert cpu["min_frequency_mhz"] == 3900.0
    assert cpu["max_frequency_mhz"] == 4300.0
    assert cpu["avg_temperature_c"] == 72.0
    assert cpu["max_temperature_c"] == 76.0
    assert cpu["avg_package_power_w"] == 110.0
    assert cpu["max_package_power_w"] == 130.0
    assert cpu["telemetry_source"] == "test_cpu"


def test_cpu_sensor_failures_degrade_to_unavailable_values():
    class BrokenCpuProvider(FakeCpuProvider):
        def sample_cpu(self):
            raise RuntimeError("sensor unavailable")

    monitor = ResourceMonitor()
    monitor._cpu_provider = BrokenCpuProvider(
        CpuSample(frequency_mhz=None, temperature_c=None, package_power_w=None)
    )
    sample = monitor._cpu_sample(42.0)
    assert sample == {
        "util_percent": 42.0,
        "frequency_mhz": None,
        "temperature_c": None,
        "package_power_w": None,
        "package_energy_delta_j": None,
    }


def test_start_and_stop_shuts_down_cpu_provider(monkeypatch):
    gpu_provider = FakeProvider([[_gpu(util=1.0)]])
    cpu_provider = FakeCpuProvider(
        CpuSample(frequency_mhz=4100.0, temperature_c=65.0, package_power_w=95.0)
    )
    monkeypatch.setattr("llmbench.monitor.get_telemetry_provider", lambda: gpu_provider)
    monkeypatch.setattr("llmbench.monitor.get_cpu_telemetry_provider", lambda: cpu_provider)

    monitor = ResourceMonitor(interval=0.02, idle_wait_seconds=0)
    monitor.start()
    start_time = time.time()
    while len(monitor._samples) == 0 and time.time() - start_time < 2.0:
        time.sleep(0.01)
    summary = monitor.stop()

    assert summary["cpu"]["avg_frequency_mhz"] == 4100.0
    assert summary["cpu"]["max_temperature_c"] == 65.0
    assert summary["cpu"]["avg_package_power_w"] == 95.0
    assert cpu_provider.shutdown_called is True


def test_summary_integrates_gpu_energy_and_uses_direct_cpu_energy():
    monitor = ResourceMonitor()
    monitor._cpu_provider = FakeCpuProvider(
        CpuSample(frequency_mhz=4000.0, temperature_c=70.0, package_power_w=100.0)
    )
    monitor._samples = [
        {
            "ts": 10.0,
            "cpu_percent": 50.0,
            "ram_used_bytes": 1000,
            "cpu": {
                "util_percent": 50.0,
                "frequency_mhz": 4000.0,
                "temperature_c": 70.0,
                "package_power_w": 90.0,
                "package_energy_delta_j": 45.0,
            },
            "gpus": [_gpu(power=100.0).__dict__],
            "power": {
                "scope": "measured_components",
                "component_power_w": 190.0,
                "wall_power_w": None,
                "coverage": ["cpu_package", "gpu:0"],
            },
        },
        {
            "ts": 12.0,
            "cpu_percent": 60.0,
            "ram_used_bytes": 1200,
            "cpu": {
                "util_percent": 60.0,
                "frequency_mhz": 4100.0,
                "temperature_c": 72.0,
                "package_power_w": 110.0,
                "package_energy_delta_j": 55.0,
            },
            "gpus": [_gpu(power=140.0).__dict__],
            "power": {
                "scope": "measured_components",
                "component_power_w": 250.0,
                "wall_power_w": None,
                "coverage": ["cpu_package", "gpu:0"],
            },
        },
    ]

    summary = monitor.summary()

    assert summary["cpu"]["energy_j"] == 100.0
    assert summary["cpu"]["energy_source"] == "hardware_energy_counter"
    assert summary["gpus"][0]["energy_j"] == 240.0
    assert summary["gpus"][0]["energy_source"] == "sampled_power_integration"
    assert summary["power"]["component_energy_j"] == 340.0
    assert summary["power"]["avg_component_power_w"] == 220.0
    assert summary["power"]["max_component_power_w"] == 250.0
    assert summary["power"]["coverage"] == ["cpu_package", "gpu:0"]
    assert summary["power"]["scope"] == "measured_components"
    assert summary["power"]["wall_power_w"] is None
    assert summary["power"]["wall_energy_wh"] is None


def test_missing_power_is_not_treated_as_zero_or_bridged_across_gap():
    monitor = ResourceMonitor()
    monitor._samples = [
        {
            "ts": 0.0,
            "cpu_percent": 1.0,
            "ram_used_bytes": 1,
            "cpu": {"package_power_w": None, "package_energy_delta_j": None},
            "gpus": [_gpu(power=100.0).__dict__],
        },
        {
            "ts": 1.0,
            "cpu_percent": 1.0,
            "ram_used_bytes": 1,
            "cpu": {"package_power_w": None, "package_energy_delta_j": None},
            "gpus": [_gpu(power=None).__dict__],
        },
        {
            "ts": 2.0,
            "cpu_percent": 1.0,
            "ram_used_bytes": 1,
            "cpu": {"package_power_w": None, "package_energy_delta_j": None},
            "gpus": [_gpu(power=200.0).__dict__],
        },
    ]

    summary = monitor.summary()

    assert summary["gpus"][0]["energy_j"] is None
    assert summary["power"]["component_energy_j"] is None
