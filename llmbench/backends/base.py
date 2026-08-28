from __future__ import annotations

import abc
from pathlib import Path
from typing import Any

class BenchmarkBackend(abc.ABC):
    """Abstract base class for LLM benchmark backends."""

    @abc.abstractmethod
    def run_benchmark(
        self,
        model_path: str,
        profile: dict[str, Any],
        kind: str,
        out_dir: Path,
        bench_cfg: dict[str, Any],
        on_progress=None
    ) -> dict[str, Any]:
        """Runs a specific benchmark test."""
        ...

    @abc.abstractmethod
    def start_server(
        self,
        model_path: str,
        profile: dict[str, Any],
        endpoint_cfg: dict[str, Any],
        bench_cfg: dict[str, Any],
        log_path: Path
    ) -> tuple[Any, str]:
        """Starts the server for endpoint testing."""
        ...

    @abc.abstractmethod
    def stop_server(self, proc: Any) -> None:
        """Stops the running server."""
        ...

    @abc.abstractmethod
    def wait_health(self, base_url: str, timeout_s: float, headers: dict[str, str] | None = None) -> float:
        """Waits for the server to become healthy."""
        ...
