"""Filesystem boundary for offline community exports."""
from __future__ import annotations

import json
import os
import sys
import contextlib
from pathlib import Path, PureWindowsPath
from collections.abc import Mapping, Sequence

from .project import ProjectionError, project
from .schema import CommunityExport, json_schema, parse_document, serialize
from .schema import SafeError
from .identity import IdentityError, validate_label
from .identity_v1 import recorded_fingerprint
from llmbench.i18n import _


class CommunityError(ValueError):
    pass


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise CommunityError("duplicate JSON key")
        result[key] = value
    return result


def resolve_summary(path: Path) -> Path:
    if path.is_dir():
        final = path / "summary.json"
        partial = path / "summary.partial.json"
        if final.exists():
            return final
        if partial.exists():
            return partial
        raise CommunityError("run directory has no summary artifact")
    if not path.is_file():
        raise CommunityError("input summary does not exist")
    return path


def read_summary(path: Path) -> Mapping[str, object]:
    try:
        text = path.read_text(encoding="utf-8-sig")
        raw = json.loads(text, object_pairs_hook=_pairs, parse_constant=lambda _value: (_ for _ in ()).throw(CommunityError("non-finite JSON value")))
    except (OSError, UnicodeError, json.JSONDecodeError, CommunityError) as exc:
        raise CommunityError("summary cannot be read as strict JSON") from exc
    if not isinstance(raw, Mapping):
        raise CommunityError("summary must be a JSON object")
    return raw


def validate_document(path: Path) -> CommunityExport:
    try:
        return parse_document(path.read_text(encoding="utf-8-sig"))
    except SafeError:
        raise
    except (OSError, ValueError) as exc:
        raise CommunityError("$: unreadable_export") from exc


def write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise CommunityError("destination export already exists") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
    except OSError:
        with contextlib.suppress(OSError):
            path.unlink()
        raise


