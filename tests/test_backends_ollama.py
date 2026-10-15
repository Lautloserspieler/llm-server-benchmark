"""OllamaBackend gegen gemockte docker_backend-Funktionen. Kein echtes Docker."""

from pathlib import Path

import pytest

from llmbench.backends import get_backend
from llmbench.backends.ollama import CONTAINER_PORT, DEFAULT_HOST_PORT, OLLAMA_DATA_MOUNT, OllamaBackend

IMAGE = "ollama/ollama:latest"


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
        monkeypatch.setattr("llmbench.backends.ollama.docker_backend." + name, getattr(fake, name))
    monkeypatch.setattr(
        "llmbench.backends.ollama.backend_setup.ensure_backend",
        lambda *_a, **_k: {"image": IMAGE},
    )
    monkeypatch.setattr("llmbench.backends.ollama.wait_health", lambda *_a, **_k: 1.5)
    # Modellvorbereitung per API unterdruecken; sie wird separat getestet.
    monkeypatch.setattr("llmbench.backends.ollama.OllamaBackend._create_model", lambda _s, _p: None)
    monkeypatch.setattr("llmbench.backends.ollama.OllamaBackend._ensure_registry_model", lambda _s, _m: None)
    return fake


def _backend(**kwargs):
    endpoint_cfg = kwargs.pop("endpoint_cfg", {"base_url": f"http://127.0.0.1:{DEFAULT_HOST_PORT}"})
    return OllamaBackend(IMAGE, endpoint_cfg=endpoint_cfg, **kwargs)


# ------------------------------------------------------------- begin_profile


def test_begin_profile_starts_container_with_empty_args(docker, tmp_path: Path):
    backend = _backend()
    backend.begin_profile("llmbench-model", {"name": "Ollama"}, {}, tmp_path)

    assert len(docker.runs) == 1
    run = docker.runs[0]
    assert run["image"] == IMAGE
    assert run["name"] == "llmbench-ollama"
    assert run["gpu"] is True
    assert run["args"] == []
    assert run["port_map"] == {DEFAULT_HOST_PORT: CONTAINER_PORT}
    assert backend.container_id == "CONTAINERID"


def test_begin_profile_cpu_profile_does_not_request_nvidia_runtime(docker, tmp_path: Path):
    backend = _backend()
    backend.begin_profile("mistral", {"name": "CPU", "gpu_layers": 0}, {}, tmp_path)
    assert docker.runs[0]["gpu"] is False


def test_begin_profile_explicit_num_gpu_zero_uses_cpu(docker, tmp_path: Path):
    backend = _backend()
    backend.begin_profile(
        "mistral",
        {"name": "CPU", "gpu_layers": -1, "ollama_num_gpu": 0},
        {},
        tmp_path,
    )
    assert docker.runs[0]["gpu"] is False


def test_begin_profile_prepares_local_gguf_via_api(docker, tmp_path: Path, monkeypatch):
    create_calls: list[str] = []
    monkeypatch.setattr(
        "llmbench.backends.ollama.OllamaBackend._create_model",
        lambda _self, model_path: create_calls.append(model_path),
    )

    model_file = tmp_path / "model.gguf"
    model_file.write_bytes(b"gguf")
    backend = _backend()
    backend.begin_profile(str(model_file), {"name": "Ollama"}, {}, tmp_path)

    run = docker.runs[0]
    assert run["args"] == []
    assert run["volumes"]["llmbench-ollama-cache"] == OLLAMA_DATA_MOUNT
    assert backend._created_model == "llmbench-model"
    assert create_calls == [str(model_file)]
    assert not (tmp_path / "Modelfile").exists()


def test_begin_profile_uses_existing_ollama_model_name(docker, tmp_path: Path):
    backend = _backend()
    backend.begin_profile("mistral:latest", {"name": "Ollama"}, {}, tmp_path)

    run = docker.runs[0]
    assert run["args"] == []
    assert run["volumes"]["llmbench-ollama-cache"] == OLLAMA_DATA_MOUNT
    assert backend._model_for_request("mistral:latest") == "mistral:latest"


def test_begin_profile_publishes_port_from_base_url(docker, tmp_path: Path):
    backend = _backend(endpoint_cfg={"base_url": "http://127.0.0.1:9100"})
    backend.begin_profile("mistral", {}, {}, tmp_path)
    assert docker.runs[0]["port_map"] == {9100: CONTAINER_PORT}


