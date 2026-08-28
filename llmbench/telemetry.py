from __future__ import annotations

import abc
import contextlib
from dataclasses import dataclass
from typing import Any


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
    """NVML-based telemetry for NVIDIA GPUs."""

    def __init__(self) -> None:
        super().__init__()
        self._nvml: Any = None
        self._handles: list[Any] = []

    def initialize(self) -> bool:
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


class DefaultProvider(TelemetryProvider):
    """Fallback provider that samples nothing for GPUs."""

    def initialize(self) -> bool:
        self.initialized = True
        return True

    def sample_gpus(self) -> list[GpuSample]:
        return []

    def shutdown(self) -> None:
        pass


def get_telemetry_provider() -> TelemetryProvider:
    """
    Factory to select the best available telemetry provider.
    Currently prioritizes NVIDIA.
    """
    # Try NVIDIA first
    nv = NvidiaProvider()
    if nv.initialize():
        return nv

    # Fallback
    return DefaultProvider()
