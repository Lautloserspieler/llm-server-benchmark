"""TextGeneration task adapter: a thin description of the existing text path.

It does not run anything; ``llmbench.runner.run_suite`` stays the executor.
"""
from __future__ import annotations

from typing import Any

from .adapters import TaskAdapter
from .ids import TaskId

# Legacy ``BENCH_KINDS`` in runner.py plus the other result sections.
KIND_TO_WORKLOAD: dict[str, str] = {
    "prompt": "text.prompt_processing",
    "generation": "text.generation",
    "long_context": "text.long_context",
    "endpoint": "text.endpoint_load",
    "soak": "text.soak",
    "ttft": "text.ttft_stress",
    "ttft_stress": "text.ttft_stress",
    "oom": "text.oom_probe",
    "oom_probe": "text.oom_probe",
}


class TextGenerationTask(TaskAdapter):
    task_id = TaskId.TEXT_GENERATION

    def workload_for_kind(self, kind: str) -> str | None:
        return KIND_TO_WORKLOAD.get(kind)


def infer_task_view(summary: dict[str, Any]) -> dict[str, Any]:
    """Return task/workload info for any summary, old or new.

    Explicit fields win.  Results without them (all pre-groundwork v1-v3
    files) are text results; the task is then reported as *inferred* so
    consumers can tell it from a recorded value.  Nothing is written back.
    """
    adapter = TextGenerationTask()
    explicit = summary.get("task")
    task = explicit if explicit is not None else TaskId.TEXT_GENERATION.value
    workloads: dict[str, str | None] = {}
    for model in summary.get("models") or []:
        for profile in model.get("profiles") or []:
            for kind, bench in (profile.get("benchmarks") or {}).items():
                recorded = bench.get("workload") if isinstance(bench, dict) else None
                workloads.setdefault(kind, recorded or adapter.workload_for_kind(kind))
    return {"task": task, "task_inferred": explicit is None, "workloads": workloads}
