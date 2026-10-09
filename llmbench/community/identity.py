"""Explicit local model identity choices for community exports."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path


class IdentityError(ValueError):
    pass


def validate_label(value: str) -> str:
    value = value.strip()
    if not 1 <= len(value) <= 128 or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value) or "/" in value or "\\" in value or "://" in value or re.match(r"^[a-zA-Z]:", value) or value in {".", "..", "~"}:
        raise IdentityError("model label is invalid")
    return value


def hash_content(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                digest.update(block)
    except OSError as exc:
        raise IdentityError("model artifact cannot be hashed") from exc
    return digest.hexdigest()


def hash_shards(paths: list[Path]) -> str:
    """Name-independent aggregate over explicitly ordered shard contents."""
    digest = hashlib.sha256(b"llmbench:sha256-shards-v1\0" + len(paths).to_bytes(8, "big"))
    if not paths:
        raise IdentityError("models.identity.fingerprint: empty_shards")
    try:
        for path in paths:
            size = path.stat().st_size
            digest.update(size.to_bytes(16, "big"))
            digest.update(bytes.fromhex(hash_content(path)))
    except OSError as exc:
        raise IdentityError("models.identity.fingerprint: unreadable_shards") from exc
    return digest.hexdigest()
