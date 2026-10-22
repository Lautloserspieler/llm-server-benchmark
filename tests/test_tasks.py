import copy

import pytest

from llmbench.backends.base import BenchmarkBackend
from llmbench.backends.capabilities import BackendCapabilities
from llmbench.runner import BENCH_KINDS
from llmbench.tasks import (
    KIND_TO_WORKLOAD,
    WORKLOADS,
    BackendRuntimeAdapter,
    RuntimeAdapter,
    TaskAdapter,
    TaskId,
    TextGenerationTask,
    UnknownTaskError,
    UnknownWorkloadError,
    get_workload,
    infer_task_view,
    is_valid_workload_id_shape,
    parse_task_id,
    workloads_for_task,
)

DOC_TASKS = [
    "text_generation", "speech_to_text", "text_to_speech", "image_generation", "ocr",
    "embedding", "reranking", "computer_vision", "3d_generation", "video_generation",
]
DOC_TEXT_WORKLOADS = [
    "text.prompt_processing", "text.generation", "text.long_context", "text.endpoint_load",
    "text.soak", "text.ttft_stress", "text.oom_probe",
]


def test_task_ids_match_architecture_doc():
    assert [t.value for t in TaskId] == DOC_TASKS
    assert str(TaskId.OCR) == "ocr"


def test_parse_task_id():
    assert parse_task_id("ocr") is TaskId.OCR
    assert parse_task_id(TaskId.OCR) is TaskId.OCR
    with pytest.raises(UnknownTaskError):
        parse_task_id("whisper")


def test_workload_registry_contains_text_workloads_implemented():
    for wid in DOC_TEXT_WORKLOADS:
        spec = get_workload(wid)
        assert spec.task is TaskId.TEXT_GENERATION and spec.implemented
    assert [w.id for w in workloads_for_task("text_generation")] == DOC_TEXT_WORKLOADS
    assert not get_workload("stt.short_audio").implemented
    with pytest.raises(UnknownWorkloadError):
        get_workload("text.nope")


def test_workload_ids_are_well_formed_and_prefixed_consistently():
    for wid in WORKLOADS:
        assert is_valid_workload_id_shape(wid)
    assert not is_valid_workload_id_shape("text")
    assert not is_valid_workload_id_shape(3)


def test_no_universal_score_metric_in_registry():
    for spec in WORKLOADS.values():
        assert "score" not in " ".join(spec.metrics)


def test_text_task_covers_every_runner_kind():
    adapter = TextGenerationTask()
    for kind in BENCH_KINDS:
        wid = adapter.workload_for_kind(kind)
        assert wid in WORKLOADS and wid in KIND_TO_WORKLOAD.values()
    assert adapter.workload_for_kind("mystery") is None
    desc = adapter.describe()
    assert desc["task"] == "text_generation" and len(desc["workloads"]) == 7
    assert len(adapter.implemented_workloads()) == 7


def test_abstract_adapters_cannot_be_instantiated():
    with pytest.raises(TypeError):
        TaskAdapter()  # type: ignore[abstract]
    with pytest.raises(TypeError):
        RuntimeAdapter()  # type: ignore[abstract]


def test_backend_runtime_adapter_wraps_without_touching_backend():
    class Dummy(BenchmarkBackend):
        capabilities = BackendCapabilities(endpoint=True, streaming=True)

        def run_benchmark(self, *a, **k): ...
        def start_server(self, *a, **k): ...
        def stop_server(self, proc): ...
        def wait_health(self, *a, **k): ...

    backend = Dummy()
    adapter = BackendRuntimeAdapter(backend, "dummy")
    assert adapter.runtime_id == "dummy"
    assert adapter.supports_task("text_generation")
    assert not adapter.supports_task(TaskId.SPEECH_TO_TEXT)
    assert adapter.capabilities()["endpoint"] is True
    assert adapter.capabilities()["oom_probe"] is False


def test_infer_task_view_for_legacy_summary_does_not_mutate():
    legacy = {"schema_version": 3, "models": [{"profiles": [{"benchmarks": {"generation": {}, "weird": {}}}]}]}
    before = copy.deepcopy(legacy)
    view = infer_task_view(legacy)
    assert legacy == before
    assert view["task"] == "text_generation" and view["task_inferred"] is True
    assert view["workloads"] == {"generation": "text.generation", "weird": None}


def test_infer_task_view_prefers_recorded_values():
    s = {"task": "ocr", "models": [{"profiles": [{"benchmarks": {"generation": {"workload": "ocr.scanned_pages"}}}]}]}
    view = infer_task_view(s)
    assert view["task"] == "ocr" and view["task_inferred"] is False
    assert view["workloads"]["generation"] == "ocr.scanned_pages"


def test_infer_task_view_ignores_non_dict_entries():
    summary = {
        "models": [
            "junk", None, 3,
            {"profiles": ["x", None, {"benchmarks": {"generation": {}, "bad": "str", "n": None}}]},
        ]
    }
    view = infer_task_view(summary)
    assert view["workloads"]["generation"] == "text.generation"
    assert view["workloads"]["bad"] is None
