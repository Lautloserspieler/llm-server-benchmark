import sys
import types

from llmbench.telemetry import DefaultProvider, GpuSample, NvidiaProvider, get_telemetry_provider


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
    provider = get_telemetry_provider()
    assert isinstance(provider, DefaultProvider)
