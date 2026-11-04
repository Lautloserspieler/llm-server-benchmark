"""TgiBackend gegen gemockte docker_backend-Funktionen. Kein echtes Docker."""

from pathlib import Path

import pytest

from llmbench.backends import get_backend
from llmbench.backends.tgi import CONTAINER_PORT, MODEL_MOUNT, TgiBackend

IMAGE = "ghcr.io/huggingface/text-generation-inference:latest"


@pytest.fixture
def docker(monkeypatch):
    """Ersetzt den Container-Lebenszyklus und protokolliert die Aufrufe."""

    class _Fake:
        def __init__(self):
            self.runs: list[dict] = []
            self.stopped: list[str] = []
            self.pid: int | None = 4242
            self.existing = False
            self.running: set[str] = set()
            self.logs = "server log"

        def run_container(self, name, image, args, **kwargs):
            self.runs.append({"name": name, "image": image, "args": list(args), **kwargs})
            self.running.add(name)
            return "CONTAINERID"

        def stop_container(self, name, log=None):  # noqa: ARG002
            self.stopped.append(name)
            self.running.discard(name)

        def container_pid(self, _name):
            return self.pid

        def container_exists(self, _name):
            return self.existing

        def container_logs(self, _name, tail=None):  # noqa: ARG002
            return self.logs

    fake = _Fake()
    for name in ("run_container", "stop_container", "container_pid",
                 "container_exists", "container_logs"):
        monkeypatch.setattr("llmbench.backends.tgi.docker_backend." + name, getattr(fake, name))
    monkeypatch.setattr(
        "llmbench.backends.tgi.backend_setup.ensure_backend",
        lambda *_a, **_k: {"image": IMAGE},
    )
    monkeypatch.setattr("llmbench.backends.tgi.wait_health", lambda *_a, **_k: 1.5)
    return fake


def _backend(**kwargs):
    endpoint_cfg = kwargs.pop("endpoint_cfg", {"base_url": "http://127.0.0.1:8080", "context_size": 32768})
    return TgiBackend(IMAGE, endpoint_cfg=endpoint_cfg, **kwargs)


# ------------------------------------------------------------- begin_profile


def test_begin_profile_starts_container_with_serve_args(docker, tmp_path: Path):
    model_dir = tmp_path / "Mistral-7B"
    model_dir.mkdir()
    backend = _backend()
    backend.begin_profile(str(model_dir), {"name": "TGI"}, {}, tmp_path)

    assert len(docker.runs) == 1
    run = docker.runs[0]
    assert run["image"] == IMAGE
    assert run["name"] == "llmbench-tgi"
    assert run["gpu"] is True

    args = run["args"]
    assert args[:2] == ["--model-id", MODEL_MOUNT]
    expected_source = str(model_dir.resolve())
    assert run["volumes"][expected_source] == f"{MODEL_MOUNT}:ro"
    assert args[args.index("--hostname") + 1] == "0.0.0.0"
    assert args[args.index("--port") + 1] == str(CONTAINER_PORT)
    assert args[args.index("--max-total-tokens") + 1] == "32768"
    assert backend.container_id == "CONTAINERID"


def test_begin_profile_passes_profile_fields(docker, tmp_path: Path):
    backend = _backend()
    backend.begin_profile(
        "org/M",
        {
            "name": "TGI-2GPU",
            "tensor_parallel_size": 2,
            "quantization": "awq",
            "dtype": "bfloat16",
            "max_input_length": 8192,
            "max_total_tokens": 32768,
        },
        {},
        tmp_path,
    )
    args = docker.runs[0]["args"]
    assert args[args.index("--num-shard") + 1] == "2"
    assert args[args.index("--quantize") + 1] == "awq"
    assert args[args.index("--dtype") + 1] == "bfloat16"
    assert args[args.index("--max-input-tokens") + 1] == "8192"
    assert args[args.index("--max-total-tokens") + 1] == "32768"


def test_begin_profile_omits_unset_profile_fields(docker, tmp_path: Path):
    """Ein llama.cpp-Profil ohne TGI-Felder darf keine leeren Flags erzeugen."""
    backend = _backend(endpoint_cfg={"base_url": "http://127.0.0.1:8080"})
    backend.begin_profile("org/M", {"name": "Full-GPU"}, {}, tmp_path)
    args = docker.runs[0]["args"]
    for flag in ("--num-shard", "--quantize", "--dtype", "--max-input-tokens", "--max-total-tokens"):
        assert flag not in args


