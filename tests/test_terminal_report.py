import io

from rich.console import Console

from llmbench.terminal_report import print_run_report
from tests.test_report import _summary


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
