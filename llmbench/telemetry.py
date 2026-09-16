from __future__ import annotations

import abc
import contextlib
import json
from dataclasses import dataclass
from typing import Any

from .utils import command_exists, run_capture


@dataclass
class GpuSample:
    index: int
    util_gpu_percent: float
    util_memory_percent: float
    memory_used_bytes: int
    memory_total_bytes: int
    temperature_c: float
    power_w: float | None
    compute_pids: list[int]


class TelemetryProvider(abc.ABC):
    """Base class for hardware telemetry providers."""

    def __init__(self) -> None:
        self.initialized = False

    @abc.abstractmethod
    def initialize(self) -> bool:
        """Initialize the provider. Return True if successful."""
        ...

    @abc.abstractmethod
    def sample_gpus(self) -> list[GpuSample]:
        """Sample current GPU metrics."""
        ...

    @abc.abstractmethod
    def shutdown(self) -> None:
        """Clean up resources."""
        ...


class NvidiaProvider(TelemetryProvider):
    """NVML-based telemetry for NVIDIA GPUs with singleton initialization."""

    TELEMETRY_SOURCE: str = "nvml"

    _instance: NvidiaProvider | None = None
    _initialized_once: bool = False

    def __new__(cls) -> NvidiaProvider:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if NvidiaProvider._initialized_once:
            return
        super().__init__()
        self._nvml: Any = None
        self._handles: list[Any] = []
        NvidiaProvider._initialized_once = True

    def initialize(self) -> bool:
        if self.initialized:
            return True
        try:
            import pynvml
            pynvml.nvmlInit()
            self._nvml = pynvml
            self._handles = [
                pynvml.nvmlDeviceGetHandleByIndex(i)
                for i in range(pynvml.nvmlDeviceGetCount())
            ]
            self.initialized = True
            return True
        except Exception:
            self.initialized = False
            return False

    def sample_gpus(self) -> list[GpuSample]:
        if not self._nvml:
            return []

        out = []
        for idx, h in enumerate(self._handles):
            try:
                mem = self._nvml.nvmlDeviceGetMemoryInfo(h)
                util = self._nvml.nvmlDeviceGetUtilizationRates(h)
                temp = self._nvml.nvmlDeviceGetTemperature(h, self._nvml.NVML_TEMPERATURE_GPU)

                power_w = None
                with contextlib.suppress(Exception):
                    power_w = self._nvml.nvmlDeviceGetPowerUsage(h) / 1000.0

                pids: list[int] = []
                with contextlib.suppress(Exception):
                    pids = [
                        int(p.pid)
                        for p in self._nvml.nvmlDeviceGetComputeRunningProcesses(h)
                    ]

                out.append(
                    GpuSample(
                        index=idx,
                        util_gpu_percent=float(util.gpu),
                        util_memory_percent=float(util.memory),
                        memory_used_bytes=int(mem.used),
                        memory_total_bytes=int(mem.total),
                        temperature_c=float(temp),
                        power_w=power_w,
                        compute_pids=pids,
                    )
                )
            except Exception:
                continue
        return out

    def shutdown(self) -> None:
        if self._nvml:
            with contextlib.suppress(Exception):
                self._nvml.nvmlShutdown()
        self._nvml = None
        self._handles = []
        self.initialized = False
        NvidiaProvider._instance = None
        NvidiaProvider._initialized_once = False


