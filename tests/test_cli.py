import json
from pathlib import Path

from llmbench.cli import build_parser, main


def test_build_parser_run_defaults():
    args = build_parser().parse_args(["run"])
    assert args.cmd == "run"
    assert args.config == "benchmark.yaml"
    assert args.model is None
    assert args.duration is None
    assert args.hardware == "both"
    assert args.skip_endpoint is False
    assert args.plain is False


def test_build_parser_run_accepts_all_options():
    args = build_parser().parse_args([
        "run", "--config", "custom.yaml", "--model", "Qwen", "--duration", "short",
        "--hardware", "cpu", "--skip-endpoint", "--plain",
    ])
    assert args.config == "custom.yaml"
    assert args.model == "Qwen"
    assert args.duration == "short"
    assert args.hardware == "cpu"
    assert args.skip_endpoint is True
    assert args.plain is True


def test_build_parser_run_rejects_invalid_hardware_choice():
    import pytest

    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--hardware", "npu"])


def test_build_parser_compare_requires_at_least_one_input():
    args = build_parser().parse_args(["compare", "results/A", "results/B", "--strict"])
    assert args.inputs == ["results/A", "results/B"]
    assert args.strict is True


def test_build_parser_rejects_unknown_command():
    import pytest

    with pytest.raises(SystemExit):
        build_parser().parse_args(["not-a-command"])


def test_main_init_writes_example_config(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = main(["init", "--output", "out.yaml"])
    assert rc == 0
    assert (tmp_path / "out.yaml").exists()


def test_main_run_reports_config_errors_and_exits_2(tmp_path: Path, capsys):
    bad_config = tmp_path / "benchmark.yaml"
    bad_config.write_text("benchmark:\n  repetitions: 0\n  prompt_tokens: []\n", encoding="utf-8")

    rc = main(["run", "--config", str(bad_config)])
    out = capsys.readouterr()
    assert rc == 2
    assert "Konfigurationsfehler" in out.err


def test_main_run_passes_hardware_choice_to_run_suite(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "benchmark.yaml"
    config_path.write_text(
        "models:\n  - name: M\n    path: model.gguf\n    profiles:\n      - name: GPU\n        gpu_layers: -1\n",
        encoding="utf-8",
    )
    captured = {}

    def _fake_run_suite(_cfg, **kwargs):
        captured.update(kwargs)
        return tmp_path

    monkeypatch.setattr("llmbench.cli.run_suite", _fake_run_suite)
    rc = main(["run", "--config", str(config_path), "--hardware", "gpu"])
    assert rc == 0
    assert captured["hardware_target"] == "gpu"


def test_main_doctor_json_reports_status(tmp_path: Path, monkeypatch, capsys):
    config_path = tmp_path / "benchmark.yaml"
    config_path.write_text(
        "models:\n  - name: M\n    path: model.gguf\n    profiles:\n      - name: GPU\n        gpu_layers: -1\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "llmbench.cli.doctor",
        lambda _cfg: {"checks": [], "models": [], "hardware": {"gpus": []}, "warnings": [], "config_fingerprint": "abc"},
    )

    rc = main(["doctor", "--config", str(config_path), "--json"])
    out = capsys.readouterr()
    assert rc == 0
    data = json.loads(out.out)
    assert data["config_fingerprint"] == "abc"


def test_main_compare_dispatches_and_reports_issues(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(
        "llmbench.cli.compare_summaries",
        lambda _inputs, _out: (
            str(tmp_path / "comparison.html"),
            [{"level": "error", "topic": "build", "message": "unterschiedlich"}],
        ),
    )
    rc = main(["compare", "results/A", "results/B", "--strict"])
    out = capsys.readouterr()
    assert rc == 1
    assert "FEHLER" in out.out
    assert "unterschiedlich" in out.out


def test_main_compare_without_strict_returns_zero_even_with_errors(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "llmbench.cli.compare_summaries",
        lambda _inputs, _out: (
            str(tmp_path / "comparison.html"),
            [{"level": "error", "topic": "build", "message": "unterschiedlich"}],
        ),
    )
    rc = main(["compare", "results/A", "results/B"])
    assert rc == 0
