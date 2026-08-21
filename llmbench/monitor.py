from __future__ import annotations

import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import psutil


@dataclass
class ResourceMonitor:
    interval: float = 0.5
    _samples: list[dict[str, Any]] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    _nvml: Any = None
    _handles: list[Any] = field(default_factory=list)

    def start(self) -> None:
        self._samples = []
        self._stop.clear()
        psutil.cpu_percent(interval=None)
        try:
            import pynvml
            pynvml.nvmlInit()
            self._nvml = pynvml
            self._handles = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(pynvml.nvmlDeviceGetCount())]
        except Exception:
            self._nvml = None
            self._handles = []
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _gpu_sample(self) -> list[dict[str, Any]]:
        if not self._nvml:
            return []
        out = []
        for idx, h in enumerate(self._handles):
            try:
                mem = self._nvml.nvmlDeviceGetMemoryInfo(h)
                util = self._nvml.nvmlDeviceGetUtilizationRates(h)
                temp = self._nvml.nvmlDeviceGetTemperature(h, self._nvml.NVML_TEMPERATURE_GPU)
                try:
                    power_w = self._nvml.nvmlDeviceGetPowerUsage(h) / 1000.0
                except Exception:
                    power_w = None
                out.append({"index": idx, "util_gpu_percent": float(util.gpu), "util_memory_percent": float(util.memory), "memory_used_bytes": int(mem.used), "memory_total_bytes": int(mem.total), "temperature_c": float(temp), "power_w": power_w})
            except Exception:
                continue
        return out

    def _run(self) -> None:
        while not self._stop.is_set():
            vm = psutil.virtual_memory()
            self._samples.append({"ts": time.time(), "cpu_percent": psutil.cpu_percent(interval=None), "ram_used_bytes": vm.used, "ram_percent": vm.percent, "gpus": self._gpu_sample()})
            self._stop.wait(self.interval)

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(2.0, self.interval * 3))
        if self._nvml:
            try:
                self._nvml.nvmlShutdown()
            except Exception:
                pass
        return self.summary()

    def summary(self) -> dict[str, Any]:
        if not self._samples:
            return {"sample_count": 0, "samples": []}
        cpu = [float(s["cpu_percent"]) for s in self._samples]
        ram = [int(s["ram_used_bytes"]) for s in self._samples]
        gpu_count = max((len(s.get("gpus", [])) for s in self._samples), default=0)
        gpu_summaries = []
        for idx in range(gpu_count):
            items = [s["gpus"][idx] for s in self._samples if len(s.get("gpus", [])) > idx]
            def vals(k: str) -> list[float]:
                return [float(x[k]) for x in items if x.get(k) is not None]
            gpu_summaries.append({"index": idx, "avg_util_gpu_percent": statistics.fmean(vals("util_gpu_percent")) if vals("util_gpu_percent") else None, "max_util_gpu_percent": max(vals("util_gpu_percent")) if vals("util_gpu_percent") else None, "avg_memory_used_bytes": statistics.fmean(vals("memory_used_bytes")) if vals("memory_used_bytes") else None, "max_memory_used_bytes": max(vals("memory_used_bytes")) if vals("memory_used_bytes") else None, "avg_power_w": statistics.fmean(vals("power_w")) if vals("power_w") else None, "max_power_w": max(vals("power_w")) if vals("power_w") else None, "max_temperature_c": max(vals("temperature_c")) if vals("temperature_c") else None})
        return {"sample_count": len(self._samples), "avg_cpu_percent": statistics.fmean(cpu), "max_cpu_percent": max(cpu), "avg_ram_used_bytes": statistics.fmean(ram), "max_ram_used_bytes": max(ram), "gpus": gpu_summaries, "samples": self._samples}
