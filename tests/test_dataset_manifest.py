import hashlib
import json

import pytest

from llmbench.tasks import (
    DatasetHashMismatchError,
    DatasetManifest,
    DatasetManifestError,
    DatasetManifestFormatError,
    SampleSelection,
    load_dataset_manifest,
    verify_file_sha256,
)

H = "a" * 64


def _manifest(**over):
    data = {
        "id": "librispeech-mini", "version": "1.0", "task": "speech_to_text",
        "source": "https://example.org/data", "license": "CC-BY-4.0", "sha256": H,
        "selection": {"method": "first_n", "count": 10},
        "workloads": ["stt.short_audio"],
    }
    data.update(over)
    return data


def _write(tmp_path, data, name="m.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_valid_manifest_roundtrip(tmp_path):
    m = load_dataset_manifest(_write(tmp_path, _manifest()))
    assert m.id == "librispeech-mini" and m.selection.method == "first_n" and m.selection.count == 10
    assert DatasetManifest.from_dict(m.to_dict()) == m
    assert m.reference() == {"id": "librispeech-mini", "version": "1.0", "sha256": H,
                             "selection": {"method": "first_n", "count": 10}}


def test_default_selection_is_all():
    m = DatasetManifest.from_dict(_manifest(selection=None))
    assert m.selection == SampleSelection("all")


@pytest.mark.parametrize("key", ["id", "version", "task", "source", "license", "sha256"])
def test_required_fields(key):
    data = _manifest()
    del data[key]
    with pytest.raises(DatasetManifestFormatError):
        DatasetManifest.from_dict(data)


@pytest.mark.parametrize("over", [
    {"sha256": "xyz"}, {"sha256": "a" * 63}, {"task": "whisper"}, {"id": "../evil"},
    {"workloads": ["nodot"]}, {"confidential": "yes"},
    {"selection": {"method": "bogus"}}, {"selection": {"method": "first_n"}},
    {"selection": {"method": "first_n", "count": 0}},
    {"selection": {"method": "random_seeded", "count": 3}},
    {"selection": {"method": "ids", "ids": []}},
    {"files": [{"path": "../x", "sha256": H}]}, {"files": [{"path": "/abs", "sha256": H}]},
    {"files": [{"path": "a", "sha256": "bad"}]}, {"files": "nope"},
])
def test_invalid_manifests_rejected(over):
    with pytest.raises(DatasetManifestFormatError):
        DatasetManifest.from_dict(_manifest(**over))


def test_error_hierarchy():
    assert issubclass(DatasetHashMismatchError, DatasetManifestError)
    assert issubclass(DatasetManifestFormatError, DatasetManifestError)
    assert issubclass(DatasetManifestError, ValueError)


def test_loader_errors(tmp_path):
    with pytest.raises(DatasetManifestFormatError):
        load_dataset_manifest(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(DatasetManifestFormatError):
        load_dataset_manifest(bad)
    with pytest.raises(DatasetManifestFormatError):
        load_dataset_manifest(_write(tmp_path, [1, 2], "list.json"))


def test_hash_verification(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "a.txt").write_bytes(b"hello")
    good = hashlib.sha256(b"hello").hexdigest()
    path = _write(tmp_path, _manifest(files=[{"path": "a.txt", "sha256": good, "size_bytes": 5}]))
    m = load_dataset_manifest(path, verify_dir=data_dir)
    assert m.files[0].size_bytes == 5
    assert verify_file_sha256(data_dir / "a.txt", good.upper()) == good

    (data_dir / "a.txt").write_bytes(b"tampered")
    with pytest.raises(DatasetHashMismatchError):
        load_dataset_manifest(path, verify_dir=data_dir)
    (data_dir / "a.txt").unlink()
    with pytest.raises(DatasetManifestError):
        load_dataset_manifest(path, verify_dir=data_dir)


def test_no_verification_without_verify_dir(tmp_path):
    path = _write(tmp_path, _manifest(files=[{"path": "never-read.bin", "sha256": H}]))
    assert load_dataset_manifest(path).files[0].path == "never-read.bin"