def test_context_size_maps_to_max_total_tokens(docker, tmp_path: Path):
    backend = _backend(endpoint_cfg={"base_url": "http://127.0.0.1:8080", "context_size": 16384})
    backend.begin_profile("org/M", {"name": "TGI"}, {}, tmp_path)
    args = docker.runs[0]["args"]
    assert args[args.index("--max-total-tokens") + 1] == "16384"


def test_profile_max_input_length_overrides_context_size(docker, tmp_path: Path):
    backend = _backend(endpoint_cfg={"base_url": "http://127.0.0.1:8080", "context_size": 16384})
    backend.begin_profile("org/M", {"name": "TGI", "max_input_length": 4096}, {}, tmp_path)
    args = docker.runs[0]["args"]
    assert args[args.index("--max-input-tokens") + 1] == "4096"


def test_begin_profile_publishes_port_from_base_url(docker, tmp_path: Path):
    backend = _backend(endpoint_cfg={"base_url": "http://127.0.0.1:9100", "context_size": 4096})
    backend.begin_profile("org/M", {}, {}, tmp_path)
    assert docker.runs[0]["port_map"] == {9100: CONTAINER_PORT}


def test_begin_profile_mounts_model_directory_read_only(docker, tmp_path: Path):
    model_dir = tmp_path / "Mistral-7B"
    model_dir.mkdir()
    backend = _backend()
    backend.begin_profile(str(model_dir), {}, {}, tmp_path)

    volumes = docker.runs[0]["volumes"]
    assert volumes[str(model_dir.resolve())] == f"{MODEL_MOUNT}:ro"
    assert docker.runs[0]["args"][1] == MODEL_MOUNT


def test_begin_profile_rejects_single_model_file(docker, tmp_path: Path):
    model_file = tmp_path / "model.gguf"
    model_file.write_bytes(b"x")
    backend = _backend()

    with pytest.raises(RuntimeError, match="Transformers-Modellverzeichnis"):
        backend.begin_profile(str(model_file), {}, {}, tmp_path)

    assert docker.runs == []


def test_huggingface_repo_id_is_not_mounted(docker, tmp_path: Path):
    """"org/model" ist eine Repo-Kennung, kein Verzeichnis."""
    backend = _backend()
    backend.begin_profile("mistralai/Mistral-7B-v0.1", {}, {}, tmp_path)

    run = docker.runs[0]
    assert run["args"][1] == "mistralai/Mistral-7B-v0.1"
    assert MODEL_MOUNT not in run["volumes"].values()
    assert "llmbench-tgi-cache" in run["volumes"]


def test_begin_profile_clears_stale_container_first(docker, tmp_path: Path):
    backend = _backend()
    backend.begin_profile("org/M", {}, {}, tmp_path)
    assert docker.stopped[0] == "llmbench-tgi"


@pytest.mark.usefixtures("docker")
def test_begin_profile_records_container_pid_for_telemetry(tmp_path: Path):
    backend = _backend()
    backend.begin_profile("org/M", {}, {}, tmp_path)
    assert backend.target_pid == 4242


def test_begin_profile_tolerates_missing_container_pid(docker, tmp_path: Path):
    """Unter Docker Desktop gibt es keine host-sichtbare PID."""
    docker.pid = None
    backend = _backend()
    backend.begin_profile("org/M", {}, {}, tmp_path)
    assert backend.target_pid is None


def test_begin_profile_cleans_up_and_reports_logs_on_failure(docker, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "llmbench.backends.tgi.wait_health",
        lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError("kein /health")),
    )
    backend = _backend()
    with pytest.raises(RuntimeError, match="nicht bereit"):
        backend.begin_profile("org/M", {}, {}, tmp_path)

    assert backend.container_id is None
    assert docker.stopped.count("llmbench-tgi") >= 2  # vorher und beim Aufraeumen
    assert (tmp_path / "tgi-server.log").exists()


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

    monkeypatch.setattr("llmbench.backends.tgi.run_http_bench", _fake)

    backend = _backend()
    backend.begin_profile("org/M", {"name": "TGI"}, {}, tmp_path)
    result = backend.run_benchmark("org/M", {"name": "TGI"}, "prompt", tmp_path, {"repetitions": 2})

    assert result == {"status": "ok", "kind": "prompt"}
    assert captured["base_url"] == "http://127.0.0.1:8080"
    assert captured["kind"] == "prompt"
    assert captured["backend_name"] == "tgi"
    assert captured["target_pid"] == 4242


