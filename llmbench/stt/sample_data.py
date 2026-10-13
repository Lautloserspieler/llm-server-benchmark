"""Erzeugt einen minimalen Beispieldatensatz fuer den STT-Prototypen.

Da echte Audiodateien gross sind, werden hier nur die Metadaten-Dateien
(JSONL + CSV) geschrieben. Der Nutzer kann die zugehoerigen Audio-Dateien
eigenstaendig unter `audio/` ablegen oder das Verzeichnis als Vorlage fuer
einen echten Datensatz nutzen.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from ..utils import ensure_dir


SAMPLES = [
    {
        "id": "sample_001",
        "audio_path": "audio/sample_001.wav",
        "reference": "Das ist ein kurzer Beispielsatz fuer die Spracherkennung.",
    },
    {
        "id": "sample_002",
        "audio_path": "audio/sample_002.wav",
        "reference": "Lokale Spracherkennung sollte reproduzierbar und messbar sein.",
    },
    {
        "id": "sample_003",
        "audio_path": "audio/sample_003.wav",
        "reference": "Wir testen die Engine auf Wortfehlerrate und Geschwindigkeit.",
    },
]


def _write_jsonl(path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        for sample in SAMPLES:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")


def _write_csv(path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "audio_path", "reference"])
        writer.writeheader()
        for sample in SAMPLES:
            writer.writerow(sample)


def write_sample_dataset(base_dir: str | Path) -> Path:
    base = Path(base_dir)
    ensure_dir(base)
    ensure_dir(base / "audio")
    _write_jsonl(base / "samples.jsonl")
    _write_csv(base / "samples.csv")
    return base
