import io

from llmbench.progress import (
    LiveReporter,
    Reporter,
    format_duration,
    make_reporter,
    telemetry_line,
)


class FakeTty(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_format_duration():
    assert format_duration(None) == "--:--"
    assert format_duration(0) == "00:00"
    assert format_duration(75) == "01:15"
    assert format_duration(3725) == "1:02:05"


def test_telemetry_line_uses_first_gpu():
    sample = {
        "cpu_percent": 42.4,
        "ram_percent": 60,
        "gpus": [{
            "util_gpu_percent": 97.5,
            "memory_used_bytes": 11 * 1024**3,
            "memory_total_bytes": 12 * 1024**3,
            "power_w": 186.2,
            "temperature_c": 71.0,
        }],
    }
    line = telemetry_line(sample)
    assert "CPU 42%" in line
    assert "GPU 98%" in line
    assert "11.0/12.0 GiB" in line
    assert "186 W" in line
    assert "71 °C" in line


def test_telemetry_line_without_gpu_falls_back_to_ram():
    line = telemetry_line({"cpu_percent": 10, "ram_percent": 55, "gpus": []})
    assert "RAM 55%" in line
    assert "GPU" not in line


def test_telemetry_line_handles_missing_sample():
    assert telemetry_line(None) == ""


def test_make_reporter_needs_a_terminal():
    assert isinstance(make_reporter(stream=io.StringIO()), Reporter)
    assert not isinstance(make_reporter(stream=io.StringIO()), LiveReporter)
    assert isinstance(make_reporter(stream=FakeTty()), LiveReporter)


def test_make_reporter_honours_force_plain():
    assert not isinstance(make_reporter(force_plain=True, stream=FakeTty()), LiveReporter)


def test_live_reporter_overwrites_its_status_line():
    stream = FakeTty()
    reporter = LiveReporter(stream)
    reporter.run_started("SRV-A", 3)
    reporter.test_started("M", "Full-GPU", "prompt")
    reporter.MIN_INTERVAL = 0.0
    reporter.progress("2/5", {"cpu_percent": 50, "gpus": []})
    reporter.progress("3/5", {"cpu_percent": 51, "gpus": []})
    output = stream.getvalue()
    assert "\r" in output
    assert output.count("\n") <= 2  # nur die festen Zeilen, nicht je Fortschritt


def test_plain_reporter_writes_no_carriage_returns():
    stream = io.StringIO()
    reporter = Reporter(stream)
    reporter.run_started("SRV-A", 3)
    reporter.test_started("M", "Full-GPU", "prompt")
    reporter.progress("2/5", {"cpu_percent": 50, "gpus": []})
    assert "\r" not in stream.getvalue()


def test_finished_test_prints_its_result():
    stream = io.StringIO()
    reporter = Reporter(stream)
    reporter.run_started("SRV-A", 1)
    reporter.test_started("M", "Full-GPU", "generation")
    reporter.test_finished("ok", [{"test": "tg128", "avg_ts": 58.7, "stddev_ts": 0.4}])
    text = stream.getvalue()
    assert "tg128" in text
    assert "58.70" in text


def test_failed_test_is_named_as_such():
    stream = io.StringIO()
    reporter = Reporter(stream)
    reporter.run_started("SRV-A", 1)
    reporter.test_started("M", "Full-GPU", "long_context")
    reporter.test_finished("timeout", [], "zu wenig VRAM")
    assert "Zeitueberschreitung" in stream.getvalue()


def test_remaining_time_is_estimated_per_kind():
    """Ein Long-Context-Test dauert ein Vielfaches eines Prompt-Tests.
    Ein Gesamtmittel waere deshalb deutlich daneben."""
    reporter = Reporter(io.StringIO())
    reporter.run_started("SRV-A", 4)
    reporter._durations = {"prompt": [10.0], "long_context": [100.0]}
    reporter.finished_tests = 2

    reporter._current_kind = "long_context"
    reporter._current_started = None
    assert abs(reporter.remaining_seconds() - 200.0) < 1e-6

    reporter._current_kind = "prompt"
    assert abs(reporter.remaining_seconds() - 20.0) < 1e-6


def test_remaining_time_unknown_before_first_result():
    reporter = Reporter(io.StringIO())
    reporter.run_started("SRV-A", 4)
    assert reporter.remaining_seconds() is None


def test_remaining_time_is_none_when_done():
    reporter = Reporter(io.StringIO())
    reporter.run_started("SRV-A", 1)
    reporter._durations = {"prompt": [5.0]}
    reporter.finished_tests = 1
    assert reporter.remaining_seconds() is None
