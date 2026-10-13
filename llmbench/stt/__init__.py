"""STT-Benchmark-Prototyp.

Experimentelles Nebenmodul, das Speech-to-Text-Engines (z. B. faster-whisper)
auf Transkriptionsqualitaet und Geschwindigkeit testet. Ist nicht Teil der
regulaeren LLM-Benchmark-Pipeline und wird nur aktiviert, wenn `stt.enabled`
in der Konfiguration auf `true` steht.
"""

from .config import STTConfig, STTEngineConfig, STTMetricConfig
from .dataset import STTSample, load_stt_dataset
from .metrics import compute_metrics, word_error_rate
from .runner import run_stt_benchmark

__all__ = [
    "STTConfig",
    "STTEngineConfig",
    "STTMetricConfig",
    "STTSample",
    "load_stt_dataset",
    "compute_metrics",
    "word_error_rate",
    "run_stt_benchmark",
]
