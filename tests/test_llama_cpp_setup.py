import io
import json
import os
import stat
import tarfile
from pathlib import Path

import pytest

from llmbench import llama_cpp_setup as lcs


def test_target_platform_maps_system_and_arch(monkeypatch):
    monkeypatch.setattr(lcs.platform, "system", lambda: "Linux")
    monkeypatch.setattr(lcs.platform, "machine", lambda: "x86_64")
    assert lcs.target_platform() == ("linux", "x64")

    monkeypatch.setattr(lcs.platform, "machine", lambda: "aarch64")
    assert lcs.target_platform() == ("linux", "arm64")

    monkeypatch.setattr(lcs.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(lcs.platform, "machine", lambda: "arm64")
    assert lcs.target_platform() == ("macos", "arm64")


def test_target_platform_rejects_windows_and_unknown_arch(monkeypatch):
    monkeypatch.setattr(lcs.platform, "system", lambda: "Windows")
    with pytest.raises(RuntimeError, match="Windows"):
        lcs.target_platform()

    monkeypatch.setattr(lcs.platform, "system", lambda: "Linux")
    monkeypatch.setattr(lcs.platform, "machine", lambda: "riscv64")
    with pytest.raises(RuntimeError, match="riscv64"):
        lcs.target_platform()


def test_pinned_tag_prefers_explicit_over_env_over_file(tmp_path: Path, monkeypatch):
    (tmp_path / "llama-cpp-version.txt").write_text("b10000\n", encoding="utf-8")
    monkeypatch.setenv("LLMBENCH_LLAMACPP_TAG", "b20000")
    assert lcs.pinned_tag(tmp_path, "b30000") == "b30000"
    assert lcs.pinned_tag(tmp_path, None) == "b20000"
    monkeypatch.delenv("LLMBENCH_LLAMACPP_TAG")
    assert lcs.pinned_tag(tmp_path, None) == "b10000"


def test_pinned_tag_ignores_comments_and_blank_lines(tmp_path: Path):
    (tmp_path / "llama-cpp-version.txt").write_text("# pinned\n\nb10604\n", encoding="utf-8")
    assert lcs.pinned_tag(tmp_path, None) == "b10604"


def test_pinned_tag_rejects_invalid_value(tmp_path: Path):
    with pytest.raises(RuntimeError, match="gueltige"):
        lcs.pinned_tag(tmp_path, "../etc/passwd")


def test_asset_pattern_matches_expected_release_names():
    linux_cpu = lcs.asset_pattern("linux", "x64", "cpu")
    linux_vulkan = lcs.asset_pattern("linux", "arm64", "vulkan")
    macos = lcs.asset_pattern("macos", "arm64", "cpu")

    assert lcs.find_asset(
        [{"assets": [{"name": "llama-b10604-bin-ubuntu-x64.tar.gz"}]}], linux_cpu
    )
    assert lcs.find_asset(
        [{"assets": [{"name": "llama-b10604-bin-ubuntu-vulkan-arm64.tar.gz"}]}], linux_vulkan
    )
    assert lcs.find_asset(
        [{"assets": [{"name": "llama-b10604-bin-macos-arm64.tar.gz"}]}], macos
    )
    assert not lcs.find_asset(
        [{"assets": [{"name": "llama-b10604-bin-win-cpu-x64.zip"}]}], linux_cpu
    )


def test_find_asset_returns_none_when_nothing_matches():
    assert lcs.find_asset([{"assets": [{"name": "unrelated.zip"}]}], lcs.asset_pattern("linux", "x64", "cpu")) is None


def test_source_build_enabled_can_be_disabled(monkeypatch):
    monkeypatch.setenv("LLMBENCH_LLAMACPP_SOURCE_BUILD", "0")
    assert lcs._source_build_enabled() is False
    monkeypatch.setenv("LLMBENCH_LLAMACPP_SOURCE_BUILD", "1")
    assert lcs._source_build_enabled() is True


def test_source_backend_order_prefers_cuda_when_nvcc_exists(monkeypatch):
    monkeypatch.delenv("LLMBENCH_LLAMACPP_BUILD_BACKEND", raising=False)
    monkeypatch.setattr(lcs, "_which_nvcc", lambda: "/usr/local/cuda/bin/nvcc")
    assert lcs._source_backend_order() == ["cuda", "cpu"]


def test_source_backend_order_respects_forced_cpu(monkeypatch):
    monkeypatch.setenv("LLMBENCH_LLAMACPP_BUILD_BACKEND", "cpu")
    monkeypatch.setattr(lcs, "_which_nvcc", lambda: "/usr/local/cuda/bin/nvcc")
    assert lcs._source_backend_order() == ["cpu"]


def _fake_bench_script(path: Path, exit_code: int = 0, output: str = "Device 0: fake\n") -> None:
    path.write_text(f"#!/bin/sh\necho '{output.strip()}'\nexit {exit_code}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def test_probe_reports_success_and_failure(tmp_path: Path):
    ok_bench = tmp_path / "llama-bench-ok"
    _fake_bench_script(ok_bench, exit_code=0)
    ok, output = lcs.probe(ok_bench)
    assert ok is True
    assert "Device 0" in output

    bad_bench = tmp_path / "llama-bench-bad"
    _fake_bench_script(bad_bench, exit_code=1, output="error: no backend")
    ok, output = lcs.probe(bad_bench)
    assert ok is False
    assert "error" in output


def test_probe_missing_binary_fails_without_raising(tmp_path: Path):
    ok, output = lcs.probe(tmp_path / "does-not-exist")
    assert ok is False
    assert "fehlt" in output


def _make_archive(tmp_path: Path, name: str, nested_dir: str | None = None) -> Path:
    archive = tmp_path / name
    with tarfile.open(archive, "w:gz") as tf:
        for fname, _content, exit_code in (("llama-bench", "ok", 0), ("llama-server", "ok", 0)):
            script = f"#!/bin/sh\necho 'Device 0: fake'\nexit {exit_code}\n"
            data = script.encode("utf-8")
            member_name = f"{nested_dir}/{fname}" if nested_dir else fname
            info = tarfile.TarInfo(name=member_name)
            info.size = len(data)
            info.mode = 0o755
            tf.addfile(info, io.BytesIO(data))
    return archive


def test_extract_flattens_nested_top_level_directory(tmp_path: Path):
    archive = _make_archive(tmp_path, "nested.tar.gz", nested_dir="llama-b10604")
    dest = tmp_path / "out"
    lcs._extract(archive, dest)
    bench = dest / "llama-bench"
    assert bench.exists()
    assert os.access(bench, os.X_OK)


def test_extract_rejects_path_traversal(tmp_path: Path):
    archive = tmp_path / "evil.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        data = b"evil"
        info = tarfile.TarInfo(name="../../evil")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    dest = tmp_path / "out"
    with pytest.raises(RuntimeError, match="Unsicherer Pfad"):
        lcs._extract(archive, dest)


def _release(tag: str, assets: list[str]) -> dict:
    return {"tag_name": tag, "draft": False, "assets": [{"name": a, "browser_download_url": f"https://example/{a}"} for a in assets]}


def test_ensure_llama_cpp_installs_cpu_build_when_no_gpu(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(lcs, "target_platform", lambda: ("linux", "x64"))
    monkeypatch.setattr(lcs, "looks_like_gpu_present", lambda: False)
    monkeypatch.setattr(lcs, "release_candidates", lambda _root, _tag: [_release("b111", ["llama-b111-bin-ubuntu-x64.tar.gz"])])

    def fake_download(_url, dest):
        archive = _make_archive(tmp_path, "dl.tar.gz")
        dest.write_bytes(archive.read_bytes())

    monkeypatch.setattr(lcs, "_download_file", fake_download)

    result = lcs.ensure_llama_cpp(tmp_path, log=lambda _m: None)
    assert result["tag"] == "b111"
    assert result["backend"] == "cpu"
    assert result["source_build"] is False
    assert (tmp_path / "tools" / "llama.cpp" / "llama-bench").exists()


def test_ensure_llama_cpp_falls_back_from_vulkan_to_cpu_when_vulkan_does_not_start(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(lcs, "target_platform", lambda: ("linux", "x64"))
    monkeypatch.setattr(lcs, "looks_like_gpu_present", lambda: True)
    monkeypatch.setattr(
        lcs,
        "release_candidates",
        lambda _root, _tag: [
            _release("b222", ["llama-b222-bin-ubuntu-vulkan-x64.tar.gz", "llama-b222-bin-ubuntu-x64.tar.gz"])
        ],
    )

    calls = {"n": 0}

    def fake_download(url, dest):
        calls["n"] += 1
        if "vulkan" in url:
            archive = tmp_path / "broken.tar.gz"
            with tarfile.open(archive, "w:gz") as tf:
                for fname in ("llama-bench", "llama-server"):
                    script = "#!/bin/sh\necho 'no vulkan icd'\nexit 1\n"
                    data = script.encode("utf-8")
                    info = tarfile.TarInfo(name=fname)
                    info.size = len(data)
                    info.mode = 0o755
                    tf.addfile(info, io.BytesIO(data))
            dest.write_bytes(archive.read_bytes())
        else:
            archive = _make_archive(tmp_path, "good.tar.gz")
            dest.write_bytes(archive.read_bytes())

    monkeypatch.setattr(lcs, "_download_file", fake_download)

    result = lcs.ensure_llama_cpp(tmp_path, log=lambda _m: None)
    assert result["backend"] == "cpu"
    assert calls["n"] == 2


def test_ensure_llama_cpp_builds_from_source_when_linux_release_asset_is_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(lcs, "target_platform", lambda: ("linux", "x64"))
    monkeypatch.setattr(lcs, "looks_like_gpu_present", lambda: False)
    monkeypatch.setattr(lcs, "release_candidates", lambda _root, _tag: [_release("b333", ["llama-b333-bin-win-cpu-x64.zip"])])

    def fake_source_build(root, llama_dir, ref, state_file, arch, force, log):
        llama_dir.mkdir(parents=True, exist_ok=True)
        _fake_bench_script(llama_dir / "llama-bench")
        (llama_dir / "llama-server").write_text("stub", encoding="utf-8")
        state = {"tag": ref, "backend": "cpu", "source_build": True, "platform": f"linux-{arch}"}
        state_file.write_text(json.dumps(state), encoding="utf-8")
        return state

    monkeypatch.setattr(lcs, "build_llama_cpp_from_source", fake_source_build)

    result = lcs.ensure_llama_cpp(tmp_path, log=lambda _m: None)
    assert result["tag"] == "b333"
    assert result["backend"] == "cpu"
    assert result["source_build"] is True


def test_ensure_llama_cpp_skips_reinstall_when_already_working(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(lcs, "target_platform", lambda: ("linux", "x64"))
    llama_dir = tmp_path / "tools" / "llama.cpp"
    llama_dir.mkdir(parents=True)
    _fake_bench_script(llama_dir / "llama-bench")
    (llama_dir / "llama-server").write_text("stub", encoding="utf-8")
    (llama_dir / ".llama-build.json").write_text(json.dumps({"tag": "b999", "backend": "cpu"}), encoding="utf-8")

    def fail_if_called(*_a, **_k):
        raise AssertionError("release_candidates should not be called when reusing an existing install")

    monkeypatch.setattr(lcs, "release_candidates", fail_if_called)

    result = lcs.ensure_llama_cpp(tmp_path, log=lambda _m: None)
    assert result["tag"] == "b999"


def test_ensure_llama_cpp_raises_with_no_matching_asset_when_source_build_is_disabled(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LLMBENCH_LLAMACPP_SOURCE_BUILD", "0")
    monkeypatch.setattr(lcs, "target_platform", lambda: ("linux", "x64"))
    monkeypatch.setattr(lcs, "looks_like_gpu_present", lambda: False)
    monkeypatch.setattr(lcs, "release_candidates", lambda _root, _tag: [_release("b333", ["llama-b333-bin-win-cpu-x64.zip"])])

    with pytest.raises(RuntimeError, match="fehlgeschlagen"):
        lcs.ensure_llama_cpp(tmp_path, log=lambda _m: None)
