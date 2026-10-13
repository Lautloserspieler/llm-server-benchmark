"""STT-Datensatz-Lader.

Unterstuetzt JSONL-Dateien mit Eintraegen der Form
    {"audio_path": "...", "reference": "..."}
und CSV-Dateien mit den Spalten `audio_path` und `reference`. Relative Pfade
werden gegen das Verzeichnis der Datensatzdatei aufgeloest.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class STTSample:
    audio_path: Path
    reference: str
    id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "audio_path": str(self.audio_path),
            "reference": self.reference,
        }


def _resolve_path(path: str, base_dir: Path) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return base_dir / p


def _load_jsonl(path: Path) -> list[STTSample]:
    samples: list[STTSample] = []
    base_dir = path.parent
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            audio = _resolve_path(obj["audio_path"], base_dir)
            samples.append(
                STTSample(
                    audio_path=audio,
                    reference=str(obj.get("reference", "")).strip(),
                    id=str(obj.get("id", f"{path.stem}-{i}")),
                )
            )
    return samples


def _load_csv(path: Path) -> list[STTSample]:
    samples: list[STTSample] = []
    base_dir = path.parent
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=1):
            audio = _resolve_path(row["audio_path"], base_dir)
            samples.append(
                STTSample(
                    audio_path=audio,
                    reference=str(row.get("reference", "")).strip(),
                    id=str(row.get("id", f"{path.stem}-{i}")),
                )
            )
    return samples


def load_stt_dataset(path: str | Path, max_samples: int | None = None) -> list[STTSample]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"STT-Datensatz nicht gefunden: {p}")

    suffix = p.suffix.lower()
    if suffix == ".jsonl":
        samples = _load_jsonl(p)
    elif suffix == ".csv":
        samples = _load_csv(p)
    else:
        raise ValueError(f"Nicht unterstuetztes Format: {suffix} (nur .jsonl/.csv)")

    if max_samples is not None:
        samples = samples[:max_samples]
    return samples