@pytest.mark.usefixtures("docker")
def test_run_benchmark_without_running_container_fails_clearly(tmp_path: Path):
    backend = _backend()
    result = backend.run_benchmark("org/M", {}, "prompt", tmp_path, {})
    assert result["status"] == "failed"
    assert "TGI-Container" in result["error"]


@pytest.mark.usefixtures("docker")
def test_run_benchmark_forwards_api_key_header(tmp_path: Path, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "llmbench.backends.tgi.run_http_bench",
        lambda _u, headers, *_a, **_k: captured.setdefault("headers", headers) or {"status": "ok"},
    )
    backend = _backend(endpoint_cfg={"base_url": "http://127.0.0.1:8080", "api_key": "tok"})
    backend.begin_profile("org/M", {}, {}, tmp_path)
    backend.run_benchmark("org/M", {}, "prompt", tmp_path, {})
    assert captured["headers"] == {"Authorization": "Bearer tok"}


# ---------------------------------------------------------------- end_profile


def test_end_profile_stops_container(docker, tmp_path: Path):
    backend = _backend()
    backend.begin_profile("org/M", {}, {}, tmp_path)
    docker.stopped.clear()
    backend.end_profile()

    assert docker.stopped == ["llmbench-tgi"]
    assert backend.container_id is None
    assert backend.target_pid is None


def test_end_profile_without_container_is_noop(docker):
    backend = _backend()
    backend.end_profile()
    assert docker.stopped == []


@pytest.mark.usefixtures("docker")
def test_end_profile_writes_container_log(tmp_path: Path):
    backend = _backend()
    backend.begin_profile("org/M", {}, {}, tmp_path)
    backend.end_profile()
    assert (tmp_path / "tgi-server.log").read_text(encoding="utf-8") == "server log"


# --------------------------------------------------------- Endpoint-Lasttest


def test_prepare_endpoint_config_selects_openai_completions():
    backend = _backend()
    cfg = backend.prepare_endpoint_config({
        "base_url": "http://127.0.0.1:8080",
        "ignore_eos": True,
    })
    assert cfg["api_style"] == "openai_completions"
    assert cfg["ignore_eos"] is False


def test_start_server_reuses_container_start_path(docker, tmp_path: Path):
    backend = _backend()
    proc, command = backend.start_server(
        "org/M", {"name": "TGI"},
        {"base_url": "http://127.0.0.1:8080", "context_size": 8192},
        {}, tmp_path / "tgi.log",
    )
    assert proc.name == "llmbench-tgi"
    assert proc.pid == 4242
    assert "--model-id" in command
    assert docker.runs[0]["args"][docker.runs[0]["args"].index("--max-total-tokens") + 1] == "8192"


@pytest.mark.usefixtures("docker")
def test_start_server_does_not_leak_api_key_in_command(tmp_path: Path):
    backend = _backend()
    _proc, command = backend.start_server(
        "org/M", {},
        {"base_url": "http://127.0.0.1:8080", "api_key": "topsecret"},
        {}, tmp_path / "tgi.log",
    )
    assert "topsecret" not in command


def test_stop_server_removes_container(docker, tmp_path: Path):
    backend = _backend()
    proc, _ = backend.start_server("org/M", {}, {}, {}, tmp_path / "tgi.log")
    docker.stopped.clear()
    backend.stop_server(proc)
    assert docker.stopped == ["llmbench-tgi"]


@pytest.mark.usefixtures("docker")
def test_wait_health_delegates_to_endpoint_wait_health():
    backend = _backend()
    assert backend.wait_health("http://x", 5.0) == 1.5


def test_additional_args_are_passed_through(docker, tmp_path: Path):
    backend = _backend()
    backend.begin_profile(
        "org/M", {"additional_args": ["--sharded", "--trust-remote-code"]}, {}, tmp_path
    )
    args = docker.runs[0]["args"]
    assert args[args.index("--sharded"):] == ["--sharded", "--trust-remote-code"]


# -------------------------------------------------------------------- Factory


def test_get_backend_returns_tgi_for_configured_backend(tmp_path: Path):
    cfg = {
        "tools": {"backend": "tgi", "tgi_image": IMAGE,
                  "llama_bench": "llama-bench", "llama_server": "llama-server"},
        "endpoint": {"base_url": "http://127.0.0.1:8080"},
        "_config_dir": str(tmp_path),
    }
    backend = get_backend(cfg)
    assert isinstance(backend, TgiBackend)
    assert backend.image == IMAGE
    assert backend.root == tmp_path


