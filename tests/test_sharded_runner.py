from pathlib import Path

from llmbench.runner import _model_meta


def test_model_meta_uses_complete_sharded_gguf_size_and_hash(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    first = models / "big-Q4_K_M-00001-of-00002.gguf"
    second = models / "big-Q4_K_M-00002-of-00002.gguf"
    first.write_bytes(b"abc")
    second.write_bytes(b"defgh")

    cfg = {
        "_config_dir": str(tmp_path),
        "project": {"hash_models": True},
    }
    meta = _model_meta(
        {
            "name": "big-Q4_K_M",
            "path": "models/big-Q4_K_M-00001-of-00002.gguf",
        },
        cfg,
    )

    assert meta["exists"] is True
    assert meta["size_bytes"] == 8
    assert meta["shard_count"] == 2
    assert meta["shards"] == [first.name, second.name]
    assert len(meta["sha256"]) == 64
