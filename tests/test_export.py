import zipfile
from pathlib import Path

from llmbench.export import export_run
from llmbench.config import public_config
from llmbench.utils import write_json


def test_export_redacts_secrets_from_server_logs(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "server.log").write_text(
        "docker run --api-key sk-live\nHF_TOKEN=hf_live\n",
        encoding="utf-8",
    )

    archive = export_run(run_dir, tmp_path / "run.zip")

    with zipfile.ZipFile(archive) as zf:
        exported = zf.read("run/server.log").decode("utf-8")

    assert "sk-live" not in exported
    assert "hf_live" not in exported
    assert "--api-key ***" in exported
    assert "HF_TOKEN=***" in exported


def test_export_masks_basic_auth_and_argument_secrets(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    cfg = {"endpoint": {"server_additional_args": ["--api-key", "-endpoint-secret"]},
           "models": [{"profiles": [{"additional_args": ["--hf-token", "hf_secret"]}]}],
           "metrics": {"tokens": 42}}
    write_json(run_dir / "summary.json", {"config": public_config(cfg)})
    (run_dir / "server.log").write_text("Authorization: Basic dXNlcjpzeW50aGV0aWM=\n", encoding="utf-8")
    archive = export_run(run_dir, tmp_path / "run.zip")
    with zipfile.ZipFile(archive) as zf:
        summary = zf.read("run/summary.json").decode()
        log = zf.read("run/server.log").decode()
    assert "-endpoint-secret" not in summary
    assert "hf_secret" not in summary
    assert '"tokens": 42' in summary
    assert "dXNlcjpzeW50aGV0aWM=" not in log
    assert log == "Authorization: ***\n"
