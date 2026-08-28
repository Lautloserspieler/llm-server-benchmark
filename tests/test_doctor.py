import subprocess
from pathlib import Path

from llmbench.config import DEFAULT_CONFIG, deep_merge
from llmbench.doctor import doctor


def _cfg(tmp_path: Path, **model_overrides):
    cfg = deep_merge(DEFAULT_CONFIG, {})
    cfg["_config_dir"] = str(tmp_path)
    cfg["models"] = [
        {
            "name": "M",
            "path": model_overrides.get("path", "model.gguf"),
            "profiles": [{"name": "Full-GPU", "gpu_layers": -1}],
        }
    ]
    return cfg


def _fake_run_capture(returncode=0, stdout="", stderr=""):
    def _inner(cmd, **_kwargs):
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)

    return _inner


HELP_TEXT_ALL_FLAGS = (
    "--flash-attn on|off|auto --cache-type-k --cache-type-v --n-depth --batch-size "
    "--ubatch-size --n-gpu-layers --repetitions --n-cpu-moe --no-kv-offload "
    "--tensor-split --device"
)


def test_doctor_flags_missing_model_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("llmbench.doctor.collect_hardware", lambda *_a, **_kw: {"gpus": [], "memory": {}})
    monkeypatch.setattr("llmbench.doctor.command_exists", lambda *_a, **_kw: False)

    cfg = _cfg(tmp_path)
    data = doctor(cfg)

    assert data["models"][0]["exists"] is False
    assert data["checks"][0]["ok"] is False


def test_doctor_reports_existing_model_and_fingerprint(tmp_path: Path, monkeypatch):
    model_file = tmp_path / "model.gguf"
    model_file.write_bytes(b"x" * 1024)

    monkeypatch.setattr(
        "llmbench.doctor.collect_hardware",
        lambda *_a, **_kw: {"gpus": [], "memory": {"total_bytes": 16 * 1024**3}, "disk": {"free_bytes": 100 * 1024**3}},
    )
    monkeypatch.setattr("llmbench.doctor.command_exists", lambda *_a, **_kw: False)

    cfg = _cfg(tmp_path)
    data = doctor(cfg)

    assert data["models"][0]["exists"] is True
    assert data["models"][0]["size_bytes"] == 1024
    assert data["config_fingerprint"]
    assert "Keine GPU erkannt" in " ".join(data["warnings"])


def test_doctor_warns_about_model_not_fitting_in_vram(tmp_path: Path, monkeypatch):
    import os

    model_file = tmp_path / "model.gguf"
    model_file.touch()
    os.truncate(model_file, 10 * 1024 ** 3)  # sparse file, 10 GiB reported size

    monkeypatch.setattr(
        "llmbench.doctor.collect_hardware",
        lambda *_a, **_kw: {
            "gpus": [{"vendor": "NVIDIA", "name": "RTX", "memory.total": 8 * 1024, "telemetry": "nvml"}],
            "memory": {"total_bytes": 64 * 1024**3},
            "disk": {"free_bytes": 100 * 1024**3},
        },
    )
    monkeypatch.setattr("llmbench.doctor.command_exists", lambda *_a, **_kw: False)

    cfg = _cfg(tmp_path)
    data = doctor(cfg)

    entry = data["models"][0]
    assert entry["fits_in_vram"] is False
    assert "Full-GPU-Profil" in entry["hint"]


def test_doctor_warns_when_gpu_has_no_telemetry(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "llmbench.doctor.collect_hardware",
        lambda *_a, **_kw: {
            "gpus": [{"vendor": "AMD", "name": "RX", "telemetry": "none"}],
            "memory": {"total_bytes": 32 * 1024**3},
            "disk": {"free_bytes": 100 * 1024**3},
        },
    )
    monkeypatch.setattr("llmbench.doctor.command_exists", lambda *_a, **_kw: False)

    cfg = _cfg(tmp_path)
    data = doctor(cfg)

    assert any("keine Telemetrie" in w for w in data["warnings"])


def test_doctor_warns_about_low_disk_space(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "llmbench.doctor.collect_hardware",
        lambda *_a, **_kw: {"gpus": [], "memory": {}, "disk": {"free_bytes": 1024, "root": str(tmp_path)}},
    )
    monkeypatch.setattr("llmbench.doctor.command_exists", lambda *_a, **_kw: False)

    cfg = _cfg(tmp_path)
    data = doctor(cfg)

    assert any("frei unter" in w for w in data["warnings"])


def test_doctor_flags_llama_bench_missing_required_options(tmp_path: Path, monkeypatch):
    exe = tmp_path / "llama-bench"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)

    monkeypatch.setattr(
        "llmbench.doctor.collect_hardware",
        lambda *_a, **_kw: {"gpus": [], "memory": {}, "disk": {}},
    )
    monkeypatch.setattr("llmbench.doctor.command_exists", lambda *_a, **_kw: True)
    monkeypatch.setattr("llmbench.doctor.resolve_executable", lambda *_a, **_kw: str(exe))
    monkeypatch.setattr(
        "llmbench.doctor.run_capture", _fake_run_capture(stdout="--batch-size only, nothing else")
    )
    monkeypatch.setattr("llmbench.doctor.probe_build", lambda *_a, **_kw: {})

    cfg = _cfg(tmp_path)
    cfg["tools"] = {"llama_bench": str(exe), "llama_server": str(exe)}
    data = doctor(cfg)

    llama_bench_check = next(c for c in data["checks"] if c["name"] == "llama_bench")
    assert llama_bench_check["ok"] is False
    assert "-ngl" in llama_bench_check["error"]
    assert "-ngl" in llama_bench_check["flags"]["missing_required"]


def test_doctor_passes_when_all_required_flags_are_present(tmp_path: Path, monkeypatch):
    exe = tmp_path / "llama-bench"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)

    monkeypatch.setattr(
        "llmbench.doctor.collect_hardware",
        lambda *_a, **_kw: {"gpus": [], "memory": {}, "disk": {}},
    )
    monkeypatch.setattr("llmbench.doctor.command_exists", lambda *_a, **_kw: True)
    monkeypatch.setattr("llmbench.doctor.resolve_executable", lambda *_a, **_kw: str(exe))
    monkeypatch.setattr("llmbench.doctor.run_capture", _fake_run_capture(stdout=HELP_TEXT_ALL_FLAGS))
    monkeypatch.setattr("llmbench.doctor.probe_build", lambda *_a, **_kw: {"commit": "abc"})

    cfg = _cfg(tmp_path)
    cfg["tools"] = {"llama_bench": str(exe), "llama_server": str(exe)}
    data = doctor(cfg)

    llama_bench_check = next(c for c in data["checks"] if c["name"] == "llama_bench")
    assert llama_bench_check["ok"] is True
    assert llama_bench_check["flags"]["missing_required"] == []
