"""Qualification prerequisites against fake local tools, without real backends."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from llmbench import i18n


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts/qualification_preflight.py"
    spec = importlib.util.spec_from_file_location("qualification_preflight", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def harness(tmp_path, monkeypatch):
    script = _script()
    tools = tmp_path / "tools/llama.cpp"
    tools.mkdir(parents=True)
    for name in ("llama-bench", "llama-server"):
        binary = tools / name
        binary.write_bytes(b"local binary")
        binary.chmod(0o755)
    gguf = tmp_path / "model.gguf"
    gguf.write_bytes(b"GGUF-local-model-fixture")
    h = SimpleNamespace(
        script=script, root=tmp_path, gguf=gguf, calls=[],
        apis={"llama-bench": "CUDA", "llama-server": "CUDA"},
        programs={"docker": "docker", "nvidia-smi": "nvidia-smi"},
        docker_info={"OSType": "linux", "ServerVersion": "29.0", "Runtimes": {"nvidia": {}}, "HttpProxy": "PRIVATE_SENTINEL"},
        nvidia="Test NVIDIA GPU, 615.0\n", bad_image=False,
        state_images={"ollama": script.DEFAULT_OLLAMA_IMAGE, "vllm": script.DEFAULT_VLLM_IMAGE},
    )

    def capture(argv):
        h.calls.append(argv)
        if argv[0] == "git":
            output = "a" * 40 if "rev-parse" in argv else " M PRIVATE_SENTINEL.txt\n"
        elif argv[0] == "nvidia-smi":
            output = h.nvidia
        elif argv[:2] == ["docker", "info"]:
            output = json.dumps(h.docker_info)
        elif argv[:3] == ["docker", "image", "inspect"]:
            reference = argv[3]
            output = json.dumps({"Os": "linux", "Id": reference.rsplit("@", 1)[-1],
                                 "RepoDigests": [] if h.bad_image else [reference],
                                 "Config": {"Env": ["TOKEN=PRIVATE_SENTINEL"]}})
        elif argv[-1] == "--list-devices":
            output = h.apis[Path(argv[0]).name] + "0: Test GPU\n"
        else:
            raise AssertionError(f"Unexpected command: {argv}")
        return subprocess.CompletedProcess(argv, 0, output, "")

    monkeypatch.setattr(script, "_capture", capture)
    monkeypatch.setattr(script.shutil, "which", lambda name: h.programs.get(name))
    monkeypatch.setattr(script.backend_setup, "read_state", lambda name, _root: {"image": h.state_images.get(name)})
    return h


def inspect(h, **overrides):
    return h.script.inspect_prerequisites(**{
        "root": h.root, "backends": list(h.script.BACKENDS), "device": "cuda", "gguf": str(h.gguf), **overrides,
    })


def test_ready_preflight_never_claims_qualification_or_starts_backends(harness):
    h = harness
    report = inspect(h)
    assert report["readiness_status"] == "ready"
    assert report["scope"] == "prerequisites_only"
    assert report["qualification_status"] == "not_run"
    assert report["source"]["dirty"] is True
    assert "PRIVATE_SENTINEL" not in json.dumps(report)
    assert all(item["gpu_passthrough"] == "not_tested" for item in report["backends"])
    assert all(item["model_load"] == "not_tested" for item in report["backends"])
    for command in h.calls:
        if command[0] == "docker":
            assert command[1] == "info" or command[1:3] == ["image", "inspect"]


def test_installer_cuda_marker_and_vulkan_devices_cannot_prove_cuda(harness):
    h = harness
    (h.root / "tools/llama.cpp/.llama-build.json").write_text('{"backend":"cuda"}')
    h.apis["llama-server"] = "Vulkan"
    report = inspect(h, backends=["llama_cpp"])
    assert report["readiness_status"] == "blocked"
    checks = report["backends"][0]["checks"]
    assert any(c["code"] == "native_cuda_device" and c["status"] == "blocked" for c in checks)


@pytest.mark.parametrize("output", ["", "No devices were found", "GPU, N/A\n", "warning, error\n"])
def test_missing_nvidia_evidence_does_not_infer_cpu_only(harness, output):
    h = harness
    h.nvidia = output
    report = inspect(h)
    assert report["readiness_status"] == "blocked"
    assert report["target"]["device"] == "cuda"
    assert report["qualification_status"] == "not_run"
    assert all(any(c["code"] == "nvidia_driver_observed" and c["status"] == "blocked" for c in b["checks"])
               for b in report["backends"])


def test_cpu_preflight_does_not_require_or_probe_cuda(harness):
    h = harness
    h.programs.pop("nvidia-smi")
    report = inspect(h, device="cpu", backends=["llama_cpp", "ollama"])
    assert report["readiness_status"] == "ready"
    assert all(command[-1] != "--list-devices" for command in h.calls)
    assert not any(command[0] == "nvidia-smi" for command in h.calls)


@pytest.mark.parametrize("backends", [["vllm"], ["ollama", "vllm"]])
def test_cpu_vllm_skip_cannot_be_reported_as_fully_ready(harness, backends):
    report = inspect(harness, device="cpu", backends=backends)
    assert report["readiness_status"] == "partial"
    assert report["backends"][-1]["status"] == "not_applicable"


@pytest.mark.parametrize("info", [None, [], {"OSType": "windows"}])
def test_unavailable_or_non_linux_docker_blocks_containers(harness, info):
    h = harness
    h.docker_info = info
    report = inspect(h, backends=["ollama"])
    assert report["readiness_status"] == "blocked"
    assert not any(command[1:3] == ["image", "inspect"] for command in h.calls)


def test_linux_cuda_requires_a_declared_docker_runtime(harness, monkeypatch):
    h = harness
    monkeypatch.setattr(h.script.sys, "platform", "linux")
    h.docker_info["Runtimes"] = {}
    assert inspect(h, backends=["ollama"])["readiness_status"] == "blocked"


def test_local_image_id_is_not_a_repository_digest(harness):
    h = harness
    h.bad_image = True
    report = inspect(h, backends=["ollama"])
    assert report["readiness_status"] == "blocked"
    image = next(c for c in report["backends"][0]["checks"] if c["code"] == "pinned_local_image")
    assert image["evidence"]["digest_matched"] is False


def test_missing_install_state_is_blocked_even_when_image_is_local(harness):
    h = harness
    h.state_images["ollama"] = None
    assert inspect(h, backends=["ollama"])["readiness_status"] == "blocked"


@pytest.mark.parametrize("state", [[], ["invalid"], "invalid"])
def test_malformed_install_state_is_blocked(harness, monkeypatch, state):
    h = harness
    monkeypatch.setattr(h.script.backend_setup, "read_state", lambda *_args: state)
    assert inspect(h, backends=["ollama"])["readiness_status"] == "blocked"


def test_invalid_image_is_not_executed_or_echoed(harness):
    h = harness
    secret = "http://user:PRIVATE_SENTINEL@registry/image:latest"
    h.state_images["ollama"] = secret
    report = inspect(h, backends=["ollama"], ollama_image=secret)
    assert report["readiness_status"] == "blocked"
    assert secret not in json.dumps(report)
    assert not any(command[1:3] == ["image", "inspect"] for command in h.calls)


@pytest.mark.parametrize("content", [b"", b"not-a-GGUF"])
def test_empty_or_invalid_model_blocks_native_preflight(harness, content):
    h = harness
    h.gguf.write_bytes(content)
    assert inspect(h, backends=["llama_cpp"])["readiness_status"] == "blocked"


def test_model_hash_is_optional_and_preserves_the_input(harness):
    h = harness
    original = h.gguf.read_bytes()
    report = inspect(h, backends=["llama_cpp"], hash_model=True)
    model = report["backends"][0]["checks"][-1]["evidence"]
    assert model["sha256"] == hashlib.sha256(original).hexdigest()
    assert h.gguf.read_bytes() == original
    assert report["qualification_status"] == "not_run"
    assert inspect(h, backends=["llama_cpp"])["backends"][0]["checks"][-1]["evidence"]["sha256"] is None


def test_failed_device_probe_cannot_supply_cuda_evidence(harness, monkeypatch):
    h = harness
    original = h.script._capture

    def failed_device(args):
        if args[-1] == "--list-devices":
            return subprocess.CompletedProcess(args, 1, "CUDA0: unavailable", "")
        return original(args)

    monkeypatch.setattr(h.script, "_capture", failed_device)
    assert inspect(h, backends=["llama_cpp"])["readiness_status"] == "blocked"


def test_incomplete_shard_set_is_not_ready(harness):
    h = harness
    shard = h.root / "model-00001-of-00002.gguf"
    shard.write_bytes(b"GGUF-shard")
    assert inspect(h, backends=["llama_cpp"], gguf=str(shard))["readiness_status"] == "blocked"


@pytest.mark.parametrize("backend", ["tgi", "sglang"])
def test_inactive_backends_are_not_part_of_qualification(harness, backend):
    with pytest.raises(ValueError, match="invalid_preflight_target"):
        inspect(harness, backends=[backend])


@pytest.mark.parametrize("error", [OSError("PRIVATE_SENTINEL"), subprocess.TimeoutExpired("probe", 10)])
def test_probe_errors_are_bounded_and_not_echoed(monkeypatch, error):
    script = _script()

    def failed(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(script.subprocess, "run", failed)
    assert script._capture(["test-tool"]) is None


@pytest.mark.parametrize("text", ["invalid JSON", "[]", "null"])
def test_invalid_json_probe_is_unavailable(monkeypatch, text):
    script = _script()
    monkeypatch.setattr(script, "_capture", lambda args: subprocess.CompletedProcess(args, 0, text, ""))
    assert script._json_probe(["test-tool"]) is None


def test_main_saves_blocked_report_without_overwriting(harness):
    h = harness
    h.programs.pop("docker")
    output = h.root / "evidence"
    args = ["--root", str(h.root), "--backends", "ollama", "--output", str(output)]
    assert h.script.main(args) == 2
    path = output / "report.json"
    original = path.read_bytes()
    assert json.loads(original)["qualification_status"] == "not_run"
    calls_before = len(h.calls)
    with pytest.raises(SystemExit):
        h.script.main(args)
    assert path.read_bytes() == original and len(h.calls) == calls_before


def test_english_cli_does_not_claim_release_acceptance(harness, capsys):
    h = harness
    i18n.set_language("en")
    output = h.root / "english"
    assert h.script.main(["--root", str(h.root), "--device", "cpu", "--backends", "ollama", "--output", str(output)]) == 0
    text = capsys.readouterr().out
    assert "Preflight: ready" in text
    assert "Hardware qualification was not run" in text


def test_report_write_error_is_safe_and_not_a_ready_exit(harness, monkeypatch, capsys):
    h = harness

    def failed(*_args):
        raise OSError("PRIVATE_SENTINEL")

    monkeypatch.setattr(h.script, "write_json", failed)
    assert h.script.main(["--root", str(h.root), "--device", "cpu", "--backends", "ollama",
                          "--output", str(h.root / "unwritable")]) == 1
    captured = capsys.readouterr()
    assert "PRIVATE_SENTINEL" not in captured.out + captured.err