def test_smoke_resource_limits_reach_docker(docker, tmp_path):
    backend = _backend()
    backend.start_server("Qwen/Qwen2.5-0.5B-Instruct", {
        "container_memory_gib": 12, "compilation_jobs": 1, "tgi_attention": "torch",
    }, {}, {}, tmp_path / "tgi.log")
    call = docker.runs[0]
    assert call["extra_args"][-4:] == ["--memory", "12g", "--memory-swap", "12g"]
    assert call["env"]["MAX_JOBS"] == "1"
    assert call["env"]["ATTENTION"] == "paged"
    assert call["env"]["PREFIX_CACHING"] == "0"
    assert call["env"]["PREFILL_CHUNKING"] == "0"
    assert call["env"]["USE_FLASH_ATTENTION"] == "false"


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_container_memory_is_rejected(docker, tmp_path, value):
    backend = _backend()
    with pytest.raises(ValueError, match="container_memory_gib"):
        backend.start_server("model", {"container_memory_gib": value}, {}, {}, tmp_path / "tgi.log")
    assert not docker.runs
    assert not docker.stopped


# ------------------------------- Haertung v1.7 (Issue #120): Zyklen & Fehlertaxonomie


def test_ten_start_stop_cycles_leave_no_owned_container(docker, tmp_path: Path):
    backend = _backend()
    for _cycle in range(10):
        backend.begin_profile("org/M", {}, {}, tmp_path)
        assert docker.running == {"llmbench-tgi"}
        backend.end_profile()
        assert docker.running == set()
    assert len(docker.runs) == 10


def test_ten_endpoint_start_stop_cycles_leave_no_owned_container(docker, tmp_path: Path):
    backend = _backend()
    for _cycle in range(10):
        proc, _command = backend.start_server("org/M", {}, {"base_url": "http://127.0.0.1:8080"}, {}, tmp_path / "s.log")
        assert docker.running == {"llmbench-tgi"}
        backend.stop_server(proc)
        assert docker.running == set()


@pytest.mark.parametrize(
    ("logs", "expected"),
    [
        ("Error: RepositoryNotFound: Repository not found for url", "model_not_found"),
        ("error: invalid value 'fp3' for '--quantize <QUANTIZE>': possible values: awq, gptq", "invalid_configuration"),
        ("torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 2.00 GiB", "out_of_memory"),
        ("everything fine but never healthy", "startup_timeout"),
    ],
    ids=["missing_model", "invalid_quantization", "gpu_oom", "health_timeout"],
)
def test_startup_failures_are_classified_and_leave_no_orphan(docker, tmp_path: Path, monkeypatch, logs, expected):
    from llmbench.backends.http_probe import BackendStartupError

    docker.logs = logs
    monkeypatch.setattr(
        "llmbench.backends.tgi.wait_health",
        lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError("kein /health")),
    )
    backend = _backend()

    with pytest.raises(BackendStartupError) as raised:
        backend.begin_profile("org/M", {}, {}, tmp_path)

    assert raised.value.failure_category == expected
    assert isinstance(raised.value, RuntimeError)
    assert docker.running == set()
    assert backend.container_id is None and backend.target_pid is None


def test_container_exit_during_startup_is_classified(docker, tmp_path: Path, monkeypatch):
    from llmbench.backends.http_probe import BackendStartupError

    def exited(*_a, **_k):
        raise RuntimeError("Container llmbench-tgi wurde nicht bereit: Status=exited, Exitcode=1")

    monkeypatch.setattr("llmbench.backends.tgi.wait_health", exited)
    with pytest.raises(BackendStartupError) as raised:
        _backend().begin_profile("org/M", {}, {}, tmp_path)
    assert raised.value.failure_category == "container_exited"
    assert docker.running == set()


def test_docker_run_failure_is_classified_as_startup_failed(docker, tmp_path: Path, monkeypatch):
    from llmbench.backends.http_probe import BackendStartupError

    def fail(*_a, **_k):
        raise RuntimeError("docker: Error response from daemon: port is already allocated")

    monkeypatch.setattr("llmbench.backends.tgi.docker_backend.run_container", fail)
    with pytest.raises(BackendStartupError) as raised:
        _backend().begin_profile("org/M", {}, {}, tmp_path)
    assert raised.value.failure_category == "startup_failed"
    assert docker.running == set()


