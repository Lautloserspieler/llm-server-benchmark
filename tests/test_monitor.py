import time

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

    monitor = ResourceMonitor(interval=0.02)
    monitor.start()
    time.sleep(0.08)
    summary = monitor.stop()

    assert summary["sample_count"] >= 1
    assert summary["gpus"][0]["avg_util_gpu_percent"] == 77.0
    assert provider.shutdown_called is True


def test_latest_returns_baseline_before_any_sample_is_collected(monkeypatch):
    provider = FakeProvider([[_gpu(util=10.0)]])
    monkeypatch.setattr("llmbench.monitor.get_telemetry_provider", lambda: provider)

    monitor = ResourceMonitor(interval=10.0)
    monitor.start()
    try:
        latest = monitor.latest()
        assert latest is monitor._baseline
    finally:
        monitor.stop()
