"""Content-only historical identity and explicit current-artifact hashing."""
from __future__ import annotations
import re
from pathlib import Path
from collections.abc import Mapping
from .identity import IdentityError, hash_content, hash_shards, validate_label


def recorded_fingerprint(metadata: Mapping[str, object]) -> dict[str, str] | None:
    path = metadata.get("path")
    shard_count = metadata.get("shard_count")
    split = isinstance(shard_count, int) and not isinstance(shard_count, bool) and shard_count > 1
    split = split or isinstance(path, str) and bool(re.search(r"-\d{5}-of-\d{5}\.gguf$", path, re.I))
    digest = metadata.get("sha256")
    if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) and not split:
        return {"algorithm": "sha256", "scope": "recorded_single_file_content", "value": digest}
    return None


def resolve_identity(metadata: Mapping[str, object], *, label: str | None, rehash: bool, cache: dict | None = None) -> dict[str, object]:
    fingerprint = recorded_fingerprint(metadata)
    exact = "content_fingerprinted" if fingerprint else "unverified"
    if rehash:
        path_value = metadata.get("path")
        if not isinstance(path_value, str):
            raise IdentityError("models.identity.fingerprint: missing_artifact")
        path = Path(path_value)
        key = str(path.resolve())
        current = (cache or {}).get(key)
        if current is None:
            match = re.fullmatch(r"(.+)-(\d{5})-of-(\d{5})\.gguf", path.name, re.I)
            if match:
                count, index = int(match.group(3)), int(match.group(2))
                if not 1 <= index <= count <= 10000:
                    raise IdentityError("models.identity.fingerprint: invalid_shard_sequence")
                paths = [path.with_name(f"{match.group(1)}-{i:05d}-of-{count:05d}.gguf") for i in range(1, count + 1)]
                if not all(item.is_file() for item in paths):
                    raise IdentityError("models.identity.fingerprint: incomplete_shards")
                current = ("sha256-shards-v1", hash_shards(paths))
            else:
                current = ("sha256", hash_content(path))
            if cache is not None:
                cache[key] = current
        algorithm, digest = current
        if not fingerprint or fingerprint["value"] != digest:
            exact = "unverified"
            fingerprint = {"algorithm": algorithm, "scope": "current_artifact_unverified", "value": digest}
    identity: dict[str, object] = {"exact_identity": exact, "fingerprint_status": "available" if fingerprint else "unavailable"}
    if fingerprint:
        identity["fingerprint"] = fingerprint
    if label is not None:
        identity.update(label=validate_label(label), label_source="user_approved")
    public = metadata.get("public_id")
    if isinstance(public, str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}/[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}", public):
        identity["public_id"] = public
        revision = metadata.get("revision")
        if isinstance(revision, str) and re.fullmatch(r"[a-fA-F0-9]{40,64}", revision):
            identity["revision"] = revision
        if exact == "unverified" and not fingerprint:
            identity["exact_identity"] = "public_reference"
    for key in ("size_bytes", "shard_count"):
        if key in metadata:
            identity[key] = metadata[key]
    if not (label or fingerprint or identity.get("public_id")):
        raise IdentityError("models.identity: missing_approved_identity")
    return identity
