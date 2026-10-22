"""Dataset manifests: reproducible identification of workload input data.

A manifest records source, version, license, SHA-256 and sample selection
(docs/architecture/workloads.md).  It never embeds the data itself and never
requires confidential company data.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ids import UnknownTaskError, is_valid_workload_id_shape, parse_task_id

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SELECTION_METHODS = ("all", "first_n", "ids", "random_seeded")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CHUNK = 1024 * 1024
# Reserved DOS device names (also with an extension, e.g. "nul.txt").
_WIN_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


class DatasetManifestError(ValueError):
    """Base class for manifest problems."""


class DatasetManifestFormatError(DatasetManifestError):
    """The manifest file is unreadable, not JSON, or violates the format."""


class DatasetHashMismatchError(DatasetManifestError):
    """A data file does not match the SHA-256 recorded in the manifest."""


def _str(data: dict[str, Any], key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DatasetManifestFormatError(f"{where}: '{key}' must be a non-empty string")
    return value


def _check_relative_path(rel: str, where: str) -> None:
    """Reject paths that are unsafe on any supported OS (incl. Windows/NTFS)."""
    if "\x00" in rel:
        raise DatasetManifestFormatError(f"{where}.path must not contain NUL bytes")
    if ":" in rel:
        raise DatasetManifestFormatError(f"{where}.path must not contain ':' (drive letters, NTFS streams)")
    if Path(rel).is_absolute() or rel.startswith(("/", "\\")):
        raise DatasetManifestFormatError(f"{where}.path must be relative without '..'")
    for part in rel.replace("\\", "/").split("/"):
        if part == "..":
            raise DatasetManifestFormatError(f"{where}.path must be relative without '..'")
        if part and (part.endswith((".", " ")) and part != "."):
            raise DatasetManifestFormatError(f"{where}.path segment {part!r} ends with '.' or space")
        if part.split(".", 1)[0].rstrip(" ").upper() in _WIN_RESERVED:
            raise DatasetManifestFormatError(f"{where}.path segment {part!r} is a reserved Windows name")


def _sha(value: Any, where: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value.lower()):
        raise DatasetManifestFormatError(f"{where}: sha256 must be 64 hex characters")
    return value.lower()


@dataclass(frozen=True, slots=True)
class SampleSelection:
    method: str = "all"
    count: int | None = None
    seed: int | None = None
    ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.method not in SELECTION_METHODS:
            raise DatasetManifestFormatError(f"selection.method must be one of {SELECTION_METHODS}, got {self.method!r}")
        if self.method in ("first_n", "random_seeded"):
            if isinstance(self.count, bool) or not isinstance(self.count, int) or self.count <= 0:
                raise DatasetManifestFormatError(f"selection.count must be a positive integer for {self.method}")
        if self.method == "random_seeded" and (isinstance(self.seed, bool) or not isinstance(self.seed, int)):
            raise DatasetManifestFormatError("selection.seed (integer) is required for random_seeded; no hidden randomness")
        if self.method == "ids" and not self.ids:
            raise DatasetManifestFormatError("selection.ids must not be empty for method 'ids'")

    @classmethod
    def from_dict(cls, data: Any) -> "SampleSelection":
        if data is None:
            return cls()
        if not isinstance(data, dict):
            raise DatasetManifestFormatError("selection must be an object")
        ids = data.get("ids", [])
        if not isinstance(ids, list) or not all(isinstance(i, str) and i for i in ids):
            raise DatasetManifestFormatError("selection.ids must be a list of non-empty strings")
        return cls(str(data.get("method", "all")), data.get("count"), data.get("seed"), tuple(ids))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"method": self.method}
        if self.count is not None:
            out["count"] = self.count
        if self.seed is not None:
            out["seed"] = self.seed
        if self.ids:
            out["ids"] = list(self.ids)
        return out


@dataclass(frozen=True, slots=True)
class DatasetFile:
    path: str
    sha256: str
    size_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    id: str
    version: str
    task: str
    source: str
    license: str
    sha256: str  # hash of the dataset as a whole (or of its single file)
    selection: SampleSelection = field(default_factory=SampleSelection)
    workloads: tuple[str, ...] = ()
    files: tuple[DatasetFile, ...] = ()
    confidential: bool = False
    # True only after every listed file was hashed on disk and matched
    # (load_dataset_manifest(verify_dir=...)); never serialized, not compared.
    verified: bool = field(default=False, compare=False)

    @staticmethod
    def compute_files_sha256(files: "tuple[DatasetFile, ...] | list[DatasetFile]") -> str:
        """Aggregate hash: SHA-256 over the sorted lines ``<path>:<sha256>\n``.

        ``path`` uses ``/`` separators, ``sha256`` is lower-case hex; lines are
        sorted as strings and joined without separator, encoded as UTF-8.
        """
        lines = sorted(f"{f.path.replace(chr(92), '/')}:{f.sha256}\n" for f in files)
        return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, data: Any) -> "DatasetManifest":
        if not isinstance(data, dict):
            raise DatasetManifestFormatError("manifest must be a JSON object")
        ident = _str(data, "id", "manifest")
        if not _ID_RE.fullmatch(ident):
            raise DatasetManifestFormatError("manifest: 'id' contains invalid characters")
        task = _str(data, "task", "manifest")
        try:
            parse_task_id(task)
        except UnknownTaskError as exc:
            raise DatasetManifestFormatError(f"manifest: {exc}") from None
        workloads = data.get("workloads", [])
        if not isinstance(workloads, list) or not all(is_valid_workload_id_shape(w) for w in workloads):
            raise DatasetManifestFormatError("manifest: 'workloads' must be a list of '<group>.<name>' ids")
        raw_files = data.get("files", [])
        if not isinstance(raw_files, list):
            raise DatasetManifestFormatError("manifest: 'files' must be a list")
        files = []
        for i, item in enumerate(raw_files):
            if not isinstance(item, dict):
                raise DatasetManifestFormatError(f"files[{i}] must be an object")
            rel = _str(item, "path", f"files[{i}]")
            _check_relative_path(rel, f"files[{i}]")
            size = item.get("size_bytes")
            if size is not None and (isinstance(size, bool) or not isinstance(size, int) or size < 0):
                raise DatasetManifestFormatError(f"files[{i}].size_bytes must be a non-negative integer")
            files.append(DatasetFile(rel, _sha(item.get("sha256"), f"files[{i}]"), size))
        confidential = data.get("confidential", False)
        if not isinstance(confidential, bool):
            raise DatasetManifestFormatError("manifest: 'confidential' must be a boolean")
        manifest_sha = _sha(data.get("sha256"), "manifest")
        if files:
            expected = cls.compute_files_sha256(files)
            if expected != manifest_sha:
                raise DatasetHashMismatchError(
                    f"manifest sha256 {manifest_sha} does not match the aggregate hash of files[] ({expected})"
                )
        return cls(
            id=ident,
            version=_str(data, "version", "manifest"),
            task=task,
            source=_str(data, "source", "manifest"),
            license=_str(data, "license", "manifest"),
            sha256=manifest_sha,
            selection=SampleSelection.from_dict(data.get("selection")),
            workloads=tuple(workloads),
            files=tuple(files),
            confidential=confidential,
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id, "version": self.version, "task": self.task, "source": self.source,
            "license": self.license, "sha256": self.sha256, "selection": self.selection.to_dict(),
        }
        if self.workloads:
            out["workloads"] = list(self.workloads)
        if self.files:
            out["files"] = [
                {"path": f.path, "sha256": f.sha256, **({"size_bytes": f.size_bytes} if f.size_bytes is not None else {})}
                for f in self.files
            ]
        if self.confidential:
            out["confidential"] = True
        return out

    def reference(self) -> dict[str, Any]:
        """Compact form recorded in results (``dataset`` field)."""
        return {"id": self.id, "version": self.version, "sha256": self.sha256,
                "selection": self.selection.to_dict(), "verified": self.verified}

    def verify_files(self, base_dir: Path) -> None:
        """Hash every listed file below ``base_dir``; raise on missing/mismatch."""
        base = Path(base_dir).resolve()
        for entry in self.files:
            target = (base / entry.path).resolve()
            if base not in target.parents:
                raise DatasetManifestFormatError(f"file path escapes dataset directory: {entry.path}")
            verify_file_sha256(target, entry.sha256)


def verify_file_sha256(path: Path, expected: str) -> str:
    """Return the file's SHA-256 if it equals ``expected`` else raise."""
    path = Path(path)
    if not path.is_file():
        raise DatasetManifestError(f"dataset file not found: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected.lower():
        raise DatasetHashMismatchError(f"SHA-256 mismatch for {path.name}: expected {expected.lower()}, got {actual}")
    return actual


def load_dataset_manifest(path: Path, *, verify_dir: Path | None = None) -> DatasetManifest:
    """Load and validate a manifest; optionally verify listed files in ``verify_dir``."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise DatasetManifestFormatError(f"cannot read manifest {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DatasetManifestFormatError(f"manifest {path} is not valid JSON: {exc}") from exc
    manifest = DatasetManifest.from_dict(data)
    if verify_dir is not None:
        manifest.verify_files(verify_dir)
        if manifest.files:  # nothing to verify without files[] -> stays unverified
            object.__setattr__(manifest, "verified", True)
    return manifest
