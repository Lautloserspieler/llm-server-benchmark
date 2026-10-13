"""Unit tests fuer den STT-Prototypen.

Testet die Konfiguration, Datensatz-Lader, Metriken, Fake-Backend und den
Runner ohne externe Abhaengigkeiten (insbesondere ohne faster-whisper).
"""
from __future__ import annotations

import json

import pytest

from llmbench.stt import (
    STTConfig,
    STTEngineConfig,
    compute_metrics,
    load_stt_dataset,
    run_stt_benchmark,
    word_error_rate,
)
from llmbench.stt.runner import _aggregate
from llmbench.stt.sample_data import SAMPLES, write_sample_dataset


def test_word_error_rate_perfect_match():
    assert word_error_rate("hallo welt", "hallo welt") == 0.0


def test_word_error_rate_one_substitution():
    assert word_error_rate("hallo welt", "hallo welt") == 0.0
    assert word_error_rate("hallo welt", "hallo walt") == pytest.approx(1 / 2)


def test_word_error_rate_empty_reference():
    assert word_error_rate("", "") == 0.0
    assert word_error_rate("", "hallo") == 1.0


def test_char_error_rate_matches_string_distance():
    from llmbench.stt.metrics import char_error_rate
    assert char_error_rate("hallo", "hallo") == 0.0
    assert char_error_rate("hallo", "halo") == pytest.approx(1 / 5)


def test_compute_metrics_selects_requested_metrics():
    assert compute_metrics("a b c", "a b c", [{"name": "wer"}]) == {"wer": 0.0}
    assert set(compute_metrics("a b c", "x b c", [{"name": "wer"}, {"name": "cer"}]).keys()) == {"wer", "cer"}


def test_aggregate_basic_stats():
    agg = _aggregate([1.0, 2.0, 3.0, 4.0])
    assert agg["mean"] == 2.5
    assert agg["min"] == 1.0
    assert agg["max"] == 4.0
    assert agg["median"] == 2.5


def test_write_and_load_sample_dataset(tmp_path):
    base = write_sample_dataset(tmp_path / "stt_data")
    assert (base / "samples.jsonl").exists()
    assert (base / "samples.csv").exists()
    assert (base / "audio").is_dir()
    samples = load_stt_dataset(base / "samples.jsonl")
    assert len(samples) == len(SAMPLES)
    assert samples[0].id == "sample_001"


def test_load_csv_dataset(tmp_path):
    base = write_sample_dataset(tmp_path / "stt_data")
    samples = load_stt_dataset(base / "samples.csv")
    assert len(samples) == len(SAMPLES)
    assert samples[1].reference == SAMPLES[1]["reference"]


def test_load_dataset_respects_max_samples(tmp_path):
    base = write_sample_dataset(tmp_path / "stt_data")
    samples = load_stt_dataset(base / "samples.jsonl", max_samples=2)
    assert len(samples) == 2


def test_run_stt_benchmark_with_fake_engine(tmp_path):
    base = write_sample_dataset(tmp_path / "data")
    cfg = STTConfig(
        enabled=True,
        dataset_path=str(base / "samples.jsonl"),
        engines=[
            STTEngineConfig(
                name="fake",
                model="test",
                extra={
                    "results": {str(base / "audio" / "sample_001.wav"): "Das ist ein kurzer Beispielsatz.",
                               str(base / "audio" / "sample_002.wav"): "Lokale Spracherkennung sollte messbar sein.",
                               str(base / "audio" / "sample_003.wav"): "Wir testen die Engine auf Geschwindigkeit."},
                },
            )
        ],
        metrics=[{"name": "wer"}],
        output_dir="stt_results",
    )
    result = run_stt_benchmark(cfg, tmp_path)
    assert result["status"] == "ok"
    assert result["dataset"]["samples_count"] == 3
    engine_result = result["engines"][0]
    assert engine_result["engine"]["name"] == "fake"
    assert "wer" in engine_result["metrics"]
    assert (tmp_path / "stt_results" / "stt_summary.json").exists()


def test_run_stt_benchmark_disabled_returns_skipped(tmp_path):
    cfg = STTConfig(enabled=False)
    result = run_stt_benchmark(cfg, tmp_path)
    assert result["status"] == "skipped"


def test_run_stt_benchmark_missing_dataset_returns_error(tmp_path):
    cfg = STTConfig(enabled=True, dataset_path="/does/not/exist.jsonl")
    result = run_stt_benchmark(cfg, tmp_path)
    assert result["status"] == "error"


def test_stt_config_default_values():
    cfg = STTConfig()
    assert cfg.enabled is False
    assert cfg.engines[0].name == "faster-whisper"
    assert cfg.metrics[0].name == "wer"
