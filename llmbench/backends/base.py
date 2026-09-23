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
    def wait_health(
        self, base_url: str, timeout_s: float, headers: dict[str, str] | None = None, proc: Any = None
    ) -> float:
        """Waits for the server to become healthy.

        ``proc`` is the handle returned by ``start_server``; backends that can
        detect a server that already exited should fail fast with its reason.
        """
        ...

    # ------------------------------------------------------------- Lifecycle
    # Optional hooks, deliberately concrete and no-op by default.
    #
    # llama.cpp needs nothing here: ``run_benchmark`` shells out to the
    # ``llama-bench`` binary, which starts and stops its own process per call.
    # HTTP-only backends (vLLM, later Ollama/TGI) have no such tool - they must
    # bring up a server and measure against it. Starting that server once per
    # profile instead of once per benchmark kind saves two slow startups per
    # profile, which is why these hooks wrap the whole kind loop rather than a
    # single ``run_benchmark`` call.
    #
    # Making them abstract would force every existing backend to grow two empty
    # methods, so they stay optional.

    # B027 flags empty non-abstract methods on an ABC. Here that is the point:
    # these hooks must stay optional so that LlamaCppBackend keeps working
    # unchanged, without two empty overrides it does not need.
    def begin_profile(  # noqa: B027
        self,
        model_path: str,  # noqa: ARG002 - part of the hook contract, unused by default
        profile: dict[str, Any],  # noqa: ARG002 - part of the hook contract, unused by default
        bench_cfg: dict[str, Any],  # noqa: ARG002 - part of the hook contract, unused by default
        out_dir: Path,  # noqa: ARG002 - part of the hook contract, unused by default
    ) -> None:
        """Called once before all benchmark kinds of a profile. No-op by default."""

    def end_profile(self) -> None:  # noqa: B027
        """Called once after all benchmark kinds of a profile. No-op by default."""
