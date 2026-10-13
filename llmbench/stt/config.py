"""STT-Konfiguration (Pydantic-Modelle).

Diese Klassen sind als experimentelles Nebenmodul gedacht und spiegeln die
in llmbench.config definierten STT-Konfigurationsfelder wider. Sie koennen
spaeter aus llmbench.config importiert werden, sobald das Modul stabil ist.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class STTMetricConfig(BaseModel):
    name: str = "wer"
    params: dict[str, Any] = Field(default_factory=dict)


class STTEngineConfig(BaseModel):
    name: str
    model: str | None = None
    device: str = "auto"
    compute_type: str = "default"
    language: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class STTConfig(BaseModel):
    enabled: bool = False
    dataset_path: str | None = None
    max_samples: int | None = None
    engines: list[STTEngineConfig] = Field(
        default_factory=lambda: [
            STTEngineConfig(name="faster-whisper", model="base", compute_type="int8")
        ]
    )
    metrics: list[STTMetricConfig] = Field(
        default_factory=lambda: [STTMetricConfig(name="wer")]
    )
    output_dir: str = "stt_results"