def test_begin_profile_clears_stale_container_first(docker, tmp_path: Path):
    backend = _backend()
    backend.begin_profile("mistral", {}, {}, tmp_path)
    assert docker.stopped[0] == "llmbench-ollama"


@pytest.mark.usefixtures("docker")
def test_begin_profile_records_container_pid_for_telemetry(tmp_path: Path):
    backend = _backend()
    backend.begin_profile("mistral", {}, {}, tmp_path)
    assert backend.target_pid == 4242


def test_begin_profile_tolerates_missing_container_pid(docker, tmp_path: Path):
    """Unter Docker Desktop gibt es keine host-sichtbare PID."""
    docker.pid = None
    backend = _backend()
    backend.begin_profile("mistral", {}, {}, tmp_path)
    assert backend.target_pid is None


def test_begin_profile_cleans_up_and_reports_logs_on_failure(docker, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "llmbench.backends.ollama.wait_health",
        lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError("kein /api/tags")),
    )
    backend = _backend()
    with pytest.raises(RuntimeError, match="nicht bereit"):
        backend.begin_profile("mistral", {}, {}, tmp_path)

    assert backend.container_id is None
    assert docker.stopped.count("llmbench-ollama") >= 2  # vorher und beim Aufraeumen
    assert (tmp_path / "ollama-server.log").exists()


# --------------------------------------------------------- Model preparation


class _ApiResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_create_model_uploads_gguf_blob_and_uses_current_api(tmp_path: Path, monkeypatch):
    model_file = tmp_path / "model.gguf"
    model_file.write_bytes(b"gguf-bytes")
    calls: list[dict] = []

    class Client:
        def __init__(self, *args, **kwargs):  # noqa: ARG002
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def head(self, url, **kwargs):  # noqa: ARG002
            calls.append({"method": "HEAD", "url": url})
            return _ApiResponse(404)

        def post(self, url, **kwargs):
            content = kwargs.get("content")
            body = b"".join(content) if content is not None else None
            calls.append({
                "method": "POST",
                "url": url,
                "json": kwargs.get("json"),
                "body": body,
                "headers": kwargs.get("headers"),
            })
            return _ApiResponse(201 if "/api/blobs/" in url else 200)

    monkeypatch.setattr("llmbench.backends.ollama.httpx.Client", Client)
    backend = _backend()
    backend._created_model = "llmbench-model"
    backend._create_model(str(model_file))

    upload = next(call for call in calls if call["method"] == "POST" and "/api/blobs/" in call["url"])
    assert upload["body"] == b"gguf-bytes"
    assert upload["headers"]["Content-Length"] == str(len(b"gguf-bytes"))

    create = next(call for call in calls if call["url"].endswith("/api/create"))
    payload = create["json"]
    assert payload["model"] == "llmbench-model"
    assert payload["stream"] is False
    assert set(payload["files"]) == {"model.gguf"}
    assert payload["files"]["model.gguf"].startswith("sha256:")
    assert "name" not in payload
    assert "modelfile" not in payload


def test_create_model_propagates_create_failure(tmp_path: Path, monkeypatch):
    model_file = tmp_path / "model.gguf"
    model_file.write_bytes(b"gguf")

    class Client:
        def __init__(self, *args, **kwargs):  # noqa: ARG002
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def head(self, *_args, **_kwargs):
            return _ApiResponse(200)

        def post(self, url, **kwargs):  # noqa: ARG002
            return _ApiResponse(500 if url.endswith("/api/create") else 201)

    monkeypatch.setattr("llmbench.backends.ollama.httpx.Client", Client)
    backend = _backend()
    backend._created_model = "llmbench-model"

    with pytest.raises(RuntimeError, match="HTTP 500"):
        backend._create_model(str(model_file))


