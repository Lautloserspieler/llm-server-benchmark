from pathlib import Path

import pytest

pytest.importorskip("reportlab")
pypdf = pytest.importorskip("pypdf")

from llmbench.pdf_report import generate_run_pdf  # noqa: E402
from llmbench.result_schema import encode_v3  # noqa: E402
from llmbench.kv_cache import KvCacheObservation, normalize_kv_cache  # noqa: E402


def _summary(with_endpoint: bool = True, failing: bool = False) -> dict:
    bench_ok = {
        "kind": "generation", "status": "ok",
        "rows": [{"n_prompt": 0, "n_gen": 128, "n_depth": 0, "avg_ts": 58.75,
                  "stddev_ts": 0.4, "build_commit": "abc1234"}],
        "telemetry": {"avg_cpu_percent": 22.0, "max_ram_used_bytes": 8 * 1024**3,
                      "gpus": [{"index": 0, "avg_util_gpu_percent": 97.0,
                                "max_memory_used_bytes": 11 * 1024**3,
                                "avg_power_w": 186.0, "max_temperature_c": 71.0}]},
    }
    bench_bad = {"kind": "long_context", "status": "timeout",
                 "error": "Kontexttiefe passt nicht in den Speicher", "telemetry": {}}
    benchmarks = {"generation": bench_ok}
    if failing:
        benchmarks["long_context"] = bench_bad

    model = {
        "model": {"name": "qwen-27b-q4_0", "sha256": "a" * 64,
                  "size_bytes": 17 * 1024**3, "path": "models/qwen.gguf",
                  "quality_gate": "Nicht bewertet"},
        "profiles": [{"name": "Full-GPU", "settings": {"gpu_layers": -1, "threads": "auto"},
                      "benchmarks": benchmarks}],
    }
    if with_endpoint:
        model["endpoint"] = {
            "status": "ok",
            "levels": [{"concurrency": 4, "successful": 8, "requests": 8,
                        "system_tps": 210.5, "avg_interactivity_tps": 52.6,
                        "ttft_p50_seconds": 0.12, "ttft_p95_seconds": None}],
        }
    return {
        "schema_version": 2, "llmbench_version": "1.3.0", "server_name": "SRV-WERKSTATT",
        "project": "Firmenweiter LLM Server Benchmark",
        "started_at": "2026-08-23T10:00:00+00:00", "finished_at": "2026-08-23T11:20:00+00:00",
        "config_fingerprint": "5f1521be7761070c",
        "config": {"benchmark": {"repetitions": 5, "batch_size": 2048, "ubatch_size": 512,
                                 "flash_attention": "auto", "cache_type_k": "f16",
                                 "cache_type_v": "f16"}},
        "tools": {"llama_cpp_build_ids": ["abc1234/10595"],
                  "llama_bench": {"binary": {"sha256": "f" * 64}}},
        "hardware": {"os": "Windows-11", "cpu": {"name": "Ryzen 9", "physical_cores": 12,
                                                 "logical_cores": 24},
                     "memory": {"total_bytes": 64 * 1024**3},
                     "power_scheme": "Hoechstleistung",
                     "gpus": [{"index": 0, "vendor": "NVIDIA", "name": "RTX 5070",
                               "memory.total": 12226, "driver_version": "610.88",
                               "telemetry": "nvml"}]},
        "warnings": ["Fremde Prozesse haben waehrend der Messung die GPU benutzt"],
        "models": [model],
    }


def _text(path: Path) -> str:
    reader = pypdf.PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_pdf_is_created_and_readable(tmp_path: Path):
    out = generate_run_pdf(_summary(), tmp_path / "report.pdf")
    assert out.exists() and out.stat().st_size > 3000
    assert pypdf.PdfReader(str(out)).pages


def test_v3_pdf_executes_and_includes_provenance(tmp_path: Path):
    text = _text(generate_run_pdf(encode_v3(_summary(), {("qwen-27b-q4_0", "Full-GPU"): "requested"}), tmp_path / "v3.pdf"))
    assert "Wert-Provenienz" in text
    assert "gemessen" in text


def test_v3_pdf_shows_runtime_memory_bandwidth_telemetry(tmp_path: Path):
    summary = _summary()
    summary["hardware"]["memory_domains"] = [{
        "id": "apple:unified:0", "kind": "unified_memory", "vendor": "Apple",
        "bandwidth": {"theoretical": {"value": 410.0, "source": "detected", "unit": "GB/s"}},
    }]
    summary["telemetry"] = {"memory_bandwidth": [{
        "domain_id": "apple:unified:0", "scope": "system_soc_dram",
        "observed_during_benchmark": {"value": 120.0, "source": "measured", "unit": "GB/s"},
    }]}
    text = _text(generate_run_pdf(encode_v3(summary), tmp_path / "bandwidth-v3.pdf"))
    assert "Memory bandwidth runtime telemetry" in text
    assert "120.00 GB/s" in text


def test_v3_pdf_shows_kv_core_without_backend_details(tmp_path: Path):
    summary = encode_v3(_summary())
    cache = normalize_kv_cache("llama_cpp", [KvCacheObservation("k_dtype", "q8_0", provider="llama.cpp")])
    cache["backend_details"] = {"llama_cpp": {"private": {"value": "hidden", "source": "detected"}}}
    summary["models"][0]["profiles"][0]["kv_cache"] = cache
    text = _text(generate_run_pdf(summary, tmp_path / "kv.pdf"))
    assert "Effektive KV-Cache-Konfiguration" in text
    assert "q8_0" in text
    assert "private" not in text and "hidden" not in text


