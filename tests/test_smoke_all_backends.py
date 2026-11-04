"""Smoke orchestration against local HTTP mocks; no Docker or model downloads."""

import copy
import importlib.util
import io
import json
import os
import socket
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from rich.console import Console


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "smoke_all_backends.py"
    spec = importlib.util.spec_from_file_location("smoke_all_backends", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def harness(tmp_path, monkeypatch):
    script = _script()
    events = []
    requests = []
    cfg = {
        "_config_dir": str(tmp_path), "tools": {}, "benchmark": {"batch_size": 99999},
        "endpoint": {"base_url": "http://127.0.0.1:18080"},
    }

    class Backend:
        container_name = "original-benchmark"

        def start_server(self, model, profile, endpoint, bench, _log):
            self.endpoint, self.bench, self.profile = endpoint, bench, profile
            events.append(("start", self.container_name))
            endpoint["model"] = model
            return SimpleNamespace(name=self.container_name), "start"

        def wait_health(self, *_args):
            events.append(("health", self.container_name))

        def prepare_endpoint_config(self, endpoint):
            style = {"llama_cpp": "llama_cpp", "ollama": "ollama_native"}.get(self.kind, "openai_completions")
            return {**endpoint, "api_style": style}

        def stop_server(self, proc):
            events.append(("stop", proc.name))

    backend = Backend()

    def handler(request):
        payload = json.loads(request.content)
        requests.append((str(request.url), payload))
        if request.url.path == "/completion":
            return httpx.Response(200, text='data: {"content": "Hallo Welt."}\n\n')
        # Both registry and OpenAI APIs require an explicit model in this mock.
        if not payload.get("model"):
            return httpx.Response(422, json={"error": "model field required"})
        if request.url.path == "/api/generate":
            return httpx.Response(200, text='{"response": "Hallo Welt.", "done": false}\n{"done": true, "eval_count": 3}\n')
        return httpx.Response(200, text='data: {"choices": [{"text": "Hallo Welt."}]}\n\ndata: [DONE]\n')

    real_client = httpx.AsyncClient

    def client(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    def get_backend(cfg):
        backend.kind = cfg["tools"]["backend"]
        return backend

    monkeypatch.setattr(script.httpx, "AsyncClient", client)
    monkeypatch.setattr(script, "_prerequisite", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(script, "_prepare_backend", lambda *_args: None)
    monkeypatch.setattr(script, "_free_port", lambda *_args: True)
    monkeypatch.setattr(script, "_case", lambda *_args: ("smoke-model", {"gpu_layers": 0}))
    monkeypatch.setattr(script, "get_backend", get_backend)
    monkeypatch.setattr(script.docker_backend, "container_logs", lambda name: events.append(("logs", name)) or "startup log")
    monkeypatch.setattr(script.docker_backend, "verify_container_removed", lambda name: events.append(("verify", name)))
    monkeypatch.setattr(script.docker_backend, "stop_container", lambda name: events.append(("fallback-stop", name)))
    return SimpleNamespace(script=script, cfg=cfg, backend=backend, events=events, requests=requests, out=tmp_path)


def test_gemma_gguf_download_uses_small_model(tmp_path, monkeypatch):
    script = _script()
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        return tmp_path / "gemma.gguf"

    monkeypatch.setattr(script, "hf_hub_download", download)
    assert script._smallest_catalog_gguf({"_config_dir": str(tmp_path)}) == str(tmp_path / "gemma.gguf")
    assert calls == [{
        "repo_id": "ggml-org/gemma-3-1b-it-GGUF",
        "filename": "gemma-3-1b-it-Q4_K_M.gguf",
        "local_dir": tmp_path / "models" / "smoke-gemma3-1b",
    }]


def test_existing_gguf_needs_no_download(tmp_path, monkeypatch):
    script = _script()
    model = tmp_path / "existing.gguf"
    model.touch()
    monkeypatch.setattr(script, "hf_hub_download", lambda **_kwargs: pytest.fail("unexpected download"))
    assert script._smallest_catalog_gguf({"_smoke_gguf": str(model)}) == str(model)
    with pytest.raises(script.MissingPrerequisite):
        script._smallest_catalog_gguf({"_smoke_gguf": str(tmp_path / "missing.gguf")})


@pytest.mark.parametrize("name", ("llama_cpp", "ollama", "vllm", "tgi"))
def test_success_uses_real_http_client_and_cleans_up(harness, name):
    h = harness
    phases = []
    row = h.script.run_one(h.cfg, name, h.out, lambda _name, phase: phases.append(phase))
    assert row["status"] == "passed"
    assert row["phase"] == "done"
    assert phases == list(h.script.PHASES)
    assert list(row["phases"]) == phases
    payload = h.requests[0][1]
    if name == "llama_cpp":
        assert h.requests[0][0].endswith("/completion")
        assert payload["n_predict"] == 16
    elif name == "ollama":
        assert h.requests[0][0].endswith("/api/generate")
        assert payload["model"] == "smoke-model"
        assert payload["options"]["num_predict"] == 16
    else:
        assert h.requests[0][0].endswith("/v1/completions")
        assert payload["model"] == "smoke-model"
        assert payload["max_tokens"] == 16
    assert sum(event == "stop" for event, _name in h.events) == 1
    if name != "llama_cpp":
        assert row["container"].startswith(f"llmbench-smoke-{name}-")
        assert all(value != "original-benchmark" for _event, value in h.events)
        assert Path(row["log"]).read_text().strip() == "startup log"
        assert h.events.index(("logs", row["container"])) < h.events.index(("stop", row["container"]))


def test_benchmark_settings_are_isolated(harness):
    h = harness
    h.cfg["endpoint"].update(chat_format=True, api_style="ollama_native", min_tokens=500,
                             server_additional_args=["--bad-flag"], ignore_eos=True)
    before = copy.deepcopy(h.cfg)
    row = h.script.run_one(h.cfg, "llama_cpp", h.out)
    assert row["status"] == "passed"
    assert h.cfg == before
    assert h.backend.endpoint["api_style"] == "llama_cpp"
    assert h.backend.endpoint["chat_format"] is False
    assert "min_tokens" not in h.backend.endpoint
    assert "server_additional_args" not in h.backend.endpoint
    assert h.backend.bench["batch_size"] == 128


@pytest.mark.parametrize("failure,detail", [(RuntimeError("generation failed"), "generation failed"),
                                           (None, "ohne Text")])
def test_generation_failure_keeps_logs_and_stops(harness, monkeypatch, failure, detail):
    h = harness

    async def generate(*_args, **_kwargs):
        if failure:
            raise failure
        return "  "

    monkeypatch.setattr(h.script, "sanity_completion_async", generate)
    row = h.script.run_one(h.cfg, "ollama", h.out)
    assert row["status"] == "failed"
    assert row["phase"] == "generation"
    assert detail in row["detail"]
    assert Path(row["log"]).read_text().strip() == "startup log"
    assert ("stop", row["container"]) in h.events


def test_partial_start_saves_logs_before_cleanup(harness, monkeypatch):
    h = harness

    def start(*_args):
        raise RuntimeError("model pull failed")

    monkeypatch.setattr(h.backend, "start_server", start)
    row = h.script.run_one(h.cfg, "ollama", h.out)
    assert row["status"] == "failed"
    assert row["phase"] == "start"
    assert "model pull failed" in row["detail"]
    assert h.events == [("logs", row["container"]), ("stop", row["container"]), ("verify", row["container"])]
    assert Path(row["log"]).read_text().strip() == "startup log"


def test_stop_cannot_overwrite_logs_captured_before_removal(harness, monkeypatch):
    h = harness

    def stop(_proc):
        (h.out / "ollama.log").write_text("later log capture failed", encoding="utf-8")

    monkeypatch.setattr(h.backend, "stop_server", stop)
    row = h.script.run_one(h.cfg, "ollama", h.out)
    assert row["status"] == "passed"
    assert Path(row["log"]).read_text().strip() == "startup log"


def test_native_start_failure_does_not_stop_a_nonexistent_process(harness, monkeypatch):
    h = harness

    def start(*_args):
        raise RuntimeError("binary failed")

    monkeypatch.setattr(h.backend, "start_server", start)
    row = h.script.run_one(h.cfg, "llama_cpp", h.out)
    assert row["cleanup_error"] is None
    assert "binary failed" in row["detail"]
    assert not h.events


def test_cleanup_failure_is_reported_even_after_success(harness, monkeypatch):
    h = harness

    def remains(_name):
        raise RuntimeError("container remains")

    monkeypatch.setattr(h.script.docker_backend, "verify_container_removed", remains)
    row = h.script.run_one(h.cfg, "tgi", h.out)
    assert row["status"] == "failed"
    assert row["phase"] == "cleanup"
    assert "container remains" in row["cleanup_error"]


def test_progress_output_failure_cannot_prevent_cleanup(harness):
    h = harness

    def broken_output(_name, _phase):
        raise BrokenPipeError("output closed")

    row = h.script.run_one(h.cfg, "ollama", h.out, on_progress=broken_output)
    assert row["status"] == "passed"
    assert ("stop", row["container"]) in h.events
    assert ("verify", row["container"]) in h.events


def test_cleanup_failure_preserves_original_error_and_retries(harness, monkeypatch):
    h = harness

    async def fail(*_args, **_kwargs):
        raise RuntimeError("generation failed")

    def fail_stop(_proc):
        raise RuntimeError("stop failed")

    monkeypatch.setattr(h.script, "sanity_completion_async", fail)
    monkeypatch.setattr(h.backend, "stop_server", fail_stop)
    row = h.script.run_one(h.cfg, "vllm", h.out)
    assert "generation failed" in row["detail"]
    assert "stop failed" in row["cleanup_error"]
    assert ("fallback-stop", row["container"]) in h.events


def test_interrupt_cleans_up_and_reports_aborted(harness, monkeypatch):
    h = harness

    def interrupt(*_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(h.backend, "wait_health", interrupt)
    row = h.script.run_one(h.cfg, "ollama", h.out)
    assert row["status"] == "aborted"
    assert row["phase"] == "health"
    assert ("stop", row["container"]) in h.events
    assert Path(row["log"]).is_file()


def test_skipped_backend_has_duration_and_never_starts(harness, monkeypatch):
    h = harness
    monkeypatch.setattr(h.script, "_prerequisite", lambda *_args, **_kwargs: "not installed")
    row = h.script.run_one(h.cfg, "tgi", h.out)
    assert row["status"] == "skipped"
    assert row["seconds"] >= 0
    assert row["log"] is None
    assert not h.events


def test_preflight_exception_becomes_failed_row(harness, monkeypatch):
    h = harness

    def fail(*_args, **_kwargs):
        raise RuntimeError("preflight failed")

    monkeypatch.setattr(h.script, "_prerequisite", fail)
    row = h.script.run_one(h.cfg, "vllm", h.out)
    assert row["status"] == "failed"
    assert row["phase"] == "prerequisites"
    assert row["seconds"] >= 0
    assert not h.events


def test_secret_not_written_to_report_details(harness, monkeypatch):
    h = harness
    h.cfg["endpoint"]["api_key"] = "secret-test-key"

    async def fail(*_args, **_kwargs):
        raise RuntimeError("Rejected secret-test-key")

    monkeypatch.setattr(h.script, "sanity_completion_async", fail)
    row = h.script.run_one(h.cfg, "llama_cpp", h.out)
    assert "secret-test-key" not in json.dumps(row)
    assert "***" in row["detail"]


def test_generation_has_total_deadline(harness, monkeypatch):
    import asyncio

    h = harness
    h.cfg["_smoke_request_timeout"] = 0.01

    async def forever(*_args, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(h.script, "sanity_completion_async", forever)
    row = h.script.run_one(h.cfg, "ollama", h.out)
    assert row["status"] == "failed"
    assert "TimeoutError" in row["detail"]
    assert ("stop", row["container"]) in h.events


@pytest.mark.parametrize("url", ["https://127.0.0.1:8080", "http://example.org:8080", "http://127.0.0.1:8080/v1",
                                 "http://user:pass@localhost:8080", "http://localhost:0", "http://localhost:99999"])
def test_local_url_rejects_incompatible_endpoints(url):
    with pytest.raises(ValueError):
        _script()._local_url(url)


@pytest.mark.parametrize("url,expected", [("http://localhost", "http://localhost:8080"),
                                          ("http://[::1]:18080/", "http://[::1]:18080")])
def test_local_url_normalizes_default_port(url, expected):
    assert _script()._local_url(url) == expected


def test_port_probe_detects_bound_but_not_listening_socket():
    script = _script()
    with socket.socket() as bound:
        bound.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{bound.getsockname()[1]}"
        assert script._free_port(url) is False
    assert script._free_port(url) is True


@pytest.mark.parametrize("local_image,state_image", [(False, "image:test"), (True, "image:old")])
def test_preflight_skips_missing_or_different_images(tmp_path, monkeypatch, local_image, state_image):
    script = _script()
    monkeypatch.setattr(script.docker_backend, "docker_available", lambda: True)
    monkeypatch.setattr(script.docker_backend, "container_exists", lambda _name: False)
    monkeypatch.setattr(script.backend_setup, "read_state", lambda *_args: {"image": state_image})
    monkeypatch.setattr(script.docker_backend, "image_exists", lambda _image: local_image)
    reason = script._prerequisite("ollama", tmp_path, "image:test")
    assert "nicht lokal installiert" in reason


def test_preflight_leaves_existing_benchmark_container_alone(tmp_path, monkeypatch):
    script = _script()
    monkeypatch.setattr(script.docker_backend, "docker_available", lambda: True)
    monkeypatch.setattr(script.backend_setup, "read_state", lambda *_args: {"image": "image:test"})
    monkeypatch.setattr(script.docker_backend, "image_exists", lambda _image: True)
    monkeypatch.setattr(script.docker_backend, "container_exists", lambda _name: True)
    assert "unberuehrt" in script._prerequisite("ollama", tmp_path, "image:test")


@pytest.mark.parametrize("statuses,strict,expected", [
    (["passed", "passed"], False, 0), (["passed", "skipped"], False, 0),
    (["passed", "skipped"], True, 1), (["skipped", "skipped"], False, 2),
    (["failed", "passed"], False, 1), (["aborted", "passed"], False, 130),
])
def test_cli_writes_incrementally_and_returns_meaningful_exit_code(tmp_path, monkeypatch, capsys, statuses, strict, expected):
    script = _script()
    report = tmp_path / "report.json"
    calls = []
    monkeypatch.setattr(script, "load_config", lambda _path: {"endpoint": {}})

    def run(_cfg, name, _out, on_progress, on_message):
        assert len(json.loads(report.read_text())) == len(calls)
        on_progress(name, "prerequisites")
        on_message(f"Testing {name}")
        status = statuses[len(calls)]
        calls.append(name)
        return {"backend": name, "status": status, "detail": "test", "phase": "test", "seconds": 1.0}

    monkeypatch.setattr(script, "run_one", run)
    args = ["--output", str(tmp_path), "--backends", "ollama", "vllm", "ollama", "--no-progress"]
    if strict:
        args.append("--strict")
    assert script.main(args) == expected
    rows = json.loads(report.read_text())
    assert len(rows) == (1 if statuses[0] == "aborted" else 2)
    assert len(calls) == len(rows)
    output = capsys.readouterr().out
    assert "1/7" in output
    assert "Bericht:" in output
    assert not report.with_suffix(".json.tmp").exists()


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
def test_cli_rejects_invalid_timeouts(value):
    with pytest.raises(SystemExit) as exc:
        _script().main(["--request-timeout", value])
    assert exc.value.code == 2


def test_progress_renders_in_terminal():
    script = _script()
    output = io.StringIO()
    console = Console(file=output, force_terminal=True, force_interactive=True, width=100,
                      _environ={"TERM": "xterm"})
    with script.SmokeProgress(console, 1) as progress:
        progress.begin("ollama")
        progress.phase("ollama", "start")
        progress.progress.refresh()
        progress.finish({"backend": "ollama", "status": "passed", "seconds": 1.0, "detail": "OK"})
    assert "Server starten" in output.getvalue()
    assert "PASSED" in output.getvalue()


def test_vllm_smoke_reserves_less_memory_without_cuda_graphs():
    script = _script()
    _model, profile = script._case({}, "vllm")
    assert profile["gpu_memory_utilization"] == 0.5
    # Reproduce the supplied 11.58 GiB GPU / 9.32 GiB free startup scenario.
    assert 11.58 * profile["gpu_memory_utilization"] < 9.32
    assert "--enforce-eager" in profile["additional_args"]
    assert "--max-num-seqs" in profile["additional_args"]
    _, custom = script._case({"_smoke_gpu_memory_utilization": 0.35}, "vllm")
    assert custom["gpu_memory_utilization"] == 0.35
    _, tgi = script._case({}, "tgi")
    assert "--enforce-eager" not in tgi["additional_args"]


def test_container_name_is_shown_before_start(harness):
    h = harness
    messages = []
    row = h.script.run_one(h.cfg, "vllm", h.out, on_message=messages.append)
    assert row["status"] == "passed"
    assert any(f"docker logs -f --tail 100 {row['container']}" in message for message in messages)


@pytest.mark.parametrize("value", ["0", "-0.1", "1.1", "nan", "inf"])
def test_cli_rejects_invalid_gpu_memory_fraction(value):
    with pytest.raises(SystemExit) as exc:
        _script().main(["--gpu-memory-utilization", value])
    assert exc.value.code == 2


@pytest.mark.parametrize("name", ["llama_cpp", "ollama"])
@pytest.mark.parametrize("available", [False, True])
def test_auto_device_prefers_available_gpu(monkeypatch, name, available):
    script = _script()
    monkeypatch.setattr(script.llama_cpp_setup, "looks_like_gpu_present", lambda: available)
    monkeypatch.setattr(script.docker_backend, "nvidia_runtime_available", lambda: available)
    if name == "llama_cpp":
        monkeypatch.setattr(script.sys, "platform", "linux")
    assert script._use_gpu({}, name) is available
    assert script._use_gpu({"_smoke_device": "cpu"}, name) is False
    if not available:
        with pytest.raises(script.MissingPrerequisite, match="GPU"):
            script._use_gpu({"_smoke_device": "gpu"}, name)


def test_ollama_gpu_profile_does_not_force_cpu(monkeypatch):
    script = _script()
    monkeypatch.setattr(script.docker_backend, "nvidia_runtime_available", lambda: True)
    _, gpu = script._case({}, "ollama")
    assert gpu["gpu_layers"] == -1
    assert "ollama_num_gpu" not in gpu
    _, cpu = script._case({"_smoke_device": "cpu"}, "ollama")
    assert cpu["gpu_layers"] == 0
    assert cpu["ollama_num_gpu"] == 0


def test_missing_docker_backend_is_prepared_automatically(tmp_path, monkeypatch):
    script = _script()
    calls = []
    monkeypatch.setattr(script.backend_setup, "ensure_backend", lambda *args, **_kwargs: calls.append(args))
    cfg = {"_config_dir": str(tmp_path), "tools": {"tgi_image": "test-tgi"}}
    script._prepare_backend(cfg, "tgi", lambda _message: None)
    assert calls == [("tgi", tmp_path, "test-tgi")]


def test_missing_native_backend_is_installed_and_paths_are_used(tmp_path, monkeypatch):
    script = _script()
    monkeypatch.setattr(script, "_use_gpu", lambda *_args: True)
    monkeypatch.setattr(script.shutil, "which", lambda _name: None)
    monkeypatch.setattr(script.llama_cpp_setup, "target_platform", lambda: ("linux", "x64"))
    monkeypatch.setattr(script.llama_cpp_setup, "_prefer_cuda_source", lambda *_args: False)
    monkeypatch.setattr(script.sys, "platform", "linux")
    monkeypatch.delenv("LLMBENCH_LLAMACPP_BUILD_BACKEND", raising=False)
    calls = []

    def install(root, **_kwargs):
        import os

        calls.append((root, os.environ.get("LLMBENCH_LLAMACPP_BUILD_BACKEND")))
        return {"backend": "vulkan"}

    monkeypatch.setattr(script.llama_cpp_setup, "ensure_llama_cpp", install)
    cfg = {"_config_dir": str(tmp_path), "tools": {"llama_server": "missing-server"}}
    script._prepare_backend(cfg, "llama_cpp", lambda _message: None)
    assert calls == [(tmp_path, "vulkan")]
    executable = "llama-server.exe" if os.name == "nt" else "llama-server"
    assert cfg["tools"]["llama_server"] == str(tmp_path / "tools" / "llama.cpp" / executable)
    assert "LLMBENCH_LLAMACPP_BUILD_BACKEND" not in script.os.environ


def test_no_install_mode_does_not_prepare_backend(harness, monkeypatch):
    h = harness
    h.cfg["_smoke_auto_install"] = False
    monkeypatch.setattr(h.script, "_prepare_backend", lambda *_args: pytest.fail("installation disabled"))
    assert h.script.run_one(h.cfg, "ollama", h.out)["status"] == "passed"


def test_install_failure_is_recorded_and_not_reported_as_skip(harness, monkeypatch):
    h = harness

    def fail(*_args):
        raise RuntimeError("image pull failed")

    monkeypatch.setattr(h.script, "_prepare_backend", fail)
    row = h.script.run_one(h.cfg, "tgi", h.out)
    assert row["status"] == "failed"
    assert row["phase"] == "setup"
    assert "image pull failed" in row["detail"]
    assert not h.events


def test_occupied_default_port_is_replaced_automatically():
    script = _script()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        busy = f"http://127.0.0.1:{listener.getsockname()[1]}"
        available = script._available_url(busy)
        assert available != busy
        assert script._free_port(available)
        with pytest.raises(RuntimeError, match="Port belegt"):
            script._available_url(busy, fixed=True)


@pytest.mark.skipif(os.name == "nt", reason="POSIX SO_REUSEADDR semantics; Windows uses exclusive binds")
def test_port_probe_allows_restart_after_closed_connection():
    script = _script()
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port)) as client:
            peer, _addr = listener.accept()
            peer.close()
            assert client.recv(1) == b""
    assert script._free_port(f"http://127.0.0.1:{port}")


@pytest.mark.parametrize("devices,expected", [
    ("Available devices:\n  Vulkan0: NVIDIA RTX 5070\n", True),
    ("Available devices:\n  CUDA0: NVIDIA\n", True),
    ("Available devices:\n", False),
])
def test_native_gpu_probe_requires_an_actual_device(monkeypatch, devices, expected):
    script = _script()
    monkeypatch.setattr(script.subprocess, "run", lambda *_a, **_k: SimpleNamespace(returncode=0, stdout=devices, stderr=""))
    assert script._llama_gpu_available(Path("server")) is expected


def test_existing_cpu_binary_is_replaced_by_gpu_setup(tmp_path, monkeypatch):
    script = _script()
    server = tmp_path / "cpu-server"
    server.touch()
    server.chmod(0o755)
    monkeypatch.setattr(script, "_use_gpu", lambda *_args: True)
    monkeypatch.setattr(script, "_llama_gpu_available", lambda *_args: False)
    monkeypatch.setattr(script.llama_cpp_setup, "target_platform", lambda: ("linux", "x64"))
    monkeypatch.setattr(script.llama_cpp_setup, "_prefer_cuda_source", lambda *_args: False)
    monkeypatch.setattr(script.sys, "platform", "linux")
    calls = []

    def install(_root, **kwargs):
        calls.append(kwargs["force"])
        return {"backend": "vulkan"}

    monkeypatch.setattr(script.llama_cpp_setup, "ensure_llama_cpp", install)
    cfg = {"_config_dir": str(tmp_path), "tools": {"llama_server": str(server)}}
    script._prepare_backend(cfg, "llama_cpp", lambda _message: None)
    assert calls == [True]
    assert cfg["tools"]["llama_server"] != str(server)


def test_tgi_smoke_bounds_warmup_and_memory():
    script = _script()
    _, profile = script._case({}, "tgi")
    assert profile["max_input_length"] == 128
    assert profile["max_total_tokens"] == 256
    assert profile["container_memory_gib"] == 12
    assert profile["compilation_jobs"] == 1
    assert profile["tgi_attention"] == "torch"
    args = profile["additional_args"]
    for flag, value in (("--max-concurrent-requests", "1"), ("--max-batch-size", "1"),
                        ("--max-batch-prefill-tokens", "256"), ("--max-batch-total-tokens", "256"),
                        ("--cuda-graphs", "0"), ("--cuda-memory-fraction", "0.5")):
        assert args[args.index(flag) + 1] == value


def test_startup_failure_summary_does_not_dump_ansi_config(harness, monkeypatch):
    h = harness

    def fail(*_args):
        raise RuntimeError("Container exited, OOMKilled=true\n\x1b[32mArgs {\n" + "long configuration\n" * 100)

    monkeypatch.setattr(h.backend, "wait_health", fail)
    row = h.script.run_one(h.cfg, "tgi", h.out)
    assert row["status"] == "failed"
    assert "Arbeitsspeichermangel" in row["detail"]
    assert "Args" not in row["detail"]
    assert "\x1b" not in row["error"]
    assert "long configuration" in row["error"]
    assert len(row["detail"]) < 300


def test_cached_gguf_does_not_contact_hub(tmp_path, monkeypatch):
    script = _script()
    cached = tmp_path / "models" / "smoke-gemma3-1b" / "gemma-3-1b-it-Q4_K_M.gguf"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"GGUF")
    monkeypatch.setattr(script, "hf_hub_download", lambda **_kwargs: pytest.fail("cache should avoid network request"))
    assert script._smallest_catalog_gguf({"_config_dir": str(tmp_path)}) == str(cached)


@pytest.mark.parametrize("url", ["", "http://0.0.0.0:8080", "http://[::]:8080", "http://example.org:8080"])
def test_port_selection_rejects_non_loopback_urls_before_probing(monkeypatch, url):
    script = _script()
    monkeypatch.setattr(script, "_free_port", lambda *_args: pytest.fail("invalid host must not be probed"))
    with pytest.raises(ValueError):
        script._available_url(url)


@pytest.mark.parametrize("url,expected_host", [("http://localhost:8080", "127.0.0.1"),
                                              ("http://[::1]:8080", "::1")])
def test_fallback_port_binds_only_explicit_loopback(monkeypatch, url, expected_host):
    script = _script()
    bound = []

    class Socket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def bind(self, address):
            bound.append(address)

        def getsockname(self):
            return expected_host, 12345

    monkeypatch.setattr(script, "_free_port", lambda _url: False)
    monkeypatch.setattr(script.socket, "socket", lambda *_args: Socket())
    selected = script._available_url(url)
    assert bound == [(expected_host, 0)]
    assert script.urlparse(selected).hostname == expected_host
    assert script.urlparse(selected).port == 12345


# --------------------------------------------- Start/Stopp-Zyklen (Issue #124)


def _cycle_run(statuses_by_call, calls):
    def run(_cfg, name, _out, on_progress, on_message):  # noqa: ARG001
        on_progress(name, "prerequisites")
        status = statuses_by_call[len(calls)]
        calls.append(name)
        return {"backend": name, "status": status, "detail": "t", "phase": "done", "seconds": 0.1}

    return run


def test_cycles_repeat_each_backend_and_number_the_rows(tmp_path, monkeypatch):
    script = _script()
    calls: list[str] = []
    monkeypatch.setattr(script, "load_config", lambda _path: {"endpoint": {}})
    monkeypatch.setattr(script, "run_one", _cycle_run(["passed"] * 6, calls))

    rc = script.main(["--output", str(tmp_path), "--backends", "ollama", "vllm", "--cycles", "3", "--no-progress"])

    rows = json.loads((tmp_path / "report.json").read_text())
    assert rc == 0 and calls == ["ollama"] * 3 + ["vllm"] * 3
    assert [row["cycle"] for row in rows] == [1, 2, 3, 1, 2, 3]


def test_cycles_stop_a_backend_at_its_first_failure_but_continue_with_the_next(tmp_path, monkeypatch):
    script = _script()
    calls: list[str] = []
    monkeypatch.setattr(script, "load_config", lambda _path: {"endpoint": {}})
    # ollama: pass, fail (stop) -> vllm: pass, pass
    monkeypatch.setattr(script, "run_one", _cycle_run(["passed", "failed", "passed", "passed"], calls))

    rc = script.main(["--output", str(tmp_path), "--backends", "ollama", "vllm", "--cycles", "2", "--no-progress"])

    assert rc == 1 and calls == ["ollama", "ollama", "vllm", "vllm"]


def test_abort_during_cycles_stops_everything(tmp_path, monkeypatch):
    script = _script()
    calls: list[str] = []
    monkeypatch.setattr(script, "load_config", lambda _path: {"endpoint": {}})
    monkeypatch.setattr(script, "run_one", _cycle_run(["passed", "aborted", "passed"], calls))

    rc = script.main(["--output", str(tmp_path), "--backends", "ollama", "vllm", "--cycles", "3", "--no-progress"])

    assert rc == 130 and calls == ["ollama", "ollama"]


@pytest.mark.parametrize("value", ["0", "-2", "x", "1.5"])
def test_cycles_must_be_a_positive_integer(value):
    with pytest.raises(SystemExit):
        _script().main(["--cycles", value])
