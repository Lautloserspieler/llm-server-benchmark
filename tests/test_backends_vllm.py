"""VllmBackend gegen gemockte docker_backend-Funktionen. Kein echtes Docker."""

from pathlib import Path

import pytest

from llmbench.backends import get_backend
from llmbench.backends.vllm import CONTAINER_PORT, MODEL_MOUNT, VllmBackend

IMAGE = "vllm/vllm-openai:latest"


@pytest.fixture
def docker(monkeypatch):
    """Ersetzt den Container-Lebenszyklus und protokolliert die Aufrufe."""

    class _Fake:
        def __init__(self):
            self.runs: list[dict] = []
            self.stopped: list[str] = []
            self.pid: int | None = 4242
            self.existing = False

        def run_container(self, name, image, args, **kwargs):
            self.runs.append({"name": name, "image": image, "args": list(args), **kwargs})
            return "CONTAINERID"

        def stop_container(self, name, log=None):  # noqa: ARG002
            self.stopped.append(name)

        def container_pid(self, _name):
            return self.pid

        def container_exists(self, _name):
            return self.existing

        def container_logs(self, _name, tail=None):  # noqa: ARG002
            return "server log"

    fake = _Fake()
    for name in ("run_container", "stop_container", "container_pid",
                 "container_exists", "container_logs"):
        monkeypatch.setattr("llmbench.backends.vllm.docker_backend." + name, getattr(fake, name))
    monkeypatch.setattr(
        "llmbench.backends.vllm.backend_setup.ensure_backend",
        lambda *_a, **_k: {"image": IMAGE},
    )
    monkeypatch.setattr("llmbench.backends.vllm.wait_health", lambda *_a, **_k: 1.5)
    return fake


def _backend(**kwargs):
    endpoint_cfg = kwargs.pop("endpoint_cfg", {"base_url": "http://127.0.0.1:8000", "context_size": 32768})
    return VllmBackend(IMAGE, endpoint_cfg=endpoint_cfg, **kwargs)


# ------------------------------------------------------------- begin_profile


def test_begin_profile_starts_container_with_serve_args(docker, tmp_path: Path):
    backend = _backend()
    backend.begin_profile("/models/Mistral-7B", {"name": "vLLM", "gpu_layers": -1}, {}, tmp_path)

    assert len(docker.runs) == 1
    run = docker.runs[0]
    assert run["image"] == IMAGE
    assert run["name"] == "llmbench-vllm"
    assert run["gpu"] is True

    args = run["args"]
    # Das Elternverzeichnis wird eingehaengt, der Modellname bleibt erhalten -
    # das stimmt sowohl fuer eine Modelldatei als auch fuer ein Modellverzeichnis.
    assert args[:2] == ["--model", f"{MODEL_MOUNT}/Mistral-7B"]
    # Der Host-Quellpfad wird ueber Path(...).resolve() aufgeloest, das liefert
    # unter Windows einen Laufwerkspfad (z. B. "D:\\models") statt "/models" -
    # deshalb hier denselben Aufloesungsschritt verwenden statt ihn zu raten.
    expected_source = str(Path("/models/Mistral-7B").parent.resolve())
    assert run["volumes"][expected_source] == f"{MODEL_MOUNT}:ro"
    assert args[args.index("--host") + 1] == "0.0.0.0"
    assert args[args.index("--port") + 1] == str(CONTAINER_PORT)
    assert args[args.index("--max-model-len") + 1] == "32768"
    assert backend.container_id == "CONTAINERID"


def test_begin_profile_passes_profile_fields(docker, tmp_path: Path):
    backend = _backend()
    backend.begin_profile(
        "/models/M",
        {
            "name": "vLLM-2GPU",
            "tensor_parallel_size": 2,
            "quantization": "awq",
            "gpu_memory_utilization": 0.85,
            "dtype": "bfloat16",
        },
        {},
        tmp_path,
    )
    args = docker.runs[0]["args"]
    assert args[args.index("--tensor-parallel-size") + 1] == "2"
    assert args[args.index("--quantization") + 1] == "awq"
    assert args[args.index("--gpu-memory-utilization") + 1] == "0.85"
    assert args[args.index("--dtype") + 1] == "bfloat16"


def test_begin_profile_omits_unset_profile_fields(docker, tmp_path: Path):
    """Ein llama.cpp-Profil ohne vLLM-Felder darf keine leeren Flags erzeugen."""
    backend = _backend()
    backend.begin_profile("/models/M", {"name": "Full-GPU", "gpu_layers": -1}, {}, tmp_path)
    args = docker.runs[0]["args"]
    for flag in ("--tensor-parallel-size", "--quantization", "--gpu-memory-utilization", "--dtype"):
        assert flag not in args


