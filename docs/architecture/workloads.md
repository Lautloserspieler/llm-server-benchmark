# Tasks und Workloads

[🇬🇧 English](workloads.en.md) | [Übersicht](README.md)

## Task

Eine **Task** beschreibt, was ein Modell fachlich tut.

Vorgesehene Task-IDs:

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

Task-IDs sind stabiler Bestandteil von zukünftigen Resultaten und dürfen nicht für
Marketing-/Modellfamilien verwendet werden.

## Workload

Ein **Workload** beschreibt eine reproduzierbare Messsituation innerhalb einer Task.

Aktuelle Textbeispiele:

```text
text.prompt_processing
text.generation
text.long_context
text.endpoint_load
text.soak
text.ttft_stress
text.oom_probe
```

Zukünftige Beispiele:

```text
stt.short_audio
stt.long_audio
tts.short_text
ocr.scanned_pages
image.txt2img
embedding.batch
```

## Metric-Regel

Metriken werden **innerhalb** eines Workload-Typs verglichen. Nicht vergleichbare
Maßeinheiten werden nicht zu einem gemeinsamen Gesamtscore verrechnet.

Beispiele:

- Text: Tokens/s, TTFT, Request-Erfolgsrate.
- STT: RTF, WER, CER.
- TTS: Time-to-first-audio, RTF.
- Image: Sekunden/Bild, Bilder/min.
- OCR: Seiten/min, CER.
- Vision: FPS, mAP/Accuracy.

## Performance und Qualität

Wo eine Task sinnvolle Ground-Truth-Metriken besitzt, soll ein stabiler Benchmark beide
Dimensionen speichern:

1. **Performance** — wie schnell/effizient die Arbeit ausgeführt wird.
2. **Qualität** — wie korrekt das Ergebnis ist.

Schnellere Ausgabe allein darf nicht automatisch als besser gelten.

## Datasets

Ein Workload muss seine Eingabedaten reproduzierbar identifizieren können. Zukünftige
Dataset-Manifeste sollen mindestens Quelle, Version, Lizenz, Hash und Sample-Auswahl
festhalten. Öffentlich geteilte Benchmarkprofile dürfen keine vertraulichen
Unternehmensdaten voraussetzen.

Umgesetzt (Groundwork) in `llmbench/tasks/dataset.py`: `DatasetManifest` ist eine
validierte, unveränderliche Dataclass mit `id`, `version`, `task`, `source`, `license`,
`sha256` und `selection` (`all`, `first_n`, `ids`, `random_seeded`; Zufall nur mit
explizitem Seed). Optional sind `workloads`, `files` (relative Pfade mit eigenem SHA-256)
und `confidential`. `load_dataset_manifest(path, verify_dir=...)` liefert die Fehlerklassen
`DatasetManifestFormatError` (Format/JSON/Feld) und `DatasetHashMismatchError`
(Hash-Abweichung); beide erben von `DatasetManifestError`.

## Registry

`llmbench/tasks/ids.py` enthält `TaskId` (die zehn oben genannten IDs) und eine
Workload-Registry (`WORKLOADS`) mit den sieben Text-Workloads (implementiert) sowie
reservierten, noch nicht implementierten IDs (`stt.*`, `tts.*`, `ocr.*`, `image.*`,
`embedding.*`). Metriken sind pro Workload aufgeführt; es gibt bewusst keinen universellen
Score.
