"""Optional runtime memory-bandwidth observers.

Observers never decide benchmark success.  This first adapter deliberately
supports only mactop's counter-backed Apple Silicon output; estimated M5+ data
is left unavailable instead of being promoted to a measured value.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from statistics import mean, median
from typing import Any

from .utils import utc_now_iso


# mactop v2 headless JSON serializes Go's untagged SocMetrics fields using
# their exported names.  This adapter intentionally accepts only the documented
# combined DRAM field below, rather than guessing from arbitrary JSON keys.
MACTOP_HEADLESS_PROTOCOL = "mactop-v2-headless-json"
_COMBINED_DRAM_KEY = "DRAMBWCombined"


def _unavailable(domain_id: str, reason: str) -> dict[str, Any]:
    return {
        "domain_id": domain_id,
        "method": "mactop", "scope": "system_soc_dram",
        "observed_during_benchmark": {
            "value": None, "source": None, "unit": "GB/s",
            "status": "unavailable", "reason": reason,
        },
    }


class MactopObserver:
    """Run mactop as a best-effort sidecar and retain its raw JSON artifact."""

    def __init__(self, run_dir: Path, *, enabled: bool, hardware: dict[str, Any], interval_ms: int = 1000) -> None:
        self.run_dir = run_dir
        self.enabled = enabled
        self.hardware = hardware
        self.interval_ms = interval_ms
        self.domain_id = "apple:unified:0"
        self.process: subprocess.Popen[str] | None = None
        self.output_path = run_dir / "mactop-dram.json"
        self.error_path = run_dir / "mactop-dram.stderr.log"
        self._output: Any = None
        self._error: Any = None
        self._started_at: str | None = None
        self.result: dict[str, Any] | None = None

    def start(self) -> None:
        if not self.enabled:
            return
        if sys.platform != "darwin" or not any(
            d.get("id") == self.domain_id for d in self.hardware.get("memory_domains") or []
        ):
            self.result = _unavailable(self.domain_id, "apple_silicon_not_detected")
            return
        domain = next(d for d in self.hardware["memory_domains"] if d.get("id") == self.domain_id)
        if str(domain.get("name") or "").startswith("Apple M5"):
            self.result = _unavailable(self.domain_id, "mactop_power_estimate_not_measured")
            return
        executable = shutil.which("mactop")
        if not executable:
            self.result = _unavailable(self.domain_id, "mactop_not_installed")
            return
        try:
            self._output = self.output_path.open("w", encoding="utf-8")
            self._error = self.error_path.open("w", encoding="utf-8")
            self.process = subprocess.Popen(
                [executable, "--headless", "--format", "json", "--interval", str(self.interval_ms)],
                stdout=self._output, stderr=self._error, text=True,
            )
            self._started_at = utc_now_iso()
        except OSError:
            self._close_files()
            self.result = _unavailable(self.domain_id, "mactop_start_failed")

    def stop(self) -> dict[str, Any] | None:
        if self.result is not None:
            return self.result
        if self.process is None:
            return None
        try:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        except OSError:
            pass
        finally:
            self._close_files()
        self.result = self._parse()
        return self.result

    def _close_files(self) -> None:
        for handle in (self._output, self._error):
            if handle is not None:
                handle.close()
        self._output = self._error = None

    def _parse(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _unavailable(self.domain_id, "mactop_invalid_or_incomplete_output")
        samples = payload if isinstance(payload, list) else [payload]
        values: list[float] = []
        for sample in samples:
            if not isinstance(sample, dict):
                continue
            metrics = sample.get("soc_metrics") or {}
            if not isinstance(metrics, dict):
                continue
            combined = metrics.get(_COMBINED_DRAM_KEY)
            if isinstance(combined, (int, float)) and not isinstance(combined, bool) and combined >= 0:
                values.append(float(combined))
        if not values:
            return _unavailable(self.domain_id, "mactop_counter_bandwidth_not_reported")
        digest = hashlib.sha256(self.output_path.read_bytes()).hexdigest()
        return {
            "domain_id": self.domain_id,
            "method": MACTOP_HEADLESS_PROTOCOL, "scope": "system_soc_dram",
            "tool_version": self._version(), "sampling_interval_ms": self.interval_ms,
            "window": {"started_at": self._started_at, "finished_at": utc_now_iso()},
            "observed_during_benchmark": {
                "value": median(values), "source": "measured", "unit": "GB/s",
                "evidence": {
                    "method": "benchmark_measurement", "provider": "mactop",
                    "protocol": MACTOP_HEADLESS_PROTOCOL,
                    "field": f"soc_metrics.{_COMBINED_DRAM_KEY}",
                },
            },
            "statistics": {"sample_count": len(values), "mean_gb_s": mean(values), "max_gb_s": max(values)},
            "artifact": {"path": self.output_path.name, "sha256": digest, "stderr_path": self.error_path.name},
        }

    def _version(self) -> str | None:
        executable = shutil.which("mactop")
        if not executable:
            return None
        try:
            output = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=5, check=False)
            return output.stdout.strip() or None
        except OSError:
            return None


def experimental_observer_status(vendor: str) -> dict[str, Any]:
    """Declare unimplemented vendor adapters without claiming profiler support."""
    return _unavailable(f"{vendor.lower()}:runtime", "adapter_not_implemented")