def test_begin_profile_publishes_port_from_base_url(docker, tmp_path: Path):
    backend = _backend(endpoint_cfg={"base_url": "http://127.0.0.1:9100", "context_size": 4096})
    backend.begin_profile("/models/M", {}, {}, tmp_path)
    assert docker.runs[0]["port_map"] == {9100: CONTAINER_PORT}


def test_begin_profile_mounts_model_directory_read_only(docker, tmp_path: Path):
    model_dir = tmp_path / "Mistral-7B"
    model_dir.mkdir()
    backend = _backend()
    backend.begin_profile(str(model_dir), {}, {}, tmp_path)

    volumes = docker.runs[0]["volumes"]
    assert volumes[str(model_dir.resolve())] == f"{MODEL_MOUNT}:ro"
    assert docker.runs[0]["args"][1] == MODEL_MOUNT


def test_begin_profile_mounts_parent_for_single_model_file(docker, tmp_path: Path):
    model_file = tmp_path / "model.gguf"
    model_file.write_bytes(b"x")
    backend = _backend()
    backend.begin_profile(str(model_file), {}, {}, tmp_path)

    volumes = docker.runs[0]["volumes"]
    assert volumes[str(tmp_path.resolve())] == f"{MODEL_MOUNT}:ro"
    assert docker.runs[0]["args"][1] == f"{MODEL_MOUNT}/model.gguf"


def test_huggingface_repo_id_is_not_mounted(docker, tmp_path: Path):
    """"org/model" ist eine Repo-Kennung, kein Verzeichnis."""
    backend = _backend()
    backend.begin_profile("mistralai/Mistral-7B-v0.1", {}, {}, tmp_path)

    run = docker.runs[0]
    assert run["args"][1] == "mistralai/Mistral-7B-v0.1"
    assert MODEL_MOUNT not in run["volumes"].values()
    # Der HF-Cache haengt trotzdem in einem benannten Volume.
    assert "llmbench-vllm-cache" in run["volumes"]


def test_begin_profile_clears_stale_container_first(docker, tmp_path: Path):
    backend = _backend()
    backend.begin_profile("/models/M", {}, {}, tmp_path)
    assert docker.stopped[0] == "llmbench-vllm"


@pytest.mark.usefixtures("docker")
def test_begin_profile_records_container_pid_for_telemetry(tmp_path: Path):
    backend = _backend()
    backend.begin_profile("/models/M", {}, {}, tmp_path)
    assert backend.target_pid == 4242


def test_begin_profile_tolerates_missing_container_pid(docker, tmp_path: Path):
    """Unter Docker Desktop gibt es keine host-sichtbare PID."""
    docker.pid = None
    backend = _backend()
    backend.begin_profile("/models/M", {}, {}, tmp_path)
    assert backend.target_pid is None


def test_begin_profile_cleans_up_and_reports_logs_on_failure(docker, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "llmbench.backends.vllm.wait_health",
        lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError("kein /health")),
    )
    backend = _backend()
    with pytest.raises(RuntimeError, match="nicht bereit"):
        backend.begin_profile("/models/M", {}, {}, tmp_path)

    assert backend.container_id is None
    assert docker.stopped.count("llmbench-vllm") >= 2  # vorher und beim Aufraeumen
    assert (tmp_path / "vllm-server.log").exists()


# -------------------------------------------------------------- run_benchmark


@pytest.mark.usefixtures("docker")
def test_run_benchmark_delegates_to_run_http_bench(tmp_path: Path, monkeypatch):
    captured = {}

    def _fake(base_url, headers, bench_cfg, profile, kind, out_dir, _on_progress=None, **kwargs):
        captured.update({
            "base_url": base_url, "headers": headers, "bench_cfg": bench_cfg,
            "profile": profile, "kind": kind, "out_dir": out_dir, **kwargs,
        })
        return {"status": "ok", "kind": kind}

    monkeypatch.setattr("llmbench.backends.vllm.run_http_bench", _fake)

    backend = _backend()
    backend.begin_profile("/models/M", {"name": "vLLM"}, {}, tmp_path)
    result = backend.run_benchmark("/models/M", {"name": "vLLM"}, "prompt", tmp_path, {"repetitions": 2})

    assert result == {"status": "ok", "kind": "prompt"}
    assert captured["base_url"] == "http://127.0.0.1:8000"
    assert captured["kind"] == "prompt"
    assert captured["backend_name"] == "vllm"
    assert captured["target_pid"] == 4242


