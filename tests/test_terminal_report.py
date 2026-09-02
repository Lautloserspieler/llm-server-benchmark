import io

from rich.console import Console

from llmbench.terminal_report import print_run_report


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
