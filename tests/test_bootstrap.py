from pathlib import Path

import yaml

from llmbench.bootstrap import (
    bootstrap_config,
    discover_llama_binaries,
    discover_models,
    unique_model_name,
)


def _make_project(root: Path) -> None:
    (root / "models").mkdir()
    (root / "tools" / "llama.cpp").mkdir(parents=True)
    (root / "models" / "A.gguf").write_bytes(b"a")
    (root / "models" / "B.gguf").write_bytes(b"b")
    (root / "tools" / "llama.cpp" / "llama-bench.exe").write_bytes(b"")
    (root / "tools" / "llama.cpp" / "llama-server.exe").write_bytes(b"")
    (root / "benchmark.example.yaml").write_text("models: []\n", encoding="utf-8")


def test_bootstrap_discovers_gguf_and_preserves_existing(tmp_path: Path):
    root = tmp_path
    _make_project(root)

    result = bootstrap_config(
        root / "benchmark.yaml", root, root / "tools" / "llama.cpp", root / "models"
    )
    assert result["models_added"] == 2
    assert result["llama_binaries_found"] is True
    cfg = yaml.safe_load((root / "benchmark.yaml").read_text(encoding="utf-8"))
    assert {m["name"] for m in cfg["models"]} == {"A", "B"}
    assert all(m["profiles"][0]["gpu_layers"] == -1 for m in cfg["models"])

    result2 = bootstrap_config(
        root / "benchmark.yaml", root, root / "tools" / "llama.cpp", root / "models"
    )
    assert result2["models_added"] == 0
    cfg2 = yaml.safe_load((root / "benchmark.yaml").read_text(encoding="utf-8"))
    assert len(cfg2["models"]) == 2


def test_same_filename_in_different_folders_gets_distinct_names(tmp_path: Path):
    """Sonst landen beide Modelle im selben Ergebnisordner und das zweite
    ueberschreibt die Rohdaten des ersten."""
    root = tmp_path
    _make_project(root)
    (root / "models" / "q4").mkdir()
    (root / "models" / "q8").mkdir()
    (root / "models" / "q4" / "mixtral.gguf").write_bytes(b"4")
    (root / "models" / "q8" / "mixtral.gguf").write_bytes(b"8")

    bootstrap_config(root / "benchmark.yaml", root, root / "tools" / "llama.cpp", root / "models")
    cfg = yaml.safe_load((root / "benchmark.yaml").read_text(encoding="utf-8"))
    names = [m["name"] for m in cfg["models"]]
    assert len(names) == len(set(names)), names
    assert "mixtral" in names
    assert any(n.startswith("mixtral-") for n in names)


def test_unique_model_name_falls_back_to_hash(tmp_path: Path):
    path = tmp_path / "x" / "model.gguf"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"")
    assert unique_model_name(path, set()) == "model"
    assert unique_model_name(path, {"model"}) == "model-x"
    third = unique_model_name(path, {"model", "model-x"})
    assert third.startswith("model-") and third not in {"model-x"}


def test_llama_discovery_stays_inside_the_project(tmp_path: Path, monkeypatch):
    """Eine systemweite Suche koennte die bewusst eingefrorene llama.cpp
    still durch eine andere ersetzen."""
    root = tmp_path / "project"
    (root / "tools" / "llama.cpp").mkdir(parents=True)

    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "llama-bench").write_bytes(b"")
    (outside / "llama-server").write_bytes(b"")
    monkeypatch.chdir(outside)
    monkeypatch.setattr("shutil.which", lambda name: str(outside / name))

    assert discover_llama_binaries(root) is None
    assert discover_llama_binaries(root, allow_system_search=True) == str(outside.resolve())


def test_model_discovery_ignores_system_paths_by_default(tmp_path: Path):
    root = tmp_path
    (root / "models").mkdir()
    (root / "models" / "only.gguf").write_bytes(b"x")
    found = discover_models(root, root / "models")
    assert [p.name for p in found] == ["only.gguf"]


def test_bootstrap_warns_about_missing_configured_model(tmp_path: Path):
    root = tmp_path
    _make_project(root)
    (root / "benchmark.yaml").write_text(
        yaml.safe_dump({"models": [{"name": "weg", "path": "models/weg.gguf",
                                    "profiles": [{"name": "GPU", "gpu_layers": -1}]}]}),
        encoding="utf-8",
    )
    result = bootstrap_config(
        root / "benchmark.yaml", root, root / "tools" / "llama.cpp", root / "models"
    )
    assert any("weg" in w for w in result["warnings"])
