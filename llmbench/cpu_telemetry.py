from __future__ import annotations

import abc
import contextlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import psutil


@dataclass
class CpuSample:
    frequency_mhz: float | None
    temperature_c: float | None
    package_power_w: float | None


class CpuTelemetryProvider(abc.ABC):
    """Base class for optional CPU telemetry providers."""

    TELEMETRY_SOURCE = "none"

    def __init__(self) -> None:
        self.initialized = False

    @abc.abstractmethod
    def initialize(self) -> bool:
        ...

    @abc.abstractmethod
    def sample_cpu(self) -> CpuSample:
        ...

    @abc.abstractmethod
    def shutdown(self) -> None:
        ...


class _RaplEnergyReader:
    """Read Linux powercap package-energy counters and derive package power."""

    def __init__(
        self,
        root: Path = Path("/sys/class/powercap"),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.root = root
        self.clock = clock
        self._zones: list[tuple[Path, float | None]] = []
        self._previous_energy_uj: list[float] | None = None
        self._previous_ts: float | None = None

    def initialize(self) -> bool:
        self._zones = []
        if not self.root.exists():
            return False

        for energy_path in sorted(self.root.glob("*/energy_uj")):
            zone = energy_path.parent
            name = ""
            with contextlib.suppress(Exception):
                name = (zone / "name").read_text(encoding="utf-8").strip().lower()

            # Only top-level package/socket domains belong here. Subdomains
            # such as cores/uncore/dram would otherwise double-count power.
            if name and not (
                name.startswith("package")
                or name.startswith("socket")
                or name in {"pkg", "package"}
            ):
                continue

            max_range: float | None = None
            with contextlib.suppress(Exception):
                max_range = float(
                    (zone / "max_energy_range_uj").read_text(encoding="utf-8").strip()
                )
            self._zones.append((energy_path, max_range))

        return bool(self._zones)

    @staticmethod
    def _read_energy(path: Path) -> float | None:
        try:
            return float(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def sample_power_w(self) -> float | None:
        if not self._zones:
            return None

        now = self.clock()
        current = [self._read_energy(path) for path, _max_range in self._zones]
        if any(value is None for value in current):
            self._previous_energy_uj = None
            self._previous_ts = now
            return None

        values = [float(value) for value in current if value is not None]
        if self._previous_energy_uj is None or self._previous_ts is None:
            self._previous_energy_uj = values
            self._previous_ts = now
            return None

        elapsed = now - self._previous_ts
        if elapsed <= 0:
            self._previous_energy_uj = values
            self._previous_ts = now
            return None

        delta_uj = 0.0
        for current_uj, previous_uj, (_path, max_range) in zip(
            values, self._previous_energy_uj, self._zones, strict=False
        ):
            delta = current_uj - previous_uj
            if delta < 0:
                if max_range is None or max_range <= previous_uj:
                    self._previous_energy_uj = values
                    self._previous_ts = now
                    return None
                delta = (max_range - previous_uj) + current_uj
            delta_uj += delta

        self._previous_energy_uj = values
        self._previous_ts = now
        return (delta_uj / 1_000_000.0) / elapsed

    def shutdown(self) -> None:
        self._previous_energy_uj = None
        self._previous_ts = None


class PsutilCpuProvider(CpuTelemetryProvider):
    """Portable CPU frequency plus best-effort temperature telemetry."""

    TELEMETRY_SOURCE = "psutil"

    _CPU_SENSOR_KEYS = (
        "coretemp",
        "k10temp",
        "zenpower",
        "cpu_thermal",
        "cpu-thermal",
    )
    _CPU_LABEL_HINTS = (
        "package",
        "tctl",
        "tdie",
        "cpu",
    )

    def initialize(self) -> bool:
        self.initialized = True
        return True

    @staticmethod
    def _frequency_mhz() -> float | None:
        with contextlib.suppress(Exception):
            freq = psutil.cpu_freq()
            if freq and freq.current is not None:
                return float(freq.current)
        return None

    @classmethod
    def _temperature_c(cls) -> float | None:
        sensors_fn = getattr(psutil, "sensors_temperatures", None)
        if not callable(sensors_fn):
            return None
        try:
            sensors = sensors_fn(fahrenheit=False) or {}
        except (OSError, RuntimeError):
            return None

        preferred: list[float] = []
        fallback: list[float] = []
        for chip, entries in sensors.items():
            chip_l = str(chip).lower()
            for entry in entries or []:
                current = getattr(entry, "current", None)
                if current is None:
                    continue
                value = float(current)
                label = str(getattr(entry, "label", "") or "").lower()
                if chip_l in cls._CPU_SENSOR_KEYS or any(
                    hint in label for hint in cls._CPU_LABEL_HINTS
                ):
                    preferred.append(value)
                elif "cpu" in chip_l:
                    fallback.append(value)

        values = preferred or fallback
        return max(values) if values else None

    def sample_cpu(self) -> CpuSample:
        return CpuSample(
            frequency_mhz=self._frequency_mhz(),
            temperature_c=self._temperature_c(),
            package_power_w=None,
        )

    def shutdown(self) -> None:
        self.initialized = False


class LinuxRaplCpuProvider(PsutilCpuProvider):
    """Linux CPU telemetry with package power derived from powercap/RAPL."""

    TELEMETRY_SOURCE = "psutil+powercap"

    def __init__(
        self,
        powercap_root: Path = Path("/sys/class/powercap"),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        self._rapl = _RaplEnergyReader(powercap_root, clock)

    def initialize(self) -> bool:
        super().initialize()
        self._rapl.initialize()
        return True

    def sample_cpu(self) -> CpuSample:
        base = super().sample_cpu()
        return CpuSample(
            frequency_mhz=base.frequency_mhz,
            temperature_c=base.temperature_c,
            package_power_w=self._rapl.sample_power_w(),
        )

    def shutdown(self) -> None:
        self._rapl.shutdown()
        super().shutdown()


def get_cpu_telemetry_provider() -> CpuTelemetryProvider:
    """Return the best available CPU telemetry provider for this platform."""
    if os.name == "posix" and Path("/sys/class/powercap").exists():
        provider = LinuxRaplCpuProvider()
        provider.initialize()
        return provider

    provider = PsutilCpuProvider()
    provider.initialize()
    return provider