@pytest.mark.usefixtures("docker")
def test_run_benchmark_without_running_container_fails_clearly(tmp_path: Path):
    backend = _backend()
    result = backend.run_benchmark("/models/M", {}, "prompt", tmp_path, {})
    assert result["status"] == "failed"
    assert "begin_profile" in result["error"]


@pytest.mark.usefixtures("docker")
def test_run_benchmark_forwards_api_key_header(tmp_path: Path, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "llmbench.backends.vllm.run_http_bench",
        lambda _u, headers, *_a, **_k: captured.setdefault("headers", headers) or {"status": "ok"},
    )
    backend = _backend(endpoint_cfg={"base_url": "http://127.0.0.1:8000", "api_key": "tok"})
    backend.begin_profile("/models/M", {}, {}, tmp_path)
    backend.run_benchmark("/models/M", {}, "prompt", tmp_path, {})
    assert captured["headers"] == {"Authorization": "Bearer tok"}


# ---------------------------------------------------------------- end_profile


def test_end_profile_stops_container(docker, tmp_path: Path):
    backend = _backend()
    backend.begin_profile("/models/M", {}, {}, tmp_path)
    docker.stopped.clear()
    backend.end_profile()

    assert docker.stopped == ["llmbench-vllm"]
    assert backend.container_id is None
    assert backend.target_pid is None


def test_end_profile_without_container_is_noop(docker):
    backend = _backend()
    backend.end_profile()
    assert docker.stopped == []


@pytest.mark.usefixtures("docker")
def test_end_profile_writes_container_log(tmp_path: Path):
    backend = _backend()
    backend.begin_profile("/models/M", {}, {}, tmp_path)
    backend.end_profile()
    assert (tmp_path / "vllm-server.log").read_text(encoding="utf-8") == "server log"


# --------------------------------------------------------- Endpoint-Lasttest


def test_start_server_reuses_container_start_path(docker, tmp_path: Path):
    backend = _backend()
    proc, command = backend.start_server(
        "/models/M", {"name": "vLLM"},
        {"base_url": "http://127.0.0.1:8000", "context_size": 8192},
        {}, tmp_path / "vllm.log",
    )
    assert proc.name == "llmbench-vllm"
    assert proc.pid == 4242
    assert "--model" in command
    assert docker.runs[0]["args"][docker.runs[0]["args"].index("--max-model-len") + 1] == "8192"


@pytest.mark.usefixtures("docker")
def test_start_server_redacts_api_key_in_printable_command(tmp_path: Path):
    backend = _backend()
    _proc, command = backend.start_server(
        "/models/M", {},
        {"base_url": "http://127.0.0.1:8000", "api_key": "topsecret"},
        {}, tmp_path / "vllm.log",
    )
    assert "topsecret" not in command
    assert "***" in command


def test_stop_server_removes_container(docker, tmp_path: Path):
    backend = _backend()
    proc, _ = backend.start_server("/models/M", {}, {}, {}, tmp_path / "vllm.log")
    docker.stopped.clear()
    backend.stop_server(proc)
    assert docker.stopped == ["llmbench-vllm"]


@pytest.mark.usefixtures("docker")
def test_wait_health_delegates_to_endpoint_wait_health():
    backend = _backend()
    assert backend.wait_health("http://x", 5.0) == 1.5


def test_additional_args_are_passed_through(docker, tmp_path: Path):
    backend = _backend()
    backend.begin_profile(
        "/models/M", {"additional_args": ["--enforce-eager", "--seed", "1"]}, {}, tmp_path
    )
    args = docker.runs[0]["args"]
    assert args[-3:] == ["--enforce-eager", "--seed", "1"]


# -------------------------------------------------------------------- Factory


def test_get_backend_returns_vllm_for_configured_backend(tmp_path: Path):
    cfg = {
        "tools": {"backend": "vllm", "vllm_image": "vllm/vllm-openai:v0.6.0",
                  "llama_bench": "llama-bench", "llama_server": "llama-server"},
        "endpoint": {"base_url": "http://127.0.0.1:8000"},
        "_config_dir": str(tmp_path),
    }
    backend = get_backend(cfg)
    assert isinstance(backend, VllmBackend)
    assert backend.image == "vllm/vllm-openai:v0.6.0"
    assert backend.root == tmp_path
