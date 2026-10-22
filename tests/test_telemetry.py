import json
import subprocess
import sys
import types

import pytest

from llmbench.telemetry import (
    AmdProvider,
    CompositeProvider,
    DefaultProvider,
    GpuSample,
    IntelProvider,
    NvidiaProvider,
    get_telemetry_provider,
)


@pytest.fixture(autouse=True)
def reset_nvidia_provider():
    NvidiaProvider().shutdown()
    yield
    NvidiaProvider().shutdown()


class _FakeMemInfo:
    def __init__(self, used, total):
        self.used = used
        self.total = total


class _FakeUtil:
    def __init__(self, gpu, memory):
        self.gpu = gpu
        self.memory = memory


class _FakeProc:
    def __init__(self, pid):
        self.pid = pid


def _install_fake_pynvml(monkeypatch, *, handle_count=1, power_raises=False, pids=None):
    fake = types.SimpleNamespace()
    fake.NVML_TEMPERATURE_GPU = 0
    fake.nvmlInit = lambda: None
    fake.nvmlShutdown = lambda: None
    fake.nvmlDeviceGetCount = lambda: handle_count
    fake.nvmlDeviceGetHandleByIndex = lambda i: i
    fake.nvmlDeviceGetMemoryInfo = lambda _h: _FakeMemInfo(used=1000, total=8000)
    fake.nvmlDeviceGetUtilizationRates = lambda _h: _FakeUtil(gpu=42, memory=17)
    fake.nvmlDeviceGetTemperature = lambda _h, _sensor: 65.0

    if power_raises:
        def _power(_h):
            raise RuntimeError("no power reading")
        fake.nvmlDeviceGetPowerUsage = _power
    else:
        fake.nvmlDeviceGetPowerUsage = lambda _h: 150000.0

    fake.nvmlDeviceGetComputeRunningProcesses = lambda _h: [_FakeProc(p) for p in (pids or [4321])]

    monkeypatch.setitem(sys.modules, "pynvml", fake)
    return fake


def test_nvidia_provider_initializes_and_samples(monkeypatch):
    _install_fake_pynvml(monkeypatch, handle_count=2)
    provider = NvidiaProvider()
    assert provider.initialize() is True
    assert provider.initialized is True

    samples = provider.sample_gpus()
    assert len(samples) == 2
    first = samples[0]
    assert isinstance(first, GpuSample)
    assert first.util_gpu_percent == 42.0
    assert first.memory_used_bytes == 1000
    assert first.power_w == 150.0
    assert first.compute_pids == [4321]

    provider.shutdown()
    assert provider.initialized is False
    assert provider.sample_gpus() == []


def test_nvidia_provider_missing_pynvml_fails_to_initialize(monkeypatch):
    monkeypatch.setitem(sys.modules, "pynvml", None)
    provider = NvidiaProvider()
    assert provider.initialize() is False
    assert provider.initialized is False


def test_nvidia_provider_power_read_failure_still_yields_a_sample(monkeypatch):
    _install_fake_pynvml(monkeypatch, power_raises=True)
    provider = NvidiaProvider()
    provider.initialize()
    samples = provider.sample_gpus()
    assert len(samples) == 1
    assert samples[0].power_w is None


def test_default_provider_samples_nothing():
    provider = DefaultProvider()
    assert provider.initialize() is True
    assert provider.sample_gpus() == []
    provider.shutdown()


def test_get_telemetry_provider_prefers_nvidia_when_available(monkeypatch):
    _install_fake_pynvml(monkeypatch)
    provider = get_telemetry_provider()
    assert isinstance(provider, NvidiaProvider)


def test_get_telemetry_provider_falls_back_without_nvidia(monkeypatch):
    monkeypatch.setitem(sys.modules, "pynvml", None)
    monkeypatch.setattr("llmbench.telemetry.command_exists", lambda _name: False)
    provider = get_telemetry_provider()
    assert isinstance(provider, DefaultProvider)


# --------------------------------------------------------------------- AMD