def test_missing_registry_model_is_pulled_with_current_model_field(monkeypatch):
    calls: list[dict] = []

    class Client:
        def __init__(self, *args, **kwargs):  # noqa: ARG002
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, **kwargs):
            calls.append({"url": url, "json": kwargs.get("json")})
            pulled = any(c["url"].endswith("/api/pull") for c in calls)
            return _ApiResponse(404 if url.endswith("/api/show") and not pulled else 200)

    monkeypatch.setattr("llmbench.backends.ollama.httpx.Client", Client)
    backend = _backend()
    backend._ensure_registry_model("mistral:latest")

    pull = next(call for call in calls if call["url"].endswith("/api/pull"))
    assert pull["json"] == {"model": "mistral:latest", "stream": False}


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

    monkeypatch.setattr("llmbench.backends.ollama.run_http_bench", _fake)

    backend = _backend()
    backend.begin_profile("mistral", {"name": "Ollama"}, {}, tmp_path)
    result = backend.run_benchmark("mistral", {"name": "Ollama"}, "prompt", tmp_path, {"repetitions": 2})

    assert result == {"status": "ok", "kind": "prompt"}
    assert captured["base_url"] == f"http://127.0.0.1:{DEFAULT_HOST_PORT}"
    assert captured["kind"] == "prompt"
    assert captured["backend_name"] == "ollama"
    assert captured["target_pid"] == 4242
    assert captured["api_style"] == "ollama_native"


@pytest.mark.usefixtures("docker")
def test_run_benchmark_passes_ollama_profile_options(tmp_path: Path, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "llmbench.backends.ollama.run_http_bench",
        lambda _u, _h, bench_cfg, *_a, **_k: captured.setdefault("bench_cfg", bench_cfg) or {"status": "ok"},
    )
    backend = _backend()
    profile = {"name": "Ollama", "ollama_num_ctx": 16384, "ollama_num_gpu": 24}
    backend.begin_profile("mistral", profile, {}, tmp_path)
    backend.run_benchmark("mistral", profile, "generation", tmp_path, {})
    assert captured["bench_cfg"]["ollama_num_ctx"] == 16384
    assert captured["bench_cfg"]["ollama_num_gpu"] == 24


@pytest.mark.usefixtures("docker")
def test_run_benchmark_injects_model_for_gguf(tmp_path: Path, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "llmbench.backends.ollama.run_http_bench",
        lambda _u, _h, bench_cfg, *_a, **_k: captured.setdefault("bench_cfg", bench_cfg) or {"status": "ok"},
    )

    model_file = tmp_path / "model.gguf"
    model_file.write_bytes(b"gguf")
    backend = _backend()
    backend.begin_profile(str(model_file), {}, {}, tmp_path)
    backend.run_benchmark(str(model_file), {}, "prompt", tmp_path, {})

    assert captured["bench_cfg"]["model"] == "llmbench-model"


@pytest.mark.usefixtures("docker")
def test_run_benchmark_without_running_container_fails_clearly(tmp_path: Path):
    backend = _backend()
    result = backend.run_benchmark("mistral", {}, "prompt", tmp_path, {})
    assert result["status"] == "failed"
    assert "Ollama-Container" in result["error"]


@pytest.mark.usefixtures("docker")
def test_run_benchmark_forwards_api_key_header(tmp_path: Path, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "llmbench.backends.ollama.run_http_bench",
        lambda _u, headers, *_a, **_k: captured.setdefault("headers", headers) or {"status": "ok"},
    )
    backend = _backend(endpoint_cfg={"base_url": f"http://127.0.0.1:{DEFAULT_HOST_PORT}", "api_key": "tok"})
    backend.begin_profile("mistral", {}, {}, tmp_path)
    backend.run_benchmark("mistral", {}, "prompt", tmp_path, {})
    assert captured["headers"] == {"Authorization": "Bearer tok"}


# ---------------------------------------------------------------- end_profile


def test_end_profile_stops_container(docker, tmp_path: Path):
    backend = _backend()
    backend.begin_profile("mistral", {}, {}, tmp_path)
    docker.stopped.clear()
    backend.end_profile()

    assert docker.stopped == ["llmbench-ollama"]
    assert backend.container_id is None
    assert backend.target_pid is None


def test_end_profile_without_container_is_noop(docker):
    backend = _backend()
    backend.end_profile()
    assert docker.stopped == []


@pytest.mark.usefixtures("docker")
def test_end_profile_writes_container_log(tmp_path: Path):
    backend = _backend()
    backend.begin_profile("mistral", {}, {}, tmp_path)
    backend.end_profile()
    assert (tmp_path / "ollama-server.log").read_text(encoding="utf-8") == "server log"


# --------------------------------------------------------- Endpoint-Lasttest


def test_prepare_endpoint_config_selects_ollama_native():
    backend = _backend()
    cfg = backend.prepare_endpoint_config({"base_url": f"http://127.0.0.1:{DEFAULT_HOST_PORT}"})
    assert cfg["api_style"] == "ollama_native"


