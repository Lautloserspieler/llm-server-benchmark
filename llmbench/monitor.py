from __future__ import annotations

import contextlib
import os
import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import psutil


def _agg(items: list[dict[str, Any]], key: str) -> tuple[float | None, float | None]:
    """Mittelwert und Maximum einer Kennzahl. Einmal berechnen statt dreimal."""
    values = [float(x[key]) for x in items if x.get(key) is not None]
    if not values:
        return None, None
    return statistics.fmean(values), max(values)


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
    _nvml: Any = None
    _handles: list[Any] = field(default_factory=list)
    _target_pid: int | None = None
    _own_pids: set[int] = field(default_factory=set)
    _seen_gpu_pids: set[int] = field(default_factory=set)
    _baseline: dict[str, Any] | None = None

    # ------------------------------------------------------------------ start

    def start(self) -> None:
        self._samples = []
        self._seen_gpu_pids = set()
        self._own_pids = {os.getpid()}
        self._stop.clear()
        psutil.cpu_percent(interval=None)
        try:
            import pynvml

            pynvml.nvmlInit()
            self._nvml = pynvml
            self._handles = [
                pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(pynvml.nvmlDeviceGetCount())
            ]
        except Exception:
            self._nvml = None
            self._handles = []
        # Ruhewert vor der Last: macht sichtbar, ob die Maschine sauber war.
        self._baseline = self._sample()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

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
        self._target_pid = pid
        if pid:
            self._own_pids.add(pid)

    # ----------------------------------------------------------------- sampling

    def _refresh_own_pids(self) -> None:
        if not self._target_pid:
            return
        try:
            proc = psutil.Process(self._target_pid)
            self._own_pids.update(child.pid for child in proc.children(recursive=True))
        except Exception:
            pass

    def _gpu_sample(self) -> list[dict[str, Any]]:
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
                self._seen_gpu_pids.update(pids)
                out.append(
                    {
                        "index": idx,
                        "util_gpu_percent": float(util.gpu),
                        "util_memory_percent": float(util.memory),
                        "memory_used_bytes": int(mem.used),
                        "memory_total_bytes": int(mem.total),
                        "temperature_c": float(temp),
                        "power_w": power_w,
                        "compute_pids": pids,
                    }
                )
            except Exception:
                continue
        return out

    def _sample(self) -> dict[str, Any]:
        vm = psutil.virtual_memory()
        return {
            "ts": time.time(),
            "cpu_percent": psutil.cpu_percent(interval=None),
            "ram_used_bytes": vm.used,
            "ram_percent": vm.percent,
            "gpus": self._gpu_sample(),
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            self._refresh_own_pids()
            self._samples.append(self._sample())
            self._stop.wait(self.interval)

    # ------------------------------------------------------------------- stop

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(2.0, self.interval * 3))
        if self._nvml:
            with contextlib.suppress(Exception):
                self._nvml.nvmlShutdown()
        return self.summary()

    def _foreign_processes(self) -> list[dict[str, Any]]:
        foreign = sorted(self._seen_gpu_pids - self._own_pids)
        out = []
        for pid in foreign:
            name = None
            with contextlib.suppress(Exception):
                name = psutil.Process(pid).name()
            out.append({"pid": pid, "name": name})
        return out

    def summary(self) -> dict[str, Any]:
        if not self._samples:
            return {"sample_count": 0, "samples": [], "telemetry_source": "none"}

        cpu = [float(s["cpu_percent"]) for s in self._samples]
        ram = [int(s["ram_used_bytes"]) for s in self._samples]
        gpu_count = max((len(s.get("gpus", [])) for s in self._samples), default=0)

        gpu_summaries = []
        for idx in range(gpu_count):
            items = [s["gpus"][idx] for s in self._samples if len(s.get("gpus", [])) > idx]
            avg_util, max_util = _agg(items, "util_gpu_percent")
            avg_mem, max_mem = _agg(items, "memory_used_bytes")
            avg_power, max_power = _agg(items, "power_w")
            _, max_temp = _agg(items, "temperature_c")
            total_mem = next(
                (x.get("memory_total_bytes") for x in items if x.get("memory_total_bytes")), None
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
                }
            )

        foreign = self._foreign_processes()
        warnings: list[str] = []
        if foreign:
            names = ", ".join(f"{p['name'] or '?'} (PID {p['pid']})" for p in foreign)
            warnings.append(
                "Fremde Prozesse haben waehrend der Messung die GPU benutzt: "
                f"{names}. GPU-, VRAM- und Leistungswerte sind dadurch verfaelscht."
            )
        if self._baseline:
            base_gpu = self._baseline.get("gpus") or []
            busy = [g for g in base_gpu if (g.get("util_gpu_percent") or 0) > 15]
            if busy:
                warnings.append(
                    "Die GPU war bereits vor dem Testlauf ausgelastet "
                    f"({busy[0].get('util_gpu_percent'):.0f} %). Der Server war nicht im Ruhezustand."
                )

        return {
            "sample_count": len(self._samples),
            "telemetry_source": "nvml" if self._nvml else "cpu_only",
            "avg_cpu_percent": statistics.fmean(cpu),
            "max_cpu_percent": max(cpu),
            "avg_ram_used_bytes": statistics.fmean(ram),
            "max_ram_used_bytes": max(ram),
            "gpus": gpu_summaries,
            "baseline": self._baseline,
            "foreign_gpu_processes": foreign,
            "warnings": warnings,
            "samples": self._samples,
        }
