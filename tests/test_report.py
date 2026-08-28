import csv
from pathlib import Path

from llmbench.report import fms, fnum, generate_run_html
from llmbench.runner import _write_csv


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


def test_fnum_and_fms_handle_missing_values():
    assert fnum(None) == "—"
    assert fms(None) == "—"
    assert fms(0.123) == "123.00"
    assert fnum(1.005, 2) == "1.00" or fnum(1.005, 2) == "1.01"


def test_report_shows_provenance_and_warnings(tmp_path: Path):
    out = tmp_path / "report.html"
    generate_run_html(_summary(), out)
    html = out.read_text(encoding="utf-8")
    assert "Nachweis der Testbedingungen" in html
    assert "abc123" in html
    assert "Fremde Prozesse" in html
    assert "Hoechstleistung" in html


def test_report_lists_every_gpu_not_only_the_first(tmp_path: Path):
    out = tmp_path / "report.html"
    generate_run_html(_summary(), out)
    html = out.read_text(encoding="utf-8")
    assert "RTX" in html and "Radeon" in html
    assert "keine Telemetrie" in html


def test_report_marks_failed_benchmarks(tmp_path: Path):
    out = tmp_path / "report.html"
    generate_run_html(_summary("timeout"), out)
    html = out.read_text(encoding="utf-8")
    assert "Zeitueberschreitung" in html
    assert "abgebrochen" in html


def test_csv_keeps_failed_tests_as_rows(tmp_path: Path):
    path = tmp_path / "benchmarks.csv"
    _write_csv(path, _summary("failed"))
    rows = list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()))
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert rows[0]["config_fingerprint"] == "abc123"


def test_csv_contains_fingerprint_for_successful_rows(tmp_path: Path):
    path = tmp_path / "benchmarks.csv"
    _write_csv(path, _summary())
    rows = list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()))
    assert rows[0]["avg_ts"] == "42.0"
    assert rows[0]["status"] == "ok"
    assert rows[0]["config_fingerprint"] == "abc123"


def test_report_shows_soak_results_and_throttling_flag(tmp_path: Path):
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
    out = tmp_path / "report.html"
    generate_run_html(summary, out)
    html = out.read_text(encoding="utf-8")
    assert "Dauerlast-Test" in html
    assert "84" in html
    assert "Ja" in html


def test_report_marks_failed_soak_run(tmp_path: Path):
    summary = _summary()
    summary["models"][0]["soak"] = [
        {"label": "long", "status": "failed", "error": "Server nicht erreichbar"}
    ]
    out = tmp_path / "report.html"
    generate_run_html(summary, out)
    html = out.read_text(encoding="utf-8")
    assert "Server nicht erreichbar" in html