class AmdProvider(TelemetryProvider):
    """rocm-smi-based telemetry for AMD GPUs.

    Unlike NvidiaProvider (NVML, a persistent library handle), rocm-smi is a
    CLI tool: every sample is its own subprocess call, so there is no handle
    to hold onto and shutdown() is a no-op.
    """

    TELEMETRY_SOURCE: str = "rocm_smi"

    # Candidate JSON key names per metric, tried in order. rocm-smi's key
    # naming has changed across ROCm releases (spacing, sensor naming,
    # "Average" vs "Current" power), so we probe a short list of known
    # variants instead of hardcoding a single key. NOTE: these candidates are
    # based on documented/observed rocm-smi flag and key names, not verified
    # against a real device in this sandbox (no rocm-smi binary available
    # here) - please sanity-check against `rocm-smi --showuse --showmeminfo
    # vram --showtemp --showpower --json` on real AMD hardware before
    # relying on this in production.
    _UTIL_KEYS = ("GPU use (%)", "GPU Use (%)")
    _MEM_UTIL_KEYS = ("GPU memory use (%)", "GPU Memory Allocated (VRAM%)")
    _MEM_USED_BYTES_KEYS = ("VRAM Total Used Memory (B)",)
    _MEM_TOTAL_BYTES_KEYS = ("VRAM Total Memory (B)",)
    # MiB-flavored fallbacks seen on some older/alternate rocm-smi builds.
    _MEM_USED_MB_KEYS = ("VRAM Total Used Memory (MB)", "GPU Memory Used (MB)")
    _MEM_TOTAL_MB_KEYS = ("VRAM Total Memory (MB)", "GPU Memory Total (MB)")
    _TEMP_KEYS = (
        "Temperature (Sensor edge) (C)",
        "Temperature (Sensor junction) (C)",
        "Temperature (Sensor mem) (C)",
        "Temperature (C)",
    )
    _POWER_KEYS = (
        "Average Graphics Package Power (W)",
        "Current Socket Graphics Package Power (W)",
        "Average Graphics Package Power(W)",
        "Card Power (W)",
    )

    def __init__(self) -> None:
        super().__init__()

    def initialize(self) -> bool:
        if not command_exists("rocm-smi"):
            self.initialized = False
            return False
        try:
            # Lightweight probe: confirm the tool actually runs (driver
            # loaded, permissions ok, ...), not just that the binary exists.
            cp = run_capture(["rocm-smi", "--showuse", "--json"], timeout=5)
            if cp.returncode != 0:
                self.initialized = False
                return False
            json.loads(cp.stdout)
            self.initialized = True
            return True
        except Exception:
            self.initialized = False
            return False

    @staticmethod
    def _first_value(info: dict[str, Any], keys: tuple[str, ...]) -> Any:
        for key in keys:
            if key in info:
                return info[key]
        return None

    @classmethod
    def _first_float(cls, info: dict[str, Any], keys: tuple[str, ...]) -> float | None:
        raw = cls._first_value(info, keys)
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _memory_bytes(
        cls, info: dict[str, Any], bytes_keys: tuple[str, ...], mb_keys: tuple[str, ...]
    ) -> int | None:
        raw_bytes = cls._first_float(info, bytes_keys)
        if raw_bytes is not None:
            return int(raw_bytes)
        # Fallback: some rocm-smi builds report VRAM in MB instead of bytes.
        raw_mb = cls._first_float(info, mb_keys)
        if raw_mb is not None:
            return int(raw_mb * 1024 * 1024)
        return None

    def sample_gpus(self) -> list[GpuSample]:
        if not self.initialized:
            return []
        try:
            cp = run_capture(
                ["rocm-smi", "--showuse", "--showmeminfo", "vram", "--showtemp",
                 "--showpower", "--json"],
                timeout=10,
            )
            if cp.returncode != 0:
                return []
            data = json.loads(cp.stdout)
        except Exception:
            return []

        out: list[GpuSample] = []
        for card_id, info in data.items():
            if not isinstance(info, dict) or not card_id.startswith("card"):
                continue
            try:
                index = int(card_id.removeprefix("card"))
            except ValueError:
                continue

            util_gpu = self._first_float(info, self._UTIL_KEYS) or 0.0
            util_mem = self._first_float(info, self._MEM_UTIL_KEYS) or 0.0
            mem_used = self._memory_bytes(info, self._MEM_USED_BYTES_KEYS, self._MEM_USED_MB_KEYS)
            mem_total = self._memory_bytes(
                info, self._MEM_TOTAL_BYTES_KEYS, self._MEM_TOTAL_MB_KEYS
            )
            temp = self._first_float(info, self._TEMP_KEYS) or 0.0
            power = self._first_float(info, self._POWER_KEYS)

            out.append(
                GpuSample(
                    index=index,
                    util_gpu_percent=util_gpu,
                    util_memory_percent=util_mem,
                    memory_used_bytes=mem_used or 0,
                    memory_total_bytes=mem_total or 0,
                    temperature_c=temp,
                    power_w=power,
                    # rocm-smi's per-process GPU usage needs a separate call
                    # (--showpids) that isn't easily combined with the single
                    # metrics call above without doubling subprocess overhead
                    # per sample. Known gap vs. NVML; monitor.py's foreign-
                    # process detection already degrades gracefully to an
                    # empty diff when compute_pids is empty.
                    compute_pids=[],
                )
            )
        return out

    def shutdown(self) -> None:
        # No persistent handle to release - each sample is its own
        # subprocess call.
        self.initialized = False


class DefaultProvider(TelemetryProvider):
    """Fallback provider that samples nothing for GPUs."""

    TELEMETRY_SOURCE: str = "none"

    def initialize(self) -> bool:
        self.initialized = True
        return True

    def sample_gpus(self) -> list[GpuSample]:
        return []

    def shutdown(self) -> None:
        pass


class CompositeProvider(TelemetryProvider):
    """Combines several vendor providers into one, for multi-vendor systems.

    sample_gpus() concatenates each sub-provider's samples in a fixed,
    deterministic order (NVIDIA first, then AMD - see get_telemetry_provider)
    and reassigns `index` sequentially across the combined list, since
    monitor.py aggregates per-GPU stats by indexing into `s["gpus"][idx]` and
    assumes a stable ordering across samples.
    """

    TELEMETRY_SOURCE: str = "composite"

    def __init__(self, providers: list[TelemetryProvider]) -> None:
        super().__init__()
        self._providers = providers
        self.initialized = bool(providers)

    def initialize(self) -> bool:
        # Sub-providers are expected to already be initialized by the
        # factory before being handed to CompositeProvider.
        self.initialized = bool(self._providers)
        return self.initialized

    def sample_gpus(self) -> list[GpuSample]:
        out: list[GpuSample] = []
        next_index = 0
        for provider in self._providers:
            for sample in provider.sample_gpus():
                sample.index = next_index
                out.append(sample)
                next_index += 1
        return out

    def shutdown(self) -> None:
        for provider in self._providers:
            with contextlib.suppress(Exception):
                provider.shutdown()
        self.initialized = False


def get_telemetry_provider() -> TelemetryProvider:
    """
    Factory to select the best available telemetry provider(s).

    Tries every known vendor provider and keeps the ones that initialize
    successfully. If exactly one succeeds, that bare provider is returned
    directly (not wrapped in CompositeProvider) so `telemetry_source`
    reporting stays maximally backward-compatible with existing result
    files (e.g. the common NVIDIA-only case keeps reporting "nvml" instead
    of "composite"). Only when 2+ providers succeed - a rare multi-vendor
    box - do we wrap them in CompositeProvider to combine their samples.

    Extension point: add a future IntelProvider (Phase E) to this list once
    it exists; no other changes needed here.
    """
    candidates: list[TelemetryProvider] = [NvidiaProvider(), AmdProvider()]
    initialized = [p for p in candidates if p.initialize()]

    if len(initialized) == 1:
        return initialized[0]
    if len(initialized) >= 2:
        return CompositeProvider(initialized)

    return DefaultProvider()