def export_inputs(inputs: Sequence[Path], *, out: Path | None, preview: bool, nickname: str | None, excluded: set[str], labels: Mapping[int, str] | None = None, fingerprint_positions: set[int] | None = None, rehash_models: bool = False, non_interactive: bool = False) -> tuple[int, list[str]]:
    messages: list[str] = []
    successes = 0
    model_offset = 0
    label_by_path: dict[str, str] = {}
    choice_by_content: dict[str, str | None] = {}
    hash_cache: dict = {}
    summaries: list[Mapping[str, object] | Exception] = []
    total_models = 0
    for source in inputs:
        try:
            summary = read_summary(resolve_summary(source))
            summaries.append(summary)
            raw = summary.get("models")
            total_models += len(raw) if isinstance(raw, list) else 0
        except (CommunityError, OSError) as exc:
            summaries.append(exc)
    if any(index < 1 or index > total_models for index in set(labels or {}) | set(fingerprint_positions or set())):
        return 2, ["models: selector_out_of_range"]
    if set(labels or {}) & set(fingerprint_positions or set()):
        return 2, ["models: conflicting_identity_options"]
    try:
        for label in (labels or {}).values():
            validate_label(label)
    except IdentityError:
        return 2, ["models.identity.label: invalid_label_option"]
    position = 0
    for item in summaries:
        if isinstance(item, Exception):
            continue
        models = item.get("models")
        if not isinstance(models, list):
            continue
        for raw_model in models:
            position += 1
            if not isinstance(raw_model, Mapping) or position not in set(labels or {}) | set(fingerprint_positions or set()):
                continue
            metadata = raw_model.get("model")
            if not isinstance(metadata, Mapping):
                continue
            fingerprint = recorded_fingerprint(metadata)
            choice = (labels or {}).get(position)
            if fingerprint:
                content_key = fingerprint["value"]
                if content_key in choice_by_content and choice_by_content[content_key] != choice:
                    return 2, ["models.identity: conflicting_proven_model_choices"]
                choice_by_content[content_key] = choice
            path_value = metadata.get("path")
            if choice is not None and isinstance(path_value, str):
                label_by_path[str(Path(path_value).resolve())] = choice
    for ordinal, _source in enumerate(inputs, start=1):
        model_count = 0
        try:
            item = summaries[ordinal - 1]
            if isinstance(item, Exception):
                raise item
            summary = item
            raw_models = summary.get("models")
            model_count = len(raw_models) if isinstance(raw_models, list) else 0
            local_labels = {
                position - model_offset: label
                for position, label in (labels or {}).items()
                if model_offset < position <= model_offset + model_count
            }
            local_fingerprints = {position - model_offset for position in (fingerprint_positions or set()) if model_offset < position <= model_offset + model_count}
            # Resolve each unresolved local model independently. A content hash
            # proves reuse; a path only permits reusing a label in this batch.
            raw_models = summary.get("models")
            if isinstance(raw_models, list):
                for local_index, raw_model in enumerate(raw_models, start=1):
                    if not isinstance(raw_model, Mapping):
                        continue
                    metadata = raw_model.get("model")
                    metadata = metadata if isinstance(metadata, Mapping) else {}
                    recorded = recorded_fingerprint(metadata)
                    digest = recorded["value"] if recorded else None
                    path_value = metadata.get("path")
                    has_recorded = recorded is not None
                    if digest in choice_by_content and local_index not in local_labels and local_index not in local_fingerprints:
                        choice = choice_by_content[digest]
                        if choice is not None:
                            local_labels[local_index] = choice
                        else:
                            local_fingerprints.add(local_index)
                    if local_index in local_labels or local_index in local_fingerprints:
                        if digest:
                            choice_by_content[digest] = local_labels.get(local_index)
                        continue
                    public = metadata.get("public_id")
                    import re
                    if isinstance(public, str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}/[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}", public):
                        continue
                    path_key = str(Path(path_value).resolve()) if isinstance(path_value, str) else None
                    if path_key in label_by_path:
                        local_labels[local_index] = label_by_path[path_key]
                        continue
                    if non_interactive or not sys.stdin.isatty():
                        if has_recorded or rehash_models:
                            continue
                        raise ProjectionError(f"models[{local_index - 1}].identity: missing_approved_identity")
                    suggestion = (PureWindowsPath(path_value).name if "\\" in path_value else Path(path_value).name) if isinstance(path_value, str) else "local-model"
                    try:
                        suggestion = validate_label(suggestion)
                    except IdentityError:
                        suggestion = "local-model"
                    print(_("Community-Modell {position}: [1] '{suggestion}' verwenden, [2] eigener Name, [3] Fingerprint").format(position=model_offset + local_index, suggestion=suggestion), file=sys.stderr)
                    answer = input().strip()
                    if answer == "1":
                        local_labels[local_index] = suggestion
                    elif answer == "2":
                        print(_("Oeffentlicher Modellname:"), file=sys.stderr)
                        local_labels[local_index] = input().strip()
                    elif answer == "3":
                        if not has_recorded and not rehash_models:
                            raise ProjectionError(f"models[{local_index - 1}].identity.fingerprint: unavailable_without_explicit_rehash")
                        local_fingerprints.add(local_index)
                    else:
                        raise ProjectionError("model identity choice is invalid")
                    if path_key is not None and local_index in local_labels:
                        label_by_path[path_key] = validate_label(local_labels[local_index])
                    if digest:
                        choice_by_content[digest] = local_labels.get(local_index)
            try:
                candidate = project(summary, nickname=nickname, excluded=excluded, labels=local_labels, rehash_models=rehash_models, identity_cache=hash_cache)
            except ProjectionError as exc:
                raise exc
            payload = serialize(candidate)
            if preview:
                sys.stdout.buffer.write(payload)
            else:
                if out is None:
                    raise CommunityError("missing output directory")
                write_exclusive(out / f"community-run-{ordinal:04d}.json", payload)
            successes += 1
        except (SafeError, IdentityError, CommunityError) as exc:
            messages.append(_("Eingabe {ordinal}: {error}").format(ordinal=ordinal, error=exc))
        except (ValueError, TypeError, OSError, EOFError):
            messages.append(_("Eingabe {ordinal}: {error}").format(ordinal=ordinal, error="$: invalid_source_or_io"))
        model_offset += model_count
    messages.append(_("Community-Export: {successes} erfolgreich, {failures} fehlgeschlagen").format(successes=successes, failures=len(inputs) - successes))
    return (0 if successes == len(inputs) else 1), messages


def schema_text() -> bytes:
    return (json.dumps(json_schema(), ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
