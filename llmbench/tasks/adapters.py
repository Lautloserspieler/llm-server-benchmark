"""Task and runtime adapter contracts (groundwork, no multimodal runtime yet).

``TaskAdapter`` owns *what* is measured (workloads, metrics, datasets).
``RuntimeAdapter`` owns *how software runs a model* (lifecycle, capability
declaration).  Neither replaces ``BenchmarkBackend`` or ``run_suite``; the text
implementations only describe/wrap the existing path.
"""
from __future__ import annotations

import abc
from typing import Any

from .ids import TaskId, WorkloadSpec, parse_task_id, workloads_for_task


class TaskAdapter(abc.ABC):
    """Describes one task and maps legacy result structures onto workloads."""

    task_id: TaskId

    def workloads(self) -> tuple[WorkloadSpec, ...]:
        return workloads_for_task(self.task_id)

    def implemented_workloads(self) -> tuple[WorkloadSpec, ...]:
        return tuple(w for w in self.workloads() if w.implemented)

    @abc.abstractmethod
    def workload_for_kind(self, kind: str) -> str | None:
        """Map a legacy benchmark kind (e.g. ``generation``) to a workload id.

        Returns ``None`` for unknown kinds, never a guessed id.
        """

    def describe(self) -> dict[str, Any]:
        return {
            "task": self.task_id.value,
            "workloads": [
                {"id": w.id, "metrics": list(w.metrics), "implemented": w.implemented}
                for w in self.workloads()
            ],
        }


class RuntimeAdapter(abc.ABC):
    """Declares which tasks a runtime can execute."""

    runtime_id: str

    @abc.abstractmethod
    def supported_tasks(self) -> frozenset[TaskId]:
        """Tasks this runtime can execute."""

    def supports_task(self, task: TaskId | str) -> bool:
        return parse_task_id(task) in self.supported_tasks()


class BackendRuntimeAdapter(RuntimeAdapter):
    """Thin read-only view over an existing text ``BenchmarkBackend``.

    All lifecycle work stays in the backend; this only exposes identity and
    capabilities in the runtime-adapter vocabulary.
    """

    def __init__(self, backend: Any, runtime_id: str | None = None) -> None:
        self.backend = backend
        self.runtime_id = runtime_id or type(backend).__name__

    def supported_tasks(self) -> frozenset[TaskId]:
        return frozenset({TaskId.TEXT_GENERATION})

    def capabilities(self) -> dict[str, bool]:
        caps = getattr(self.backend, "capabilities", None)
        return caps.to_dict() if caps is not None else {}
