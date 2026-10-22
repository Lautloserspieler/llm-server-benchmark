# Tasks and workloads

[🇩🇪 Deutsch](workloads.md) | [Overview](README.en.md)

## Task

A **task** describes what a model does at the application level.

Planned task IDs:

```text
text_generation
speech_to_text
text_to_speech
image_generation
ocr
embedding
reranking
computer_vision
3d_generation
video_generation
```

Task IDs are intended to be stable result identifiers and must not be used for marketing
names or model families.

## Workload

A **workload** describes a reproducible measurement situation within one task.

Current text examples:

```text
text.prompt_processing
text.generation
text.long_context
text.endpoint_load
text.soak
text.ttft_stress
text.oom_probe
```

Future examples:

```text
stt.short_audio
stt.long_audio
tts.short_text
ocr.scanned_pages
image.txt2img
embedding.batch
```

## Metric rule

Metrics are compared **within** a workload type. Unrelated units are never combined into a
single global score.

Examples:

- Text: tokens/s, TTFT, request success rate.
- STT: RTF, WER, CER.
- TTS: time-to-first-audio, RTF.
- Image: seconds/image, images/min.
- OCR: pages/min, CER.
- Vision: FPS, mAP/accuracy.

## Performance and quality

Where meaningful ground-truth metrics exist, a stable benchmark should record both:

1. **Performance** — how quickly/efficiently work is completed.
2. **Quality** — how correct the output is.

Faster output alone must not automatically be treated as better.

## Datasets

A workload must be able to identify its input data reproducibly. Future dataset manifests
should record at least source, version, license, hash, and sample selection. Publicly shared
benchmark profiles must not require confidential business data.

Implemented (groundwork) in `llmbench/tasks/dataset.py`: `DatasetManifest` is a validated,
immutable dataclass with `id`, `version`, `task`, `source`, `license`, `sha256`, and
`selection` (`all`, `first_n`, `ids`, `random_seeded`; randomness only with an explicit
seed). `workloads`, `files` (relative paths with their own SHA-256), and `confidential` are
optional. `load_dataset_manifest(path, verify_dir=...)` raises `DatasetManifestFormatError`
(format/JSON/field problems) and `DatasetHashMismatchError` (hash mismatch); both inherit
from `DatasetManifestError`.

## Registry

`llmbench/tasks/ids.py` contains `TaskId` (the ten IDs above) and a workload registry
(`WORKLOADS`) with the seven text workloads (implemented) plus reserved, not yet implemented
IDs (`stt.*`, `tts.*`, `ocr.*`, `image.*`, `embedding.*`). Metrics are listed per workload;
there is deliberately no universal score.
