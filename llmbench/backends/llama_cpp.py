from __future__ import annotations

import subprocess
import asyncio
from pathlib import Path
from typing import Any, Optional, Dict

from .base import BenchmarkBackend
from ..endpoint import (
    start_llama_server,
    stop_llama_server,
    wait_health
)
from ..llama_bench import run_llama_bench

class LlamaCppBackend(BenchmarkBackend):
    """Implementation of the benchmark backend for llama.cpp."""

    def __init__(self, llama_bench_exe: str, llama_server_exe: str):
        self.llama_bench_exe = llama_bench_exe
        self.llama_server_exe = llama_server_exe

    def run_benchmark(
        self,
        model_path: str,
        profile: Dict[str, Any],
        kind: str,
        out_dir: Path,
        bench_cfg: Dict[str, Any],
        on_progress=None
    ) -> Dict[str, Any]:
        return run_llama_bench(
            self.llama_bench_exe,
            model_path,
            bench_cfg,
            profile,
            kind,
            out_dir,
            on_progress=on_progress,
        )

    def start_server(
        self,
        model_path: str,
        profile: Dict[str, Any],
        endpoint_cfg: Dict[str, Any],
        bench_cfg: Dict[str, Any],
        log_path: Path
    ) -> tuple[Any, str]:
        return start_llama_server(
            self.llama_server_exe,
            model_path,
            profile,
            endpoint_cfg,
            bench_cfg,
            log_path,
        )

    def stop_server(self, proc: Any) -> None:
        stop_llama_server(proc)

    def wait_health(self, base_url: str, timeout_s: float, headers: Optional[Dict[str, str]] = None) -> float:
        return wait_health(base_url, timeout_s, headers)
