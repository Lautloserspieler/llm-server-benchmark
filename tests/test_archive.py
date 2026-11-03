import importlib.util
import io
import os
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest

from llmbench.archive import (
    ArchiveLimitError,
    UnsafeArchiveError,
    safe_extract_tar,
    safe_extract_zip,
)


def _tar_with(tmp_path: Path, members: list[tuple[str, bytes, str]]) -> Path:
    """members: (name, data, kind) mit kind in file/dir/symlink/hardlink/fifo."""
    archive = tmp_path / "archive.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        for name, data, kind in members:
            info = tarfile.TarInfo(name=name)
            if kind == "file":
                info.size = len(data)
                info.mode = 0o644
                tf.addfile(info, io.BytesIO(data))
            elif kind == "dir":
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tf.addfile(info)
            elif kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = data.decode("utf-8")
                tf.addfile(info)
            elif kind == "hardlink":
                info.type = tarfile.LNKTYPE
                info.linkname = data.decode("utf-8")
                tf.addfile(info)
            elif kind == "fifo":
                info.type = tarfile.FIFOTYPE
                tf.addfile(info)
            else:  # pragma: no cover - Testfehler
                raise AssertionError(kind)
    return archive


def _extract_tar(archive: Path, dest: Path) -> None:
    with tarfile.open(archive) as tf:
        safe_extract_tar(tf, dest)


def test_safe_extract_tar_writes_regular_files(tmp_path: Path):
    archive = _tar_with(tmp_path, [("bundle/llama-bench", b"binary", "file")])
    dest = tmp_path / "out"
    dest.mkdir()
    _extract_tar(archive, dest)
    assert (dest / "bundle" / "llama-bench").read_bytes() == b"binary"


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "bundle/../../escape",
        "/tmp/escape",
        "C:\\temp\\escape",
        "..\\escape",
        "bundle\\..\\..\\escape",
    ],
)
def test_safe_extract_tar_rejects_unsafe_names(tmp_path: Path, name: str):
    archive = _tar_with(tmp_path, [(name, b"evil", "file")])
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(UnsafeArchiveError):
        _extract_tar(archive, dest)
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize("target", ["/etc/passwd", "../../escape", "..\\escape"])
def test_safe_extract_tar_rejects_escaping_symlinks(tmp_path: Path, target: str):
    archive = _tar_with(
        tmp_path,
        [("target", b"target", "file"), ("evil", target.encode("utf-8"), "symlink")],
    )
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(UnsafeArchiveError):
        _extract_tar(archive, dest)
    assert not (dest / "evil").exists()


@pytest.mark.parametrize("kind", ["hardlink", "fifo"])
def test_safe_extract_tar_rejects_hardlinks_and_special_files(tmp_path: Path, kind: str):
    archive = _tar_with(
        tmp_path,
        [("target", b"target", "file"), ("evil", b"target", kind)],
    )
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(UnsafeArchiveError):
        _extract_tar(archive, dest)
    assert not (dest / "evil").exists()


@pytest.mark.skipif(
    os.name == "nt",
    reason="Symlink-Erzeugung erfordert unter Windows erhoehte Rechte; die Validierung wird separat geprueft.",
)
def test_safe_extract_tar_allows_relative_symlink_inside_destination(tmp_path: Path):
    archive = _tar_with(
        tmp_path,
        [
            ("bundle/libllama.so.0", b"library", "file"),
            ("bundle/libllama.so", b"libllama.so.0", "symlink"),
        ],
    )
    dest = tmp_path / "out"
    dest.mkdir()

    _extract_tar(archive, dest)

    link = dest / "bundle" / "libllama.so"
    assert link.is_symlink()
    assert link.resolve() == (dest / "bundle" / "libllama.so.0").resolve()


def test_safe_extract_tar_rejects_duplicate_member_names(tmp_path: Path):
    archive = _tar_with(
        tmp_path,
        [("same", b"one", "file"), ("same", b"two", "file")],
    )
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(UnsafeArchiveError, match="Doppelter"):
        _extract_tar(archive, dest)


def test_safe_extract_tar_rejects_too_many_members(tmp_path: Path):
    archive = _tar_with(
        tmp_path,
        [(f"file-{index}", b"x", "file") for index in range(4)],
    )
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(ArchiveLimitError):
        _extract_tar_with_limit(archive, dest, max_members=3)


def _extract_tar_with_limit(archive: Path, dest: Path, *, max_members: int) -> None:
    with tarfile.open(archive) as tf:
        safe_extract_tar(tf, dest, max_members=max_members)


def test_safe_extract_tar_rejects_oversized_content(tmp_path: Path):
    archive = _tar_with(tmp_path, [("big", b"x" * 64, "file")])
    dest = tmp_path / "out"
    dest.mkdir()
    with tarfile.open(archive) as tf, pytest.raises(ArchiveLimitError):
        safe_extract_tar(tf, dest, max_uncompressed_bytes=32)


def _zip_with(tmp_path: Path, entries: list[tuple[str, bytes, int | None]]) -> Path:
    archive = tmp_path / "archive.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name)
            info.date_time = (2026, 1, 1, 0, 0, 0)
            if mode is not None:
                info.external_attr = mode << 16
            zf.writestr(info, data)
    return archive


def test_safe_extract_zip_writes_regular_files(tmp_path: Path):
    archive = _zip_with(tmp_path, [("bundle/llama-bench", b"binary", None)])
    dest = tmp_path / "out"
    dest.mkdir()
    safe_extract_zip(archive, dest)
    assert (dest / "bundle" / "llama-bench").read_bytes() == b"binary"


@pytest.mark.parametrize("name", ["../escape", "/tmp/escape", "C:\\temp\\escape", "..\\escape"])
def test_safe_extract_zip_rejects_unsafe_names(tmp_path: Path, name: str):
    archive = _zip_with(tmp_path, [(name, b"evil", None)])
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(UnsafeArchiveError):
        safe_extract_zip(archive, dest)
    assert not (tmp_path / "escape").exists()


def test_safe_extract_zip_rejects_symlink_entries(tmp_path: Path):
    archive = _zip_with(tmp_path, [("evil", b"target", stat.S_IFLNK | 0o777)])
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(UnsafeArchiveError):
        safe_extract_zip(archive, dest)
    assert not (dest / "evil").exists()


def _prepare_llama_source_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "PREPARE_LLAMA_SOURCE.py"
    spec = importlib.util.spec_from_file_location("prepare_llama_source", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prepare_llama_source_rejects_zip_slip(tmp_path: Path):
    module = _prepare_llama_source_module()
    archive = _zip_with(tmp_path, [("../../escape/CMakeLists.txt", b"evil", None)])
    destination = tmp_path / "prepared"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(UnsafeArchiveError):
        module.extract_source(archive, destination)

    assert marker.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path.parent / "escape").exists()

