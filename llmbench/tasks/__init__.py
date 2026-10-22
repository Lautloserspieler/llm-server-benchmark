"""Task/workload groundwork for multimodal benchmarking (additive, text path unchanged)."""
from .adapters import BackendRuntimeAdapter, RuntimeAdapter, TaskAdapter
from .dataset import (
    DatasetHashMismatchError,
    DatasetManifest,
    DatasetManifestError,
    DatasetManifestFormatError,
    SampleSelection,
    load_dataset_manifest,
    verify_file_sha256,
)
from .ids import (
    WORKLOADS,
    TaskId,
    UnknownTaskError,
    UnknownWorkloadError,
    WorkloadSpec,
    get_workload,
    is_valid_workload_id_shape,
    parse_task_id,
    workloads_for_task,
)
from .text import KIND_TO_WORKLOAD, TextGenerationTask, infer_task_view

__all__ = [
    "BackendRuntimeAdapter", "DatasetHashMismatchError", "DatasetManifest", "DatasetManifestError",
    "DatasetManifestFormatError", "KIND_TO_WORKLOAD", "RuntimeAdapter", "SampleSelection", "TaskAdapter",
    "TaskId", "TextGenerationTask", "UnknownTaskError", "UnknownWorkloadError", "WORKLOADS", "WorkloadSpec",
    "get_workload", "infer_task_view", "is_valid_workload_id_shape", "load_dataset_manifest", "parse_task_id",
    "verify_file_sha256", "workloads_for_task",
]