def test_pdf_contains_server_hardware_and_results(tmp_path: Path):
    text = _text(generate_run_pdf(_summary(), tmp_path / "r.pdf"))
    assert "SRV-WERKSTATT" in text
    assert "RTX 5070" in text
    assert "Ryzen 9" in text
    assert "qwen-27b-q4_0" in text
    assert "58.75" in text
    assert "Full-GPU" in text


def test_pdf_documents_the_test_conditions(tmp_path: Path):
    """Der Nachweis gehoert in den Bericht, sonst ist er nicht belegbar."""
    text = _text(generate_run_pdf(_summary(), tmp_path / "r.pdf"))
    assert "5f1521be7761070c" in text
    assert "abc1234/10595" in text
    assert "Hoechstleistung" in text


def test_pdf_shows_warnings_and_failures(tmp_path: Path):
    text = _text(generate_run_pdf(_summary(failing=True), tmp_path / "r.pdf"))
    assert "Fremde Prozesse" in text
    assert "Zeitüberschreitung" in text


def test_pdf_contains_endpoint_results_and_blank_ttft(tmp_path: Path):
    text = _text(generate_run_pdf(_summary(), tmp_path / "r.pdf"))
    assert "210.50" in text
    assert "120.00" in text  # TTFT P50 in Millisekunden


def test_pdf_without_endpoint_still_builds(tmp_path: Path):
    out = generate_run_pdf(_summary(with_endpoint=False), tmp_path / "r.pdf")
    assert out.exists()


def test_pdf_contains_soak_results_and_throttling_flag(tmp_path: Path):
    summary = _summary()
    summary["models"][0]["soak"] = [{
        "label": "short",
        "status": "ok",
        "cpu": {"avg_tps": 20.0, "early_window_avg_tps": 21.0, "late_window_avg_tps": 19.0,
                "successful": 8, "requests": 8, "throttling_suspected": False},
        "gpu": {"avg_tps": 90.0, "early_window_avg_tps": 100.0, "late_window_avg_tps": 60.0,
                "successful": 30, "requests": 30, "throttling_suspected": True},
        "telemetry": {"gpus": [{"index": 0, "max_temperature_c": 84.0}]},
    }]
    text = _text(generate_run_pdf(summary, tmp_path / "r.pdf"))
    assert "Dauerlast-Test (CPU + GPU gleichzeitig)" in text
    assert "90.00" in text
    assert "Ja" in text
    assert "84" in text


def test_pdf_marks_failed_soak_run(tmp_path: Path):
    summary = _summary()
    summary["models"][0]["soak"] = [
        {"label": "long", "status": "failed", "error": "Server nicht erreichbar"}
    ]
    text = _text(generate_run_pdf(summary, tmp_path / "r.pdf"))
    assert "Server nicht erreichbar" in text


def test_pdf_survives_an_empty_run(tmp_path: Path):
    minimal = {"server_name": "leer", "models": [], "hardware": {}, "warnings": []}
    out = generate_run_pdf(minimal, tmp_path / "leer.pdf")
    assert out.exists()


def test_pdf_keeps_partial_long_context_rows(tmp_path: Path):
    summary = _summary()
    summary["models"][0]["profiles"][0]["benchmarks"]["long_context"] = {
        "kind": "long_context",
        "status": "partial",
        "rows": [{
            "n_prompt": 0,
            "n_gen": 128,
            "n_depth": 131072,
            "avg_ts": 55.73,
            "stddev_ts": 0.12,
        }],
        "error": "Kontextstufe 262144 konnte nicht erstellt werden.",
        "telemetry": {},
    }
    text = _text(generate_run_pdf(summary, tmp_path / "partial.pdf"))
    assert "55.73" in text
    assert "262144" in text


def test_pdf_labels_soak_capacity_limit(tmp_path: Path):
    summary = _summary()
    summary["models"][0]["soak"] = [{
        "label": "long",
        "status": "skipped_capacity",
        "error": "Full-GPU passt nicht in den erkannten VRAM.",
    }]
    text = _text(generate_run_pdf(summary, tmp_path / "capacity.pdf"))
    assert "Kapazitaetsgrenze" in text
    assert "VRAM" in text

def test_pdf_shows_context_capability_boundary(tmp_path: Path):
    summary = _summary()
    summary["models"][0]["profiles"][0]["context_capability"] = {
        "maximum_verified_context": 131072,
        "completed_context_depths": [0, 131072],
        "requested_context_depths": [0, 131072, 262144],
        "first_failed_context": 262144,
        "limit_status": "skipped_capacity",
        "curve": [
            {"populated_context": 131072, "prefill_tps": 1200.0, "decode_tps": 55.0,
             "combined_tps": None, "result": "pass"},
            {"populated_context": 262144, "prefill_tps": None, "decode_tps": None,
             "combined_tps": None, "result": "oom"},
        ],
    }

    text = _text(generate_run_pdf(summary, tmp_path / "context.pdf"))
    assert "Kontext-Kapazitaet" in text
    assert "131072" in text
    assert "262144" in text
    assert "Kapazitaetsgrenze" in text
