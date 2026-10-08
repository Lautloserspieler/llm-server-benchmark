import io

from rich.console import Console

from llmbench.result_schema import encode_v3, envelope
from llmbench.terminal_report import print_run_report
from llmbench.kv_cache import KvCacheObservation, normalize_kv_cache


def _summary(bench_status: str = "ok") -> dict:
    bench = (
        {"kind": "generation", "status": "ok",
         "rows": [{"n_prompt": 0, "n_gen": 128, "n_depth": 0, "avg_ts": 42.0}],
         "telemetry": {"gpus": [{"index": 0, "avg_power_w": 100.0, "max_temperature_c": 71.0},
                                {"index": 1, "avg_power_w": 90.0, "max_temperature_c": 68.0}]}}
        if bench_status == "ok"
        else {"kind": "generation", "status": bench_status, "error": "abgebrochen", "telemetry": {}}
    )
    return {
        "schema_version": 2,
        "llmbench_version": "1.2.0",
        "server_name": "SRV-A",
        "project": "Test",
        "started_at": "2026-08-23T10:00:00+00:00",
        "config_fingerprint": "abc123",
        "config": {"benchmark": {"repetitions": 5, "batch_size": 2048, "ubatch_size": 512,
                                 "flash_attention": "auto", "cache_type_k": "f16",
                                 "cache_type_v": "f16"}},
        "tools": {"llama_cpp_build_ids": ["abc/123"],
                  "llama_bench": {"binary": {"sha256": "f" * 64}}},
        "hardware": {"cpu": {"name": "CPU"}, "memory": {"total_bytes": 8 * 1024**3},
                     "power_scheme": "Hoechstleistung",
                     "gpus": [{"vendor": "NVIDIA", "name": "RTX", "memory.total": 24576,
                               "telemetry": "nvml"},
                              {"vendor": "AMD", "name": "Radeon", "telemetry": "none"}]},
        "warnings": ["Fremde Prozesse haben die GPU benutzt"],
        "models": [{
            "model": {"name": "M", "sha256": "a" * 64, "size_bytes": 1024},
            "profiles": [{"name": "Full-GPU", "settings": {"gpu_layers": -1},
                          "benchmarks": {"generation": bench}}],
        }],
    }


def _render(summary: dict) -> str:
    buf = io.StringIO()
    console = Console(file=buf, width=120, force_terminal=True, color_system=None)
    print_run_report(summary, console)
    return buf.getvalue()


def test_terminal_report_shows_provenance_and_warnings():
    text = _render(_summary())
    assert "Nachweis der Testbedingungen" in text
    assert "abc123" in text
    assert "Fremde Prozesse" in text
    assert "Hoechstleistung" in text


def test_terminal_report_lists_every_gpu_not_only_the_first():
    text = _render(_summary())
    assert "RTX" in text and "Radeon" in text
    assert "keine Telemetrie" in text


def test_terminal_report_marks_failed_benchmarks():
    text = _render(_summary("timeout"))
    assert "Zeitueberschreitung" in text
    assert "abgebrochen" in text


def test_terminal_report_shows_soak_results_and_throttling_flag():
    summary = _summary()
    summary["models"][0]["soak"] = [{
        "label": "short",
        "status": "ok",
        "cpu": {"avg_tps": 20.0, "early_window_avg_tps": 21.0, "late_window_avg_tps": 19.0,
                "successful": 8, "requests": 8, "throttling_suspected": False},
        "gpu": {"avg_tps": 90.0, "early_window_avg_tps": 100.0, "late_window_avg_tps": 60.0,
                "successful": 30, "requests": 30, "throttling_suspected": True,
                "note": "Tokens/s gefallen"},
        "telemetry": {"gpus": [{"index": 0, "max_temperature_c": 84.0}]},
    }]
    text = _render(summary)
    assert "Dauerlast-Test" in text
    assert "84" in text
    assert "Ja" in text


def test_terminal_report_marks_failed_soak_run():
    summary = _summary()
    summary["models"][0]["soak"] = [
        {"label": "long", "status": "failed", "error": "Server nicht erreichbar"}
    ]
    text = _render(summary)
    assert "Server nicht erreichbar" in text


def test_terminal_report_shows_kv_value_and_source_but_not_backend_details():
    summary = encode_v3(_summary())
    cache = normalize_kv_cache("llama_cpp", [KvCacheObservation("k_dtype", "q8_0", provider="llama.cpp")])
    cache["backend_details"] = {"llama_cpp": {"private": envelope("hidden", "detected")}}
    summary["models"][0]["profiles"][0]["kv_cache"] = cache
    text = _render(summary)
    assert "Effektive KV-Cache-Konfiguration" in text
    assert "q8_0" in text and "detected" in text
    assert "private" not in text and "hidden" not in text


def test_terminal_report_shows_endpoint_results():
    summary = _summary()
    summary["models"][0]["endpoint"] = {
        "status": "ok",
        "profile": "Full-GPU",
        "settings": {"max_tokens": 128, "seed": 42, "ignore_eos": True},
        "warmup": {"requests": 3},
        "levels": [{
            "concurrency": 4, "successful": 4, "requests": 4, "system_tps": 55.5,
            "avg_interactivity_tps": 13.9, "ttft_p50_seconds": 0.15, "ttft_p95_seconds": 0.3,
        }],
    }
    text = _render(summary)
    assert "Endpoint-/Multi-User-Test" in text
    assert "55.50" in text


def test_terminal_report_marks_failed_model():
    summary = _summary()
    summary["models"][0]["status"] = "failed"
    summary["models"][0]["error"] = "Modell nicht gefunden"
    text = _render(summary)
    assert "Modell nicht gefunden" in text


def test_terminal_report_keeps_partial_long_context_rows():
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
    text = _render(summary)
    assert "55.73" in text
    assert "Teilweise" in text
    assert "262144" in text


def test_terminal_report_labels_soak_capacity_limit():
    summary = _summary()
    summary["models"][0]["soak"] = [{
        "label": "long",
        "status": "skipped_capacity",
        "error": "Full-GPU passt nicht in den erkannten VRAM.",
    }]
    text = _render(summary)
    assert "Kapazitaetsgrenze" in text
    assert "VRAM" in text


def test_terminal_report_keeps_v3_bandwidth_envelopes_before_projection():
    summary = encode_v3(_summary(), {("M", "Full-GPU"): "requested"})
    summary["hardware"]["memory_domains"] = [{
        "id": "apple:unified:0", "kind": "unified_memory", "vendor": "Apple",
        "bandwidth": {"theoretical": envelope(410.0, "detected", unit="GB/s")},
    }]
    summary["telemetry"] = {"memory_bandwidth": [{
        "domain_id": "apple:unified:0", "scope": "system_soc_dram",
        "observed_during_benchmark": envelope(120.0, "measured", unit="GB/s"),
    }]}
    text = _render(summary)
    assert "Memory bandwidth" in text
    assert "410.00 GB/s" in text
    assert "120.00 GB/s" in text

def test_terminal_report_shows_context_capability_boundary():
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

    text = _render(summary)
    assert "Kontext-Kapazitaet" in text
    assert "131072" in text
    assert "262144" in text
    assert "Kapazitaetsgrenze" in text
