"""STT-Engine-Backends.

Bietet eine einheitliche Schnittstelle fuer STT-Engines. Der einzige momentan
implementierte konkrete Backend ist `faster-whisper`; weitere Engines koennen
ueber eine neue `_Engine` aus `BaseEngine` abgeleitet werden.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .config import STTEngineConfig


class BaseEngine(ABC):
    """Abstrakte Basisklasse fuer eine STT-Engine."""

    name: str

    @abstractmethod
    def transcribe(self, audio_path: Path) -> tuple[str, float]:
        """Gibt (transkribierter Text, Dauer in Sekunden) zurueck."""

    @abstractmethod
    def info(self) -> dict[str, Any]:
        """Gibt nicht-sensitive Engine-Metadaten zurueck."""


class FasterWhisperEngine(BaseEngine):
    """faster-whisper Backend (lazy import, damit die Abhaengigkeit optional ist)."""

    name = "faster-whisper"

    def __init__(self, cfg: STTEngineConfig):
        try:
            from faster_whisper import WhisperModel  # type: ignore[import-untyped]
        except Exception as exc:
            raise RuntimeError(
                "faster-whisper ist nicht installiert. "
                "Installiere es mit: pip install faster-whisper"
            ) from exc
        model = cfg.model or "base"
        device = cfg.device
        compute_type = cfg.compute_type
        self._language = cfg.language
        self._extra = cfg.extra
        self._model = WhisperModel(model, device=device, compute_type=compute_type)
        self._model_name = model
        self._device = device
        self._compute_type = compute_type

    def transcribe(self, audio_path: Path) -> tuple[str, float]:
        started = time.perf_counter()
        segments, _info = self._model.transcribe(
            str(audio_path),
            language=self._language,
            **self._extra,
        )
        text = " ".join(segment.text.strip() for segment in segments)
        duration = time.perf_counter() - started
        return text, duration

    def info(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "model": self._model_name,
            "device": self._device,
            "compute_type": self._compute_type,
            "language": self._language,
        }


class FakeEngine(BaseEngine):
    """In-Memory-Testdouble fuer Unit-Tests."""

    name = "fake"

    def __init__(self, cfg: STTEngineConfig):
        self._cfg = cfg
        self._latency = float(cfg.extra.get("latency_seconds", 0.0))
        self._results: dict[str, str] = cfg.extra.get("results", {})

    def transcribe(self, audio_path: Path) -> tuple[str, float]:
        started = time.perf_counter()
        if self._latency:
            time.sleep(self._latency)
        text = self._results.get(str(audio_path), "")
        return text, time.perf_counter() - started

    def info(self) -> dict[str, Any]:
        return {"name": self.name, "model": self._cfg.model, "latency": self._latency}


def build_engine(cfg: STTEngineConfig) -> BaseEngine:
    if cfg.name == "faster-whisper":
        return FasterWhisperEngine(cfg)
    if cfg.name == "fake":
        return FakeEngine(cfg)
    raise ValueError(f"Unbekannte STT-Engine: {cfg.name!r}")
