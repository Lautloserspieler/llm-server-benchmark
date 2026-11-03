"""Sichere Extraktion von TAR- und ZIP-Archiven.

Die Validierung erfolgt vollstaendig vor dem ersten Schreibzugriff. Abgelehnt
werden absolute Pfade, Pfad-Traversal, Backslashes, unsichere Symlinks, Hardlinks sowie
Geraete- und FIFO-Eintraege. Zusaetzlich werden Anzahl und entpackte Groesse
begrenzt, damit ein manipuliertes Archiv keinen Speicher oder Datentraeger
ueberlasten kann.
"""

from __future__ import annotations

import re
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

DEFAULT_MAX_MEMBERS = 10_000
DEFAULT_MAX_UNCOMPRESSED_BYTES = 8 * 1024**3

_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class UnsafeArchiveError(RuntimeError):
    """Das Archiv enthaelt einen Eintrag, der ausserhalb des Ziels wirken kann."""


class ArchiveLimitError(RuntimeError):
    """Das Archiv ueberschreitet ein konfiguriertes Limit."""


def _validate_name(name: str, dest_resolved: Path) -> None:
    if not name or "\x00" in name:
        raise UnsafeArchiveError(f"Ungueltiger Eintrag im Archiv: {name!r}")
    if "\\" in name:
        raise UnsafeArchiveError(f"Backslash im Archivpfad: {name}")
    pure = PurePosixPath(name)
    if pure.is_absolute() or _DRIVE_RE.match(name):
        raise UnsafeArchiveError(f"Absoluter Pfad im Archiv: {name}")
    if any(part == ".." for part in pure.parts):
        raise UnsafeArchiveError(f"Unsicherer Pfad im Archiv: {name}")
    target = (dest_resolved / name).resolve()
    if target != dest_resolved and dest_resolved not in target.parents:
        raise UnsafeArchiveError(f"Unsicherer Pfad im Archiv: {name}")


def _validate_symlink(name: str, linkname: str, dest_resolved: Path) -> None:
    if not linkname or "\x00" in linkname:
        raise UnsafeArchiveError(f"Ungueltiges Symlink-Ziel im Archiv: {name!r}")
    if "\\" in linkname:
        raise UnsafeArchiveError(f"Backslash im Symlink-Ziel: {name} -> {linkname}")
    pure = PurePosixPath(linkname)
    if pure.is_absolute() or _DRIVE_RE.match(linkname):
        raise UnsafeArchiveError(f"Absolutes Symlink-Ziel im Archiv: {name} -> {linkname}")
    if any(part == ".." for part in pure.parts):
        raise UnsafeArchiveError(f"Unsicheres Symlink-Ziel im Archiv: {name} -> {linkname}")
    link_parent = (dest_resolved / name).parent
    target = (link_parent / linkname).resolve()
    if target != dest_resolved and dest_resolved not in target.parents:
        raise UnsafeArchiveError(f"Symlink-Ziel ausserhalb des Archivs: {name} -> {linkname}")


def _check_limits(entries: list[tuple[str, int, bool]], dest: Path, max_members: int, max_uncompressed_bytes: int) -> Path:
    if len(entries) > max_members:
        raise ArchiveLimitError(f"Archiv enthaelt mehr als {max_members} Eintraege")
    dest_resolved = dest.resolve()
    total = 0
    for name, size, is_dir in entries:
        _validate_name(name, dest_resolved)
        if not is_dir:
            total += max(size, 0)
            if total > max_uncompressed_bytes:
                raise ArchiveLimitError(
                    f"Archiv ist groesser als {max_uncompressed_bytes} Bytes entpackt"
                )
    return dest_resolved


def safe_extract_tar(
    tf: tarfile.TarFile,
    dest: Path,
    *,
    max_members: int = DEFAULT_MAX_MEMBERS,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
) -> None:
    """Extrahiert ein TAR-Archiv nach ``dest``, ohne das Ziel zu verlassen."""
    members = tf.getmembers()
    dest_resolved = dest.resolve()
    entries: list[tuple[str, int, bool]] = []
    seen: set[str] = set()
    for member in members:
        _validate_name(member.name, dest_resolved)
        key = PurePosixPath(member.name).as_posix()
        if key in seen:
            raise UnsafeArchiveError(f"Doppelter Eintrag im Archiv: {member.name}")
        seen.add(key)
        if member.issym():
            _validate_symlink(member.name, member.linkname, dest_resolved)
        elif member.islnk():
            raise UnsafeArchiveError(f"Hardlinks sind im Archiv nicht erlaubt: {member.name}")
        elif member.isdev() or member.ischr() or member.isblk() or member.isfifo():
            raise UnsafeArchiveError(f"Spezialdatei im Archiv nicht erlaubt: {member.name}")
        entries.append((member.name, member.size, member.isdir()))

    _check_limits(entries, dest, max_members, max_uncompressed_bytes)

    for member in members:
        # set_attrs=False verhindert, dass das Archiv Setuid-Bits oder
        # Zeitstempel auf dem Zielsystem setzt.
        tf.extract(member, path=dest, set_attrs=False)


def _extract_zip_members(
    zf: zipfile.ZipFile,
    dest: Path,
    *,
    max_members: int,
    max_uncompressed_bytes: int,
) -> None:
    infos = zf.infolist()
    entries: list[tuple[str, int, bool]] = []
    for info in infos:
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise UnsafeArchiveError(f"Links sind im Archiv nicht erlaubt: {info.filename}")
        entries.append((info.filename, info.file_size, info.is_dir()))

    _check_limits(entries, dest, max_members, max_uncompressed_bytes)

    for info in infos:
        zf.extract(info, path=dest)


def safe_extract_zip(
    archive: Path | zipfile.ZipFile,
    dest: Path,
    *,
    max_members: int = DEFAULT_MAX_MEMBERS,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
) -> None:
    """Extrahiert ein ZIP-Archiv nach ``dest``, ohne das Ziel zu verlassen."""
    if isinstance(archive, zipfile.ZipFile):
        _extract_zip_members(
            archive,
            dest,
            max_members=max_members,
            max_uncompressed_bytes=max_uncompressed_bytes,
        )
        return
    with zipfile.ZipFile(archive) as zf:
        _extract_zip_members(
            zf,
            dest,
            max_members=max_members,
            max_uncompressed_bytes=max_uncompressed_bytes,
        )