def test_start_server_reuses_container_start_path(docker, tmp_path: Path):
    backend = _backend()
    proc, command = backend.start_server(
        "mistral", {"name": "Ollama"},
        {"base_url": f"http://127.0.0.1:{DEFAULT_HOST_PORT}"},
        {}, tmp_path / "ollama.log",
    )
    assert proc.name == "llmbench-ollama"
    assert proc.pid == 4242
    assert "docker run" in command
    assert docker.runs[0]["port_map"] == {DEFAULT_HOST_PORT: CONTAINER_PORT}


@pytest.mark.usefixtures("docker")
def test_start_server_sets_model_in_endpoint_cfg(tmp_path: Path):
    backend = _backend()
    endpoint_cfg = {"base_url": f"http://127.0.0.1:{DEFAULT_HOST_PORT}"}
    backend.start_server("mistral", {}, endpoint_cfg, {}, tmp_path / "ollama.log")
    assert endpoint_cfg["model"] == "mistral"


@pytest.mark.usefixtures("docker")
def test_start_server_sets_ollama_profile_options_in_endpoint_cfg(tmp_path: Path):
    backend = _backend()
    endpoint_cfg = {"base_url": f"http://127.0.0.1:{DEFAULT_HOST_PORT}"}
    backend.start_server(
        "mistral",
        {"ollama_num_ctx": 8192, "ollama_num_gpu": 0, "gpu_layers": 0},
        endpoint_cfg,
        {},
        tmp_path / "ollama.log",
    )
    assert endpoint_cfg["ollama_num_ctx"] == 8192
    assert endpoint_cfg["ollama_num_gpu"] == 0


@pytest.mark.usefixtures("docker")
def test_start_server_does_not_leak_api_key_in_command(tmp_path: Path):
    backend = _backend()
    _proc, command = backend.start_server(
        "mistral", {},
        {"base_url": f"http://127.0.0.1:{DEFAULT_HOST_PORT}", "api_key": "topsecret"},
        {}, tmp_path / "ollama.log",
    )
    assert "topsecret" not in command


def test_stop_server_removes_container(docker, tmp_path: Path):
    backend = _backend()
    proc, _ = backend.start_server("mistral", {}, {}, {}, tmp_path / "ollama.log")
    docker.stopped.clear()
    backend.stop_server(proc)
    assert docker.stopped == ["llmbench-ollama"]


@pytest.mark.usefixtures("docker")
def test_wait_health_delegates_to_endpoint_wait_health():
    backend = _backend()
    assert backend.wait_health("http://x", 5.0) == 1.5


# -------------------------------------------------------------------- Factory


def test_get_backend_returns_ollama_for_configured_backend(tmp_path: Path):
    cfg = {
        "tools": {"backend": "ollama", "ollama_image": IMAGE,
                  "llama_bench": "llama-bench", "llama_server": "llama-server"},
        "endpoint": {"base_url": f"http://127.0.0.1:{DEFAULT_HOST_PORT}"},
        "_config_dir": str(tmp_path),
    }
    backend = get_backend(cfg)
    assert isinstance(backend, OllamaBackend)
    assert backend.image == IMAGE
    assert backend.root == tmp_path


def test_failed_pull_reports_ollama_error_text(monkeypatch):
    class _Failing:
        status_code = 500
        text = ""

        def json(self):
            return {"error": "pull model manifest: file does not exist"}

    class Client:
        def __init__(self, *args, **kwargs):  # noqa: ARG002
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, **kwargs):  # noqa: ARG002
            return _Failing() if url.endswith("/api/pull") else _ApiResponse(404)

    monkeypatch.setattr("llmbench.backends.ollama.httpx.Client", Client)
    with pytest.raises(RuntimeError, match="file does not exist"):
        _backend()._ensure_registry_model("nope:1b")


def test_residency_warning_when_gpu_profile_spills_to_cpu(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"name": "big:70b", "size": 100, "size_vram": 60, "context_length": 4096}]}

    monkeypatch.setattr("llmbench.backends.ollama.httpx.get", lambda *_a, **_k: _Resp())
    result: dict = {"status": "ok"}
    _backend()._attach_residency(result, "big:70b", {"gpu_layers": -1})
    assert result["ollama_residency"]["size_vram_bytes"] == 60
    assert any("60 %" in w for w in result["partial_errors"])

    cpu: dict = {"status": "ok"}
    _backend()._attach_residency(cpu, "big:70b", {"gpu_layers": 0})
    assert "partial_errors" not in cpu
