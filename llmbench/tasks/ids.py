"""Stable task and workload identifiers (see docs/architecture/workloads.md).

IDs are part of persisted results.  They must never be renamed; new tasks and
workloads are only ever added.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class TaskId(str, Enum):
    """What a model does functionally (not a model family or marketing name)."""

    TEXT_GENERATION = "text_generation"
    SPEECH_TO_TEXT = "speech_to_text"
    TEXT_TO_SPEECH = "text_to_speech"
    IMAGE_GENERATION = "image_generation"
    OCR = "ocr"
    EMBEDDING = "embedding"
    RERANKING = "reranking"
    COMPUTER_VISION = "computer_vision"
    THREE_D_GENERATION = "3d_generation"
    VIDEO_GENERATION = "video_generation"

    def __str__(self) -> str:
        return self.value


class UnknownTaskError(ValueError):
    """A task id is not part of the registry."""


class UnknownWorkloadError(ValueError):
    """A workload id is not part of the registry."""


WORKLOAD_ID_PATTERN = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


def parse_task_id(value: object) -> TaskId:
    """Return the ``TaskId`` for ``value`` or raise ``UnknownTaskError``."""
    if isinstance(value, TaskId):
        return value
    try:
        return TaskId(value)
    except ValueError:
        raise UnknownTaskError(f"Unknown task id: {value!r}") from None


@dataclass(frozen=True, slots=True)
class WorkloadSpec:
    """Description of one reproducible measurement situation within a task."""

    id: str
    task: TaskId
    description: str
    # Metric names are only comparable *within* one workload type; there is
    # deliberately no cross-workload score.
    metrics: tuple[str, ...] = ()
    implemented: bool = False


_T = TaskId
_SPECS: tuple[WorkloadSpec, ...] = (
    WorkloadSpec("text.prompt_processing", _T.TEXT_GENERATION, "Prompt processing (prefill) throughput", ("tokens_per_second",), True),
    WorkloadSpec("text.generation", _T.TEXT_GENERATION, "Token generation (decode) throughput", ("tokens_per_second",), True),
    WorkloadSpec("text.long_context", _T.TEXT_GENERATION, "Throughput at increasing context depth", ("tokens_per_second",), True),
    WorkloadSpec("text.endpoint_load", _T.TEXT_GENERATION, "Concurrent load against the HTTP endpoint", ("tokens_per_second", "ttft", "request_success_rate"), True),
    WorkloadSpec("text.soak", _T.TEXT_GENERATION, "Long-running stability / thermal soak", ("tokens_per_second",), True),
    WorkloadSpec("text.ttft_stress", _T.TEXT_GENERATION, "Time-to-first-token under concurrency", ("ttft",), True),
    WorkloadSpec("text.oom_probe", _T.TEXT_GENERATION, "Context / out-of-memory capacity probe", ("maximum_verified_context",), True),
    # Planned (not implemented): reserved so ids stay stable.
    WorkloadSpec("stt.short_audio", _T.SPEECH_TO_TEXT, "Short audio transcription", ("rtf", "wer", "cer")),
    WorkloadSpec("stt.long_audio", _T.SPEECH_TO_TEXT, "Long audio transcription", ("rtf", "wer", "cer")),
    WorkloadSpec("tts.short_text", _T.TEXT_TO_SPEECH, "Short text synthesis", ("time_to_first_audio", "rtf")),
    WorkloadSpec("ocr.scanned_pages", _T.OCR, "Scanned page recognition", ("pages_per_minute", "cer")),
    WorkloadSpec("image.txt2img", _T.IMAGE_GENERATION, "Text-to-image generation", ("seconds_per_image", "images_per_minute")),
    WorkloadSpec("embedding.batch", _T.EMBEDDING, "Batched embedding throughput", ("items_per_second",)),
)

WORKLOADS: dict[str, WorkloadSpec] = {spec.id: spec for spec in _SPECS}


def get_workload(workload_id: str) -> WorkloadSpec:
    try:
        return WORKLOADS[workload_id]
    except (KeyError, TypeError):
        raise UnknownWorkloadError(f"Unknown workload id: {workload_id!r}") from None


def workloads_for_task(task: TaskId | str) -> tuple[WorkloadSpec, ...]:
    task_id = parse_task_id(task)
    return tuple(spec for spec in _SPECS if spec.task is task_id)


def is_valid_workload_id_shape(value: object) -> bool:
    """Shape check only: a newer writer may use ids this version does not know."""
    return isinstance(value, str) and WORKLOAD_ID_PATTERN.fullmatch(value) is not None
