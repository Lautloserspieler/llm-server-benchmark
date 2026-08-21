from pathlib import Path

import yaml

from llmbench.bootstrap import bootstrap_config


def test_bootstrap_discovers_gguf_and_preserves_existing(tmp_path: Path):
    root = tmp_path
    (root / "models").mkdir()
    (root / "tools" / "llama.cpp").mkdir(parents=True)
    (root / "models" / "A.gguf").write_bytes(b"a")
    (root / "models" / "B.gguf").write_bytes(b"b")
    (root / "tools" / "llama.cpp" / "llama-bench.exe").write_bytes(b"")
    (root / "tools" / "llama.cpp" / "llama-server.exe").write_bytes(b"")
    (root / "benchmark.example.yaml").write_text("models: []\n", encoding="utf-8")

    result = bootstrap_config(
        root / "benchmark.yaml",
        root,
        root / "tools" / "llama.cpp",
        root / "models",
    )
    assert result["models_added"] == 2
    cfg = yaml.safe_load((root / "benchmark.yaml").read_text(encoding="utf-8"))
    assert {m["name"] for m in cfg["models"]} == {"A", "B"}
    assert all(m["profiles"][0]["gpu_layers"] == -1 for m in cfg["models"])

    result2 = bootstrap_config(
        root / "benchmark.yaml",
        root,
        root / "tools" / "llama.cpp",
        root / "models",
    )
    assert result2["models_added"] == 0
    cfg2 = yaml.safe_load((root / "benchmark.yaml").read_text(encoding="utf-8"))
    assert len(cfg2["models"]) == 2