def test_sigint_during_health_wait_stops_container_and_propagates(docker, tmp_path: Path, monkeypatch):
    def interrupted(*_a, **_k):
        raise KeyboardInterrupt

    monkeypatch.setattr("llmbench.backends.tgi.wait_health", interrupted)
    backend = _backend()

    with pytest.raises(KeyboardInterrupt):
        backend.begin_profile("org/M", {}, {}, tmp_path)

    assert docker.running == set()
    assert backend.container_id is None
    assert (tmp_path / "tgi-server.log").exists()


def test_image_reference_and_launcher_arguments_are_reproducible(docker):
    from llmbench import backend_setup

    assert "@sha256:" in backend_setup.DEFAULT_TGI_IMAGE
    backend = _backend()
    _container_id, command = backend._start("org/M", {"max_total_tokens": 4096}, backend.endpoint_cfg)
    assert command.startswith(f"docker run {IMAGE} ")
    assert "--model-id org/M" in command and "--max-total-tokens 4096" in command
    assert docker.runs[0]["image"] == IMAGE


# --------------------------------------------- Branch-Haertung (Issue #123)

from types import SimpleNamespace  # noqa: E402

from llmbench.backends.tgi import _looks_like_path  # noqa: E402


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/abs/path/model", True),
        ("./relative", True),
        ("~/models/x", True),
        ("C:\\\\models\\\\x", True),
        ("a/b/c", True),
        ("org/model", False),
        ("plain-name", False),
    ],
)
def test_looks_like_path_distinguishes_local_paths_from_repo_ids(value, expected):
    assert _looks_like_path(value) is expected


def test_existing_relative_directory_counts_as_local_path(tmp_path: Path, monkeypatch):
    (tmp_path / "model").mkdir()
    monkeypatch.chdir(tmp_path)
    assert _looks_like_path("model") is True


def test_nonexistent_local_model_path_is_rejected(docker, tmp_path: Path):
    from llmbench.backends.http_probe import BackendStartupError

    with pytest.raises(BackendStartupError, match="existiert nicht") as raised:
        _backend().begin_profile(str(tmp_path / "missing" / "dir" / "model"), {}, {}, tmp_path)
    assert raised.value.failure_category == "model_not_found"
    assert docker.running == set()


@pytest.mark.parametrize(
    ("profile", "env"),
    [
        ({"tgi_attention": "flashinfer"}, {"ATTENTION": "flashinfer"}),
        ({"tgi_attention": "flashdecoding"}, {"ATTENTION": "flashdecoding"}),
        ({"tgi_attention": "paged"}, {"ATTENTION": "paged", "PREFIX_CACHING": "0", "PREFILL_CHUNKING": "0"}),
        (
            {"tgi_attention": "torch"},
            {"ATTENTION": "paged", "PREFIX_CACHING": "0", "PREFILL_CHUNKING": "0", "USE_FLASH_ATTENTION": "false"},
        ),
        ({"compilation_jobs": 4}, {"MAX_JOBS": "4"}),
    ],
)
def test_attention_modes_and_compilation_jobs_set_container_environment(docker, tmp_path: Path, profile, env):
    _backend().begin_profile("org/M", profile, {}, tmp_path)
    assert docker.runs[0]["env"] == env


@pytest.mark.parametrize(
    ("profile", "message"),
    [
        ({"tgi_attention": "bogus"}, "tgi_attention"),
        ({"compilation_jobs": 0}, "compilation_jobs"),
    ],
)
def test_invalid_environment_settings_are_rejected_before_any_container_starts(docker, profile, message):
    with pytest.raises(ValueError, match=message):
        _backend()._start("org/M", profile, {})
    assert docker.runs == [] and docker.stopped == []


def test_stop_server_saves_the_container_log(docker, tmp_path: Path):
    backend = _backend()
    log = tmp_path / "nested" / "server.log"
    proc, _command = backend.start_server("org/M", {}, {"base_url": "http://127.0.0.1:8080"}, {}, log)
    docker.logs = "final container output"
    backend.stop_server(SimpleNamespace(name=proc.name))
    assert log.read_text(encoding="utf-8") == "final container output"
    assert docker.running == set()


def test_log_capture_failure_never_blocks_cleanup(docker, tmp_path: Path, monkeypatch):
    backend = _backend()
    backend.begin_profile("org/M", {}, {}, tmp_path)

    def broken(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr("llmbench.backends.tgi.docker_backend.container_logs", broken)
    backend.end_profile()
    assert docker.running == set() and backend.container_id is None