def _cp(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(["rocm-smi"], returncode, stdout=stdout, stderr=stderr)


_ROCM_SMI_PAYLOAD = json.dumps({
    "card0": {
        "GPU use (%)": "42",
        "GPU memory use (%)": "17",
        "VRAM Total Used Memory (B)": "1000",
        "VRAM Total Memory (B)": "8000",
        "Temperature (Sensor edge) (C)": "65.0",
        "Average Graphics Package Power (W)": "150.0",
    },
    "system": {"foo": "bar"},
})


def test_amd_provider_initializes_when_rocm_smi_is_present_and_probe_succeeds(monkeypatch):
    monkeypatch.setattr("llmbench.telemetry.command_exists", lambda name: name == "rocm-smi")
    monkeypatch.setattr(
        "llmbench.telemetry.run_capture", lambda _cmd, **_kwargs: _cp(stdout=_ROCM_SMI_PAYLOAD)
    )
    provider = AmdProvider()
    assert provider.initialize() is True
    assert provider.initialized is True


def test_amd_provider_initialize_returns_false_when_rocm_smi_binary_is_absent(monkeypatch):
    monkeypatch.setattr("llmbench.telemetry.command_exists", lambda _name: False)
    provider = AmdProvider()
    assert provider.initialize() is False
    assert provider.initialized is False


def test_amd_provider_initialize_returns_false_when_probe_call_fails(monkeypatch):
    monkeypatch.setattr("llmbench.telemetry.command_exists", lambda name: name == "rocm-smi")
    monkeypatch.setattr(
        "llmbench.telemetry.run_capture", lambda _cmd, **_kwargs: _cp(returncode=1)
    )
    provider = AmdProvider()
    assert provider.initialize() is False
    assert provider.initialized is False


def test_amd_provider_initialize_swallows_exceptions_from_run_capture(monkeypatch):
    monkeypatch.setattr("llmbench.telemetry.command_exists", lambda name: name == "rocm-smi")

    def _raise(_cmd, **_kwargs):
        raise OSError("no permission")

    monkeypatch.setattr("llmbench.telemetry.run_capture", _raise)
    provider = AmdProvider()
    assert provider.initialize() is False
    assert provider.initialized is False


def test_amd_provider_sample_gpus_maps_fields_and_normalizes_memory_to_bytes(monkeypatch):
    monkeypatch.setattr("llmbench.telemetry.command_exists", lambda name: name == "rocm-smi")
    monkeypatch.setattr(
        "llmbench.telemetry.run_capture", lambda _cmd, **_kwargs: _cp(stdout=_ROCM_SMI_PAYLOAD)
    )
    provider = AmdProvider()
    assert provider.initialize() is True

    samples = provider.sample_gpus()
    assert len(samples) == 1
    sample = samples[0]
    assert isinstance(sample, GpuSample)
    assert sample.index == 0
    assert sample.util_gpu_percent == 42.0
    assert sample.util_memory_percent == 17.0
    assert sample.memory_used_bytes == 1000
    assert sample.memory_total_bytes == 8000
    assert sample.temperature_c == 65.0
    assert sample.power_w == 150.0
    assert sample.compute_pids == []


def test_amd_provider_sample_gpus_falls_back_to_mb_keys_and_alternate_temp_key(monkeypatch):
    payload = json.dumps({
        "card1": {
            "GPU use (%)": "10",
            "GPU memory use (%)": "5",
            "VRAM Total Used Memory (MB)": "500",
            "VRAM Total Memory (MB)": "4000",
            "Temperature (Sensor junction) (C)": "55.0",
            "Card Power (W)": "80.0",
        }
    })
    monkeypatch.setattr("llmbench.telemetry.command_exists", lambda name: name == "rocm-smi")
    monkeypatch.setattr("llmbench.telemetry.run_capture", lambda _cmd, **_kwargs: _cp(stdout=payload))
    provider = AmdProvider()
    assert provider.initialize() is True

    samples = provider.sample_gpus()
    assert len(samples) == 1
    sample = samples[0]
    assert sample.index == 1
    assert sample.memory_used_bytes == 500 * 1024 * 1024
    assert sample.memory_total_bytes == 4000 * 1024 * 1024
    assert sample.temperature_c == 55.0
    assert sample.power_w == 80.0


def test_amd_provider_sample_gpus_returns_empty_when_not_initialized():
    provider = AmdProvider()
    assert provider.sample_gpus() == []


def test_amd_provider_sample_gpus_returns_empty_when_command_fails(monkeypatch):
    monkeypatch.setattr("llmbench.telemetry.command_exists", lambda name: name == "rocm-smi")
    monkeypatch.setattr(
        "llmbench.telemetry.run_capture", lambda _cmd, **_kwargs: _cp(stdout=_ROCM_SMI_PAYLOAD)
    )
    provider = AmdProvider()
    provider.initialize()

    monkeypatch.setattr("llmbench.telemetry.run_capture", lambda _cmd, **_kwargs: _cp(returncode=1))
    assert provider.sample_gpus() == []


def test_amd_provider_shutdown_is_a_noop_and_clears_initialized(monkeypatch):
    monkeypatch.setattr("llmbench.telemetry.command_exists", lambda name: name == "rocm-smi")
    monkeypatch.setattr(
        "llmbench.telemetry.run_capture", lambda _cmd, **_kwargs: _cp(stdout=_ROCM_SMI_PAYLOAD)
    )
    provider = AmdProvider()
    provider.initialize()
    provider.shutdown()
    assert provider.initialized is False


# --------------------------------------------------------------- Composite


def test_composite_provider_concatenates_and_reindexes_samples():
    nv_sample = GpuSample(
        index=0, util_gpu_percent=1.0, util_memory_percent=1.0,
        memory_used_bytes=1, memory_total_bytes=2, temperature_c=3.0,
        power_w=4.0, compute_pids=[111],
    )
    amd_sample = GpuSample(
        index=0, util_gpu_percent=5.0, util_memory_percent=5.0,
        memory_used_bytes=5, memory_total_bytes=6, temperature_c=7.0,
        power_w=8.0, compute_pids=[],
    )

    class _Stub(DefaultProvider):
        def __init__(self, samples):
            super().__init__()
            self._samples = samples

        def sample_gpus(self):
            return list(self._samples)

    nv = _Stub([nv_sample])
    amd = _Stub([amd_sample])
    composite = CompositeProvider([nv, amd])

    samples = composite.sample_gpus()
    assert [s.index for s in samples] == [0, 1]
    assert samples[0].util_gpu_percent == 1.0
    assert samples[1].util_gpu_percent == 5.0


def test_composite_provider_shutdown_shuts_down_all_sub_providers():
    class _Tracking(DefaultProvider):
        def __init__(self):
            super().__init__()
            self.shutdown_called = False

        def shutdown(self):
            self.shutdown_called = True

    a, b = _Tracking(), _Tracking()
    CompositeProvider([a, b]).shutdown()
    assert a.shutdown_called is True
    assert b.shutdown_called is True


def test_get_telemetry_provider_wraps_in_composite_when_nvidia_and_amd_both_succeed(monkeypatch):
    _install_fake_pynvml(monkeypatch)
    monkeypatch.setattr("llmbench.telemetry.command_exists", lambda name: name == "rocm-smi")
    monkeypatch.setattr(
        "llmbench.telemetry.run_capture", lambda _cmd, **_kwargs: _cp(stdout=_ROCM_SMI_PAYLOAD)
    )

    provider = get_telemetry_provider()
    assert isinstance(provider, CompositeProvider)
    assert provider.TELEMETRY_SOURCE == "composite"


def test_get_telemetry_provider_returns_bare_amd_provider_when_only_amd_succeeds(monkeypatch):
    monkeypatch.setitem(sys.modules, "pynvml", None)
    monkeypatch.setattr("llmbench.telemetry.command_exists", lambda name: name == "rocm-smi")
    monkeypatch.setattr(
        "llmbench.telemetry.run_capture", lambda _cmd, **_kwargs: _cp(stdout=_ROCM_SMI_PAYLOAD)
    )

    provider = get_telemetry_provider()
    assert isinstance(provider, AmdProvider)
    assert not isinstance(provider, CompositeProvider)
    assert provider.TELEMETRY_SOURCE == "rocm_smi"

# ------------------------------------------------------------------- Intel


_XPU_DISCOVERY = json.dumps({"device_list": [
    {"device_id": 0, "device_name": "Intel(R) Arc(TM) A770", "memory_physical_size_byte": "17179869184"},
    {"device_id": 1, "device_name": "Intel(R) Arc(TM) A380"},
]})


def _xpu_stats(**values):
    return json.dumps({"device_id": 0, "device_level": [
        {"metrics_type": k, "value": v} for k, v in values.items()
    ]})


def _fake_xpu_smi(monkeypatch, stats_by_id, *, discovery=_XPU_DISCOVERY):
    calls = []

    def _run(cmd, **_kwargs):
        calls.append(list(cmd))
        if cmd[:2] == ["xpu-smi", "discovery"]:
            return _cp(stdout=discovery)
        if cmd[:2] == ["xpu-smi", "stats"]:
            payload = stats_by_id.get(int(cmd[3]))
            return _cp(returncode=0 if payload is not None else 1, stdout=payload or "")
        return _cp(returncode=1)

    monkeypatch.setattr("llmbench.telemetry.command_exists", lambda name: name == "xpu-smi")
    monkeypatch.setattr("llmbench.telemetry.run_capture", _run)
    return calls


def test_intel_provider_maps_fields_with_one_stats_call_per_gpu(monkeypatch):
    calls = _fake_xpu_smi(monkeypatch, {
        0: _xpu_stats(XPUM_STATS_GPU_UTILIZATION=42, XPUM_STATS_MEMORY_UTILIZATION=17.5,
                      XPUM_STATS_MEMORY_USED=1024, XPUM_STATS_GPU_CORE_TEMPERATURE=65.5,
                      XPUM_STATS_POWER=150.25),
        1: _xpu_stats(XPUM_STATS_GPU_UTILIZATION=3),
    })
    provider = IntelProvider()
    assert provider.initialize() is True
    samples = provider.sample_gpus()
    assert [c[:4] for c in calls if c[1] == "stats"] == [
        ["xpu-smi", "stats", "-d", "0"], ["xpu-smi", "stats", "-d", "1"]]
    assert all(c[-1] == "-j" for c in calls)
    first, second = samples
    assert (first.index, first.util_gpu_percent, first.util_memory_percent) == (0, 42.0, 17.5)
    assert first.memory_used_bytes == 1024 * 1024 * 1024
    assert first.memory_total_bytes == 17179869184
    assert (first.temperature_c, first.power_w, first.compute_pids) == (65.5, 150.25, [])
    assert provider.TELEMETRY_SOURCE == "xpu_smi"
    # Missing metrics stay None, never 0.
    assert second.util_gpu_percent == 3.0
    assert second.util_memory_percent is None
    assert second.memory_used_bytes is None
    assert second.memory_total_bytes is None
    assert second.temperature_c is None
    assert second.power_w is None


def test_intel_provider_non_numeric_values_become_none(monkeypatch):
    _fake_xpu_smi(monkeypatch, {0: _xpu_stats(XPUM_STATS_GPU_UTILIZATION="N/A", XPUM_STATS_POWER=None),
                                1: "{}"})
    provider = IntelProvider()
    assert provider.initialize()
    sample = provider.sample_gpus()[0]
    assert sample.util_gpu_percent is None
    assert sample.power_w is None


def test_intel_provider_absent_binary_fails_to_initialize(monkeypatch):
    monkeypatch.setattr("llmbench.telemetry.command_exists", lambda _name: False)
    provider = IntelProvider()
    assert provider.initialize() is False
    assert provider.sample_gpus() == []


def test_intel_provider_discovery_failures_fail_to_initialize(monkeypatch):
    monkeypatch.setattr("llmbench.telemetry.command_exists", lambda name: name == "xpu-smi")
    for result in (_cp(returncode=1), _cp(stdout="not json"), _cp(stdout=json.dumps({"device_list": []}))):
        monkeypatch.setattr("llmbench.telemetry.run_capture", lambda _c, _r=result, **_k: _r)
        assert IntelProvider().initialize() is False

    def _boom(_cmd, **_kwargs):
        raise OSError("boom")

    monkeypatch.setattr("llmbench.telemetry.run_capture", _boom)
    assert IntelProvider().initialize() is False


def test_intel_provider_failing_device_keeps_position_with_none_metrics(monkeypatch):
    _fake_xpu_smi(monkeypatch, {0: None, 1: _xpu_stats(XPUM_STATS_GPU_UTILIZATION=9)})
    provider = IntelProvider()
    assert provider.initialize()
    samples = provider.sample_gpus()
    # Device 0 fell out: it keeps its slot (monitor.py indexes positionally).
    assert [s.index for s in samples] == [0, 1]
    dead, alive = samples
    assert dead.util_gpu_percent is None and dead.util_memory_percent is None
    assert dead.memory_used_bytes is None and dead.temperature_c is None and dead.power_w is None
    assert dead.compute_pids == []
    assert alive.util_gpu_percent == 9.0
    provider.shutdown()
    assert provider.initialized is False
    assert provider.sample_gpus() == []


def test_intel_provider_ignores_memory_temperature(monkeypatch):
    _fake_xpu_smi(monkeypatch, {0: _xpu_stats(XPUM_STATS_MEMORY_TEMPERATURE=70), 1: "{}"})
    provider = IntelProvider()
    assert provider.initialize()
    assert provider.sample_gpus()[0].temperature_c is None


def test_intel_provider_uses_short_subprocess_timeout(monkeypatch):
    seen = []

    def _run(cmd, **kwargs):
        seen.append((cmd[1], kwargs.get("timeout")))
        return _cp(stdout=_XPU_DISCOVERY if cmd[1] == "discovery" else _xpu_stats())

    monkeypatch.setattr("llmbench.telemetry.command_exists", lambda name: name == "xpu-smi")
    monkeypatch.setattr("llmbench.telemetry.run_capture", _run)
    provider = IntelProvider()
    provider.initialize()
    provider.sample_gpus()
    assert [t for c, t in seen if c == "stats"] == [3, 3]


def test_nvidia_provider_failing_device_keeps_position(monkeypatch):
    fake = _install_fake_pynvml(monkeypatch, handle_count=2)

    def _mem(h):
        if h == 0:
            raise RuntimeError("GPU fell off the bus")
        return _FakeMemInfo(used=1000, total=8000)

    fake.nvmlDeviceGetMemoryInfo = _mem
    provider = NvidiaProvider()
    provider.initialize()
    samples = provider.sample_gpus()
    assert [s.index for s in samples] == [0, 1]
    assert samples[0].util_gpu_percent is None and samples[0].memory_used_bytes is None
    assert samples[0].compute_pids == []
    assert samples[1].util_gpu_percent == 42.0


def test_get_telemetry_provider_returns_bare_intel_provider_when_only_intel_succeeds(monkeypatch):
    monkeypatch.setitem(sys.modules, "pynvml", None)
    _fake_xpu_smi(monkeypatch, {0: _xpu_stats(XPUM_STATS_GPU_UTILIZATION=1), 1: "{}"})
    provider = get_telemetry_provider()
    assert isinstance(provider, IntelProvider)
    assert provider.TELEMETRY_SOURCE == "xpu_smi"


def test_get_telemetry_provider_wraps_amd_and_intel_in_composite(monkeypatch):
    monkeypatch.setitem(sys.modules, "pynvml", None)
    monkeypatch.setattr("llmbench.telemetry.command_exists", lambda name: name in {"rocm-smi", "xpu-smi"})

    def _run(cmd, **_kwargs):
        if cmd[0] == "rocm-smi":
            return _cp(stdout=_ROCM_SMI_PAYLOAD)
        if cmd[1] == "discovery":
            return _cp(stdout=json.dumps({"device_list": [{"device_id": 0}]}))
        return _cp(stdout=_xpu_stats(XPUM_STATS_GPU_UTILIZATION=5))

    monkeypatch.setattr("llmbench.telemetry.run_capture", _run)
    provider = get_telemetry_provider()
    assert isinstance(provider, CompositeProvider)
    assert [s.index for s in provider.sample_gpus()] == [0, 1]
