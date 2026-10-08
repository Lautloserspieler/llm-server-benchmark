from __future__ import annotations

import contextlib
import os
import statistics
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import psutil

from .cpu_telemetry import get_cpu_telemetry_provider
from .i18n import _
from .telemetry import get_telemetry_provider

# Vor jedem Test kurz warten, bis die GPU vom vorigen Test zur Ruhe kommt -
# sonst meldet die Baseline direkt nach einem GPU-Test faelschlich "ausgelastet".
IDLE_GPU_UTIL_PERCENT = 10.0
IDLE_WAIT_SECONDS = 15.0
BUSY_BASELINE_UTIL_PERCENT = 15.0


def _max_gpu_util(sample: dict[str, Any] | None) -> float:
    return max((float(g.get("util_gpu_percent") or 0) for g in (sample or {}).get("gpus") or []), default=0.0)


def _agg(items: list[dict[str, Any]], key: str) -> tuple[float | None, float | None]:
    """Mittelwert und Maximum einer Kennzahl. Einmal berechnen statt dreimal."""
    values = [float(x[key]) for x in items if x.get(key) is not None]
    if not values:
        return None, None
    return statistics.fmean(values), max(values)


def _integrate_power(
    samples: list[dict[str, Any]],
    getter: Callable[[dict[str, Any]], Any],
) -> tuple[float | None, float]:
    """Integrate sampled power using real timestamps and trapezoids.

    Missing values break an interval instead of being treated as zero or
    interpolated across an unknown gap.
    """
    energy_j = 0.0
    covered_seconds = 0.0
    previous_ts: float | None = None
    previous_power: float | None = None
    intervals = 0
    for sample in samples:
        ts = sample.get("ts")
        value = getter(sample)
        if ts is None or value is None:
            previous_ts = None
            previous_power = None
            continue
        try:
            current_ts = float(ts)
            current_power = float(value)
        except (TypeError, ValueError):
            previous_ts = None
            previous_power = None
            continue
        if current_power < 0:
            previous_ts = None
            previous_power = None
            continue
        if previous_ts is not None and previous_power is not None:
            elapsed = current_ts - previous_ts
            if elapsed > 0:
                energy_j += ((previous_power + current_power) / 2.0) * elapsed
                covered_seconds += elapsed
                intervals += 1
        previous_ts = current_ts
        previous_power = current_power
    return (energy_j if intervals else None), covered_seconds


def strip_samples(telemetry: dict[str, Any] | None) -> dict[str, Any]:
    """Telemetrie ohne die Rohsamples. Fuer summary.json, damit die Datei
    auch nach mehrstuendigen Laeufen lesbar gross bleibt."""
    if not telemetry:
        return {}
    out = {k: v for k, v in telemetry.items() if k != "samples"}
    out["samples_stored_in"] = "raw_*.json"
    return out


