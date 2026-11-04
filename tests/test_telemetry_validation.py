"""Deterministic provider/monitor validation (Issue #122).

Every vendor provider is exercised with normal, malformed, timeout and
missing-sensor output. Mixed-vendor and two-GPU fixtures verify that a failing
device keeps its position with ``None`` values. No real hardware is involved:
nothing here claims a vendor was measured on a physical device.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from llmbench.monitor import TELEMETRY_UNITS, ResourceMonitor, _integrate_power
from llmbench.telemetry import (
    AmdProvider,
    CompositeProvider,
    GpuSample,
    IntelProvider,
    TelemetryProvider,
    _empty_sample,
)

METRIC_FIELDS = (
    "util_gpu_percent", "util_memory_percent", "memory_used_bytes", "memory_total_bytes", "temperature_c", "power_w",
)


def _cp(stdout: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _amd(monkeypatch, payload, *, raises: Exception | None = None) -> AmdProvider:
    def run(cmd, **_kwargs):
        if raises is not None and "--showmeminfo" in cmd:
            raise raises
        return _cp(stdout=payload if isinstance(payload, str) else json.dumps(payload))

    monkeypatch.setattr("llmbench.telemetry.command_exists", lambda name: name == "rocm-smi")
    monkeypatch.setattr("llmbench.telemetry.run_capture", run)
    provider = AmdProvider()
    provider.initialized = True
    return provider


_AMD_FULL = {
    "GPU use (%)": "35", "GPU memory use (%)": "12",
    "VRAM Total Used Memory (B)": "1073741824", "VRAM Total Memory (B)": "17179869184",
    "Temperature (Sensor edge) (C)": "55.0", "Average Graphics Package Power (W)": "120.5",
}


# ------------------------------------------------------------------ AMD


def test_amd_normal_response_maps_every_field(monkeypatch):
    (sample,) = _amd(monkeypatch, {"card0": _AMD_FULL}).sample_gpus()
    assert (sample.util_gpu_percent, sample.temperature_c, sample.power_w) == (35.0, 55.0, 120.5)
    assert sample.memory_total_bytes == 17179869184


def test_amd_missing_sensors_stay_none_and_are_never_invented_as_zero(monkeypatch):
    (sample,) = _amd(monkeypatch, {"card0": {"Average Graphics Package Power (W)": "80"}}).sample_gpus()
    assert sample.power_w == 80.0
    for field in ("util_gpu_percent", "util_memory_percent", "memory_used_bytes", "memory_total_bytes", "temperature_c"):
        assert getattr(sample, field) is None, field


def test_amd_real_zero_is_kept_as_zero(monkeypatch):
    info = dict(_AMD_FULL, **{"GPU use (%)": "0", "Average Graphics Package Power (W)": "0"})
    (sample,) = _amd(monkeypatch, {"card0": info}).sample_gpus()
    assert sample.util_gpu_percent == 0.0 and sample.power_w == 0.0


@pytest.mark.parametrize("payload", ["", "not json", "[]", "null", '{"card0": "oops"}', '{"system": {}}'])
def test_amd_malformed_output_yields_no_samples(monkeypatch, payload):
    assert _amd(monkeypatch, payload).sample_gpus() == []


def test_amd_non_numeric_values_become_none(monkeypatch):
    info = dict(_AMD_FULL, **{"GPU use (%)": "N/A", "Temperature (Sensor edge) (C)": "n/a"})
    (sample,) = _amd(monkeypatch, {"card0": info}).sample_gpus()
    assert sample.util_gpu_percent is None and sample.temperature_c is None
    assert sample.power_w == 120.5


def test_amd_timeout_yields_no_samples(monkeypatch):
    provider = _amd(monkeypatch, {}, raises=subprocess.TimeoutExpired(cmd="rocm-smi", timeout=10))
    assert provider.sample_gpus() == []


# ---------------------------------------------------------------- Intel


_XPU_DISCOVERY = json.dumps({"device_list": [{"device_id": 0}, {"device_id": 1}]})


def _xpu_payload(**values):
    return json.dumps({"device_level": [{"metrics_type": k, "value": v} for k, v in values.items()]})


def _intel(monkeypatch, by_id) -> IntelProvider:
    def run(cmd, **_kwargs):
        if cmd[:2] == ["xpu-smi", "discovery"]:
            return _cp(stdout=_XPU_DISCOVERY)
        outcome = by_id[int(cmd[3])]
        if isinstance(outcome, Exception):
            raise outcome
        return _cp(stdout=outcome)

    monkeypatch.setattr("llmbench.telemetry.command_exists", lambda name: name == "xpu-smi")
    monkeypatch.setattr("llmbench.telemetry.run_capture", run)
    provider = IntelProvider()
    assert provider.initialize() is True
    return provider


_GOOD = _xpu_payload(XPUM_STATS_GPU_UTILIZATION=50, XPUM_STATS_POWER=90.0, XPUM_STATS_GPU_CORE_TEMPERATURE=60)


@pytest.mark.parametrize(
    "bad",
    ["", "garbage", "[]", "null", subprocess.TimeoutExpired(cmd="xpu-smi", timeout=3)],
    ids=["empty", "garbage", "list", "null", "timeout"],
)
def test_intel_failed_device_keeps_position_with_all_none(monkeypatch, bad):
    first, second = _intel(monkeypatch, {0: bad, 1: _GOOD}).sample_gpus()
    assert (first.index, second.index) == (0, 1)
    assert all(getattr(first, field) is None for field in METRIC_FIELDS)
    assert second.util_gpu_percent == 50.0 and second.power_w == 90.0


def test_intel_missing_sensor_is_none_not_zero(monkeypatch):
    first, _ = _intel(monkeypatch, {0: _xpu_payload(XPUM_STATS_POWER=40.0), 1: _GOOD}).sample_gpus()
    assert first.power_w == 40.0
    assert first.util_gpu_percent is None and first.temperature_c is None


# ----------------------------------------------------------- Composite


class _Scripted(TelemetryProvider):
    """Provider returning scripted rounds; an exception entry simulates a crash."""

    TELEMETRY_SOURCE = "scripted"

    def __init__(self, rounds):
        super().__init__()
        self.rounds = list(rounds)
        self.initialized = True

    def initialize(self) -> bool:
        return True

    def sample_gpus(self):
        outcome = self.rounds.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def shutdown(self) -> None:
        self.initialized = False


def _gpu(power: float | None = 100.0, util: float | None = 10.0) -> GpuSample:
    sample = _empty_sample(0)
    sample.power_w = power
    sample.util_gpu_percent = util
    return sample


def test_mixed_vendor_order_is_stable_and_reindexed():
    nvidia = _Scripted([[_gpu(power=300.0)]] * 2)
    amd = _Scripted([[_gpu(power=200.0), _gpu(power=210.0)]] * 2)
    intel = _Scripted([[_gpu(power=90.0)]] * 2)
    composite = CompositeProvider([nvidia, amd, intel])
    for _ in range(2):
        samples = composite.sample_gpus()
        assert [s.index for s in samples] == [0, 1, 2, 3]
        assert [s.power_w for s in samples] == [300.0, 200.0, 210.0, 90.0]


@pytest.mark.parametrize("failure", ["empty", "exception"])
def test_two_gpu_failure_keeps_following_device_position(failure):
    """If the AMD provider drops out, the Intel GPU must stay at position 2."""
    broken = [] if failure == "empty" else RuntimeError("rocm-smi crashed")
    amd = _Scripted([[_gpu(power=200.0), _gpu(power=210.0)], broken])
    intel = _Scripted([[_gpu(power=90.0)], [_gpu(power=91.0)]])
    composite = CompositeProvider([amd, intel])

    first = composite.sample_gpus()
    second = composite.sample_gpus()

    assert [s.power_w for s in first] == [200.0, 210.0, 90.0]
    assert [s.index for s in second] == [0, 1, 2]
    assert second[0].power_w is None and second[1].power_w is None
    assert all(getattr(second[0], f) is None for f in METRIC_FIELDS)
    assert second[2].power_w == 91.0


def test_composite_partial_loss_pads_only_the_missing_device():
    amd = _Scripted([[_gpu(power=200.0), _gpu(power=210.0)], [_gpu(power=201.0)]])
    second_round = (lambda c: (c.sample_gpus(), c.sample_gpus())[1])(CompositeProvider([amd]))
    assert [s.power_w for s in second_round] == [201.0, None]


# ------------------------------------------------------------- Monitor


def _monitor_with(samples, interval: float = 0.5) -> ResourceMonitor:
    monitor = ResourceMonitor(interval=interval)
    monitor._samples = samples
    return monitor


def _sample(ts: float, gpus, duration: float = 0.01):
    return {
        "ts": ts, "monotonic_ts": ts, "sample_duration_seconds": duration,
        "cpu_percent": 1.0, "ram_used_bytes": 1,
        "cpu": {"package_power_w": None, "package_energy_delta_j": None},
        "gpus": [g.__dict__ for g in gpus],
    }


def test_summary_reports_units_and_sampling_quality():
    samples = [_sample(t, [_gpu()], duration=0.02) for t in (0.0, 0.5, 1.1, 1.5)]
    summary = _monitor_with(samples).summary()

    assert summary["units"] == TELEMETRY_UNITS
    sampling = summary["sampling"]
    assert sampling["requested_interval_seconds"] == 0.5
    assert sampling["sample_count"] == 4
    assert sampling["observed_interval_max_seconds"] == pytest.approx(0.6)
    assert sampling["interval_jitter_seconds"] > 0
    assert sampling["sampler_duration_mean_seconds"] == pytest.approx(0.02)
    assert 0 < sampling["sampler_overhead_fraction"] < 0.1


def test_summary_sampling_quality_is_none_not_zero_without_enough_samples():
    sampling = _monitor_with([_sample(0.0, [_gpu()])]).summary()["sampling"]
    assert sampling["observed_interval_mean_seconds"] is None
    assert sampling["interval_jitter_seconds"] is None
    assert sampling["sampler_overhead_fraction"] is None


def test_sample_completeness_reports_gaps_per_sensor():
    gpus = [_gpu(power=100.0), _gpu(power=None), _gpu(power=100.0), _gpu(power=None)]
    summary = _monitor_with([_sample(float(i), [g]) for i, g in enumerate(gpus)]).summary()
    completeness = summary["gpus"][0]["sample_completeness"]
    assert completeness["power_w"] == 0.5
    assert completeness["util_gpu_percent"] == 1.0


def test_device_missing_in_some_samples_counts_as_incomplete():
    samples = [_sample(0.0, [_gpu(), _gpu()]), _sample(1.0, [_gpu()])]
    summary = _monitor_with(samples).summary()
    assert summary["gpus"][1]["sample_completeness"]["power_w"] == 0.5


def test_stale_sampler_gap_is_not_integrated_into_energy():
    """A 60 s hole between two samples is unknown, not 60 s of constant power."""
    stalled = [_sample(0.0, [_gpu(power=100.0)]), _sample(60.0, [_gpu(power=100.0)])]
    assert _monitor_with(stalled).summary()["gpus"][0]["energy_j"] is None

    steady = [_sample(0.0, [_gpu(power=100.0)]), _sample(1.0, [_gpu(power=100.0)])]
    assert _monitor_with(steady).summary()["gpus"][0]["energy_j"] == pytest.approx(100.0)


def test_integrate_power_gap_limit_restarts_after_the_gap():
    samples = [{"ts": t, "p": 10.0} for t in (0.0, 1.0, 100.0, 101.0)]
    energy, seconds = _integrate_power(samples, lambda s: s["p"], max_gap_seconds=5.0)
    assert energy == pytest.approx(20.0) and seconds == pytest.approx(2.0)


def test_partial_gpu_telemetry_never_fabricates_zero_energy():
    samples = [_sample(float(i), [_gpu(power=None)]) for i in range(3)]
    summary = _monitor_with(samples).summary()
    gpu = summary["gpus"][0]
    assert gpu["energy_j"] is None and gpu["avg_power_w"] is None
    assert summary["power"]["component_energy_j"] is None
