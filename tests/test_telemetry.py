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