@dataclass
class ResourceMonitor:
    interval: float = 0.5
    _samples: list[dict[str, Any]] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    _provider: Any = None
    _cpu_provider: Any = None
    _target_pids: set[int] = field(default_factory=set)
    _own_pids: set[int] = field(default_factory=set)
    _seen_gpu_pids: set[int] = field(default_factory=set)
    _baseline: dict[str, Any] | None = None
    _max_samples: int = 100000  # Hard limit to prevent unbounded memory growth
    idle_wait_seconds: float = IDLE_WAIT_SECONDS

    # ------------------------------------------------------------------ start

    def start(self) -> None:
        self._samples = []
        self._seen_gpu_pids = set()
        self._own_pids = {os.getpid()} | self._target_pids
        self._stop.clear()
        psutil.cpu_percent(interval=None)
        self._provider = get_telemetry_provider()
        self._cpu_provider = get_cpu_telemetry_provider()
        self._baseline = self._wait_for_idle_gpu()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _wait_for_idle_gpu(self) -> dict[str, Any]:
        """Baseline erst nehmen, wenn die GPU ruhig ist (hoechstens idle_wait_seconds)."""
        sample = self._sample()
        deadline = time.monotonic() + max(0.0, float(self.idle_wait_seconds))
        while _max_gpu_util(sample) >= IDLE_GPU_UTIL_PERCENT and time.monotonic() < deadline:
            time.sleep(1.0)
            sample = self._sample()
        return sample

    def latest(self) -> dict[str, Any] | None:
        """Juengstes Sample fuer die Live-Anzeige.

        Der Sammel-Thread haengt nur an, deshalb genuegt der Zugriff auf das
        letzte Element ohne zusaetzliche Sperre.
        """
        samples = self._samples
        return samples[-1] if samples else self._baseline

    def set_target_pid(self, pid: int | None) -> None:
        """Prozess, dessen Last gemessen werden soll. Alles andere auf der GPU
        gilt danach als Fremdlast und wird im Ergebnis vermerkt."""
        if pid:
            self._target_pids.add(pid)
            self._own_pids.add(pid)

    def set_target_pids(self, pids: list[int]) -> None:
        """Wie set_target_pid, aber fuer mehrere gleichzeitig ueberwachte
        Prozesse - z. B. den CPU- und den GPU-Server im Soak-Test, die
        beide bewusst gleichzeitig laufen und sich nicht gegenseitig als
        Fremdlast melden sollen."""
        for pid in pids:
            self.set_target_pid(pid)

    # ----------------------------------------------------------------- sampling

    def _refresh_own_pids(self) -> None:
        if not self._target_pids:
            return
        for target_pid in list(self._target_pids):
            try:
                proc = psutil.Process(target_pid)
                self._own_pids.update(child.pid for child in proc.children(recursive=True))
            except Exception:
                pass

    def _gpu_sample(self) -> list[dict[str, Any]]:
        if not self._provider:
            return []
        samples = self._provider.sample_gpus()
        out = []
        for s in samples:
            self._seen_gpu_pids.update(s.compute_pids)
            out.append(
                {
                    "index": s.index,
                    "util_gpu_percent": s.util_gpu_percent,
                    "util_memory_percent": s.util_memory_percent,
                    "memory_used_bytes": s.memory_used_bytes,
                    "memory_total_bytes": s.memory_total_bytes,
                    "temperature_c": s.temperature_c,
                    "power_w": s.power_w,
                    "compute_pids": s.compute_pids,
                }
            )
        return out

    def _cpu_sample(self, util_percent: float) -> dict[str, Any]:
        sample: dict[str, Any] = {
            "util_percent": util_percent,
            "frequency_mhz": None,
            "temperature_c": None,
            "package_power_w": None,
            "package_energy_delta_j": None,
        }
        if not self._cpu_provider:
            return sample
        try:
            current = self._cpu_provider.sample_cpu()
        except Exception:
            return sample
        sample["frequency_mhz"] = current.frequency_mhz
        sample["temperature_c"] = current.temperature_c
        sample["package_power_w"] = current.package_power_w
        sample["package_energy_delta_j"] = current.package_energy_delta_j
        return sample

    def _sample(self) -> dict[str, Any]:
        vm = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_sample = self._cpu_sample(float(cpu_percent))
        gpu_samples = self._gpu_sample()

        component_power: list[float] = []
        coverage: list[str] = []
        cpu_power = cpu_sample.get("package_power_w")
        if cpu_power is not None:
            component_power.append(float(cpu_power))
            coverage.append("cpu_package")
        for gpu in gpu_samples:
            gpu_power = gpu.get("power_w")
            if gpu_power is not None:
                component_power.append(float(gpu_power))
                coverage.append(f"gpu:{gpu.get('index', 0)}")

        return {
            "ts": time.time(),
            # Keep the existing flat fields for backward compatibility.
            "cpu_percent": cpu_percent,
            "ram_used_bytes": vm.used,
            "ram_percent": vm.percent,
            "cpu": cpu_sample,
            "gpus": gpu_samples,
            "power": {
                "scope": "measured_components",
                "component_power_w": sum(component_power) if component_power else None,
                "wall_power_w": None,
                "coverage": coverage,
            },
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            self._refresh_own_pids()
            sample = self._sample()
            self._samples.append(sample)
            # Prevent unbounded memory growth during very long runs
            if len(self._samples) > self._max_samples:
                self._samples = self._samples[-self._max_samples:]
            self._stop.wait(self.interval)

    # ------------------------------------------------------------------- stop

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(2.0, self.interval * 3))
        if self._provider:
            self._provider.shutdown()
        if self._cpu_provider:
            self._cpu_provider.shutdown()
        return self.summary()

    def _foreign_processes(self) -> list[dict[str, Any]]:
        foreign = sorted(self._seen_gpu_pids - self._own_pids)
        out = []
        ignored_names = {
            "dwm.exe", "explorer.exe", "searchhost.exe", "startmenuexperiencehost.exe",
            "shellexperiencehost.exe", "shellhost.exe", "applicationframehost.exe",
            "systemsettings.exe", "msedge.exe", "msedgewebview2.exe", "taskmgr.exe",
            "windowsterminal.exe", "docker desktop.exe", "widgetboard.exe",
            "chrome.exe", "firefox.exe", "discord.exe", "slack.exe", "code.exe",
            "system", "system idle process", "registry", "csrss.exe", "winlogon.exe",
            "fontdrvhost.exe",
        }
        for pid in foreign:
            # PID 0/4 sind unter Windows Leerlauf- und Kernel-Prozess ("System");
            # nvidia-smi fuehrt sie als GPU-Nutzer, sie verfaelschen aber nichts.
            if pid in (0, 4):
                continue
            name = None
            with contextlib.suppress(Exception):
                name = psutil.Process(pid).name()
            if name and name.lower() in ignored_names:
                continue
            out.append({"pid": pid, "name": name})
        return out

    def summary(self) -> dict[str, Any]:
        if not self._samples:
            return {"sample_count": 0, "samples": [], "telemetry_source": "none"}

        cpu = [float(s["cpu_percent"]) for s in self._samples]
        ram = [int(s["ram_used_bytes"]) for s in self._samples]

        cpu_items = [s.get("cpu") or {} for s in self._samples]
        frequency_values = [
            float(item["frequency_mhz"])
            for item in cpu_items
            if item.get("frequency_mhz") is not None
        ]
        temperature_values = [
            float(item["temperature_c"])
            for item in cpu_items
            if item.get("temperature_c") is not None
        ]
        package_power_values = [
            float(item["package_power_w"])
            for item in cpu_items
            if item.get("package_power_w") is not None
        ]
        direct_cpu_energy = [
            float(item["package_energy_delta_j"])
            for item in cpu_items
            if item.get("package_energy_delta_j") is not None
            and float(item["package_energy_delta_j"]) >= 0
        ]
        integrated_cpu_energy, cpu_energy_seconds = _integrate_power(
            self._samples,
            lambda sample: (sample.get("cpu") or {}).get("package_power_w"),
        )
        if direct_cpu_energy:
            cpu_energy_j: float | None = sum(direct_cpu_energy)
            cpu_energy_source = "hardware_energy_counter"
        else:
            cpu_energy_j = integrated_cpu_energy
            cpu_energy_source = (
                "sampled_power_integration" if integrated_cpu_energy is not None else None
            )

        cpu_summary = {
            "avg_util_percent": statistics.fmean(cpu),
            "max_util_percent": max(cpu),
            "avg_frequency_mhz": (
                statistics.fmean(frequency_values) if frequency_values else None
            ),
            "min_frequency_mhz": min(frequency_values) if frequency_values else None,
            "max_frequency_mhz": max(frequency_values) if frequency_values else None,
            "avg_temperature_c": (
                statistics.fmean(temperature_values) if temperature_values else None
            ),
            "max_temperature_c": max(temperature_values) if temperature_values else None,
            "avg_package_power_w": (
                statistics.fmean(package_power_values) if package_power_values else None
            ),
            "max_package_power_w": max(package_power_values) if package_power_values else None,
            "energy_j": cpu_energy_j,
            "energy_wh": (cpu_energy_j / 3600.0) if cpu_energy_j is not None else None,
            "energy_source": cpu_energy_source,
            "energy_coverage_seconds": (
                cpu_energy_seconds if cpu_energy_source == "sampled_power_integration" else None
            ),
            "telemetry_source": getattr(
                self._cpu_provider, "TELEMETRY_SOURCE", "psutil"
            ),
        }

        gpu_count = max((len(s.get("gpus", [])) for s in self._samples), default=0)

        gpu_summaries = []
        for idx in range(gpu_count):
            items = [s["gpus"][idx] for s in self._samples if len(s.get("gpus", [])) > idx]
            avg_util, max_util = _agg(items, "util_gpu_percent")
            avg_mem, max_mem = _agg(items, "memory_used_bytes")
            avg_power, max_power = _agg(items, "power_w")
            _avg_temp, max_temp = _agg(items, "temperature_c")
            total_mem = next(
                (x.get("memory_total_bytes") for x in items if x.get("memory_total_bytes")), None
            )
            gpu_energy_j, gpu_energy_seconds = _integrate_power(
                self._samples,
                lambda sample, gpu_index=idx: (
                    sample.get("gpus", [])[gpu_index].get("power_w")
                    if len(sample.get("gpus", [])) > gpu_index
                    else None
                ),
            )
            gpu_summaries.append(
                {
                    "index": idx,
                    "avg_util_gpu_percent": avg_util,
                    "max_util_gpu_percent": max_util,
                    "avg_memory_used_bytes": avg_mem,
                    "max_memory_used_bytes": max_mem,
                    "memory_total_bytes": total_mem,
                    "avg_power_w": avg_power,
                    "max_power_w": max_power,
                    "max_temperature_c": max_temp,
                    "energy_j": gpu_energy_j,
                    "energy_wh": (
                        gpu_energy_j / 3600.0 if gpu_energy_j is not None else None
                    ),
                    "energy_source": (
                        "sampled_power_integration" if gpu_energy_j is not None else None
                    ),
                    "energy_coverage_seconds": gpu_energy_seconds,
                }
            )

        component_power_values = [
            float((sample.get("power") or {})["component_power_w"])
            for sample in self._samples
            if (sample.get("power") or {}).get("component_power_w") is not None
        ]
        power_coverage = sorted({
            component
            for sample in self._samples
            for component in ((sample.get("power") or {}).get("coverage") or [])
        })
        component_energies = [
            value
            for value in [
                cpu_summary.get("energy_j"),
                *(gpu.get("energy_j") for gpu in gpu_summaries),
            ]
            if value is not None
        ]
        component_energy_j = (
            sum(float(value) for value in component_energies)
            if component_energies
            else None
        )
        power_summary = {
            "scope": "measured_components",
            "coverage": power_coverage,
            "avg_component_power_w": (
                statistics.fmean(component_power_values)
                if component_power_values
                else None
            ),
            "max_component_power_w": (
                max(component_power_values) if component_power_values else None
            ),
            "component_energy_j": component_energy_j,
            "component_energy_wh": (
                component_energy_j / 3600.0
                if component_energy_j is not None
                else None
            ),
            # A real wall-power provider may populate these in a later phase.
            "wall_power_w": None,
            "wall_energy_j": None,
            "wall_energy_wh": None,
        }

        foreign = self._foreign_processes()
        warnings: list[str] = []
        if foreign:
            names = ", ".join(f"{p['name'] or '?'} (PID {p['pid']})" for p in foreign)
            warnings.append(
                _(
                    "Fremde Prozesse haben waehrend der Messung die GPU benutzt: "
                    "{names}. GPU-, VRAM- und Leistungswerte sind dadurch verfaelscht."
                ).format(names=names)
            )
        if self._baseline:
            base_gpu = self._baseline.get("gpus") or []
            busy = [g for g in base_gpu if (g.get("util_gpu_percent") or 0) > BUSY_BASELINE_UTIL_PERCENT]
            if busy:
                warnings.append(
                    _(
                        "Die GPU war bereits vor dem Testlauf ausgelastet ({percent} %), auch nach {seconds} s "
                        "Wartezeit. Der Server war nicht im Ruhezustand."
                    ).format(percent=f"{busy[0].get('util_gpu_percent'):.0f}", seconds=f"{self.idle_wait_seconds:.0f}")
                )

        return {
            "sample_count": len(self._samples),
            "telemetry_source": getattr(self._provider, "TELEMETRY_SOURCE", "cpu_only"),
            "avg_cpu_percent": statistics.fmean(cpu),
            "max_cpu_percent": max(cpu),
            "avg_ram_used_bytes": statistics.fmean(ram),
            "max_ram_used_bytes": max(ram),
            "cpu": cpu_summary,
            "cpu_telemetry_source": cpu_summary["telemetry_source"],
            "gpus": gpu_summaries,
            "power": power_summary,
            "sample_interval_seconds": self.interval,
            "baseline": self._baseline,
            "foreign_gpu_processes": foreign,
            "warnings": warnings,
            "samples": self._samples,
        }
