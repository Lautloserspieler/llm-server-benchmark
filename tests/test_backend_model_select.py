from __future__ import annotations

from pathlib import Path

import yaml

from llmbench import backend_model_select


def test_write_ollama_model_replaces_incompatible_model_list(tmp_path: Path):
    cfg = tmp_path / "benchmark.yaml"
    cfg.write_text(
        "tools:\n  backend: ollama\nmodels:\n"
        "  - name: old\n    path: Qwen/Old\n    profiles:\n"
        "      - name: old\n        gpu_layers: -1\n",
        encoding="utf-8",
    )

    backend_model_select._write_runtime_models(cfg, "ollama", ["qwen3:8b"])

    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert [model["path"] for model in data["models"]] == ["qwen3:8b"]
    profiles = data["models"][0]["profiles"]
    assert any(profile["gpu_layers"] == -1 for profile in profiles)
    assert any(profile.get("ollama_num_gpu") == 0 for profile in profiles)


def test_write_vllm_model_uses_gpu_profile(tmp_path: Path):
    cfg = tmp_path / "benchmark.yaml"
    cfg.write_text("tools:\n  backend: vllm\n", encoding="utf-8")

    backend_model_select._write_runtime_models(cfg, "vllm", ["Qwen/Qwen3-8B"])

    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    model = data["models"][0]
    assert model["path"] == "Qwen/Qwen3-8B"
    assert model["profiles"][0]["tensor_parallel_size"] == 1
    assert model["profiles"][0]["gpu_layers"] == -1


def test_transformer_dirs_require_config_json(tmp_path: Path):
    valid = tmp_path / "valid"
    invalid = tmp_path / "invalid"
    valid.mkdir()
    invalid.mkdir()
    (valid / "config.json").write_text("{}", encoding="utf-8")
    (invalid / "weights.bin").write_bytes(b"x")

    assert backend_model_select._transformer_dirs(tmp_path) == [valid.resolve()]


def test_llama_selection_persists_only_selected_gguf(tmp_path: Path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir()
    model_file = models / "model.gguf"
    model_file.write_bytes(b"GGUF")
    cfg = tmp_path / "benchmark.yaml"
    cfg.write_text("tools:\n  backend: llama_cpp\n", encoding="utf-8")

    monkeypatch.setattr(backend_model_select, "ensure_model_selection", lambda *_a, **_k: ["Chosen"])
    monkeypatch.setattr(
        backend_model_select,
        "get_catalog_models",
        lambda: {"Chosen": {"repo_id": "x", "pattern": ["*.gguf"], "filename_hint": "model", "estimated_gib": 1.0}},
    )
    monkeypatch.setattr(backend_model_select, "find_downloaded_model", lambda *_a, **_k: model_file)

    selected = backend_model_select.select_models_for_backend(cfg, models)

    assert selected == [str(model_file)]
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert [model["path"] for model in data["models"]] == [str(model_file)]



def test_ollama_catalog_is_local_diverse_and_has_extreme():
    catalog = backend_model_select.OLLAMA_MODEL_CATALOG
    refs = [str(item["ref"]) for item in catalog]
    assert len(refs) == len(set(refs))
    assert all("-cloud" not in ref for ref in refs)
    assert {"gemma3:1b", "granite4.2:3b", "qwen3:8b", "gpt-oss:20b", "mistral-small3.2:24b"} <= set(refs)
    assert any(item["tier"] == "EXTREME" for item in catalog)


def test_ollama_catalog_selection_writes_selected_models(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "benchmark.yaml"
    cfg.write_text("tools:\n  backend: ollama\n", encoding="utf-8")
    models = tmp_path / "models"
    models.mkdir()

    monkeypatch.setattr(backend_model_select.console, "input", lambda *_args: "1,5")
    selected = backend_model_select.select_models_for_backend(cfg, models)

    assert selected == ["gemma3:1b", "gpt-oss:20b"]
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert [model["path"] for model in data["models"]] == selected


def test_ollama_all_standard_excludes_extreme(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "benchmark.yaml"
    cfg.write_text("tools:\n  backend: ollama\n", encoding="utf-8")
    models = tmp_path / "models"
    models.mkdir()

    monkeypatch.setattr(backend_model_select.console, "input", lambda *_args: "A")
    selected = backend_model_select.select_models_for_backend(cfg, models)

    extreme = {
        str(item["ref"])
        for item in backend_model_select.OLLAMA_MODEL_CATALOG
        if item["tier"] == "EXTREME"
    }
    assert selected
    assert extreme.isdisjoint(selected)


def test_ollama_custom_model_remains_supported(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "benchmark.yaml"
    cfg.write_text("tools:\n  backend: ollama\n", encoding="utf-8")
    models = tmp_path / "models"
    models.mkdir()

    answers = iter(["R", "qwen2.5:0.5b"])
    monkeypatch.setattr(backend_model_select.console, "input", lambda *_args: next(answers))
    selected = backend_model_select.select_models_for_backend(cfg, models)

    assert selected == ["qwen2.5:0.5b"]
