from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _rel_or_abs(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _default_model_entry(path: Path, root: Path) -> dict[str, Any]:
    return {
        "name": path.stem,
        "path": _rel_or_abs(path, root),
        "quality_gate": "Nicht bewertet",
        "profiles": [
            {
                "name": "Full-GPU",
                "gpu_layers": -1,
                "threads": "auto",
            }
        ],
    }


def bootstrap_config(
    config_path: str | Path,
    root: str | Path,
    llama_dir: str | Path,
    models_dir: str | Path,
) -> dict[str, Any]:
    """Create/update benchmark.yaml and discover local GGUF models.

    Existing user model entries and profile settings are preserved. New GGUF files
    found below models_dir are added with a conservative Full-GPU profile.
    """
    root = Path(root).resolve()
    config_path = Path(config_path)
    if not config_path.is_absolute():
        config_path = root / config_path
    llama_dir = Path(llama_dir).resolve()
    models_dir = Path(models_dir).resolve()
    models_dir.mkdir(parents=True, exist_ok=True)

    template = root / "benchmark.example.yaml"
    if config_path.exists():
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    elif template.exists():
        cfg = yaml.safe_load(template.read_text(encoding="utf-8")) or {}
    else:
        cfg = {}

    cfg.setdefault("project", {})
    cfg["project"].setdefault("name", "Firmenweiter LLM Server Benchmark")
    cfg["project"].setdefault("server_name", None)
    cfg["project"].setdefault("output_dir", "results")
    cfg["project"].setdefault("hash_models", True)

    exe = ".exe" if (llama_dir / "llama-bench.exe").exists() else ""
    cfg.setdefault("tools", {})
    cfg["tools"]["llama_bench"] = str((llama_dir / f"llama-bench{exe}").resolve())
    cfg["tools"]["llama_server"] = str((llama_dir / f"llama-server{exe}").resolve())

    existing = cfg.get("models") or []
    known_paths: set[str] = set()
    for model in existing:
        value = model.get("path")
        if not value:
            continue
        p = Path(value)
        if not p.is_absolute():
            p = root / p
        known_paths.add(str(p.resolve()).lower())

    discovered = sorted(models_dir.rglob("*.gguf"), key=lambda p: p.name.lower())
    added = 0
    for model_file in discovered:
        key = str(model_file.resolve()).lower()
        if key in known_paths:
            continue
        existing.append(_default_model_entry(model_file, root))
        known_paths.add(key)
        added += 1

    cfg["models"] = existing
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True, width=120),
        encoding="utf-8",
    )

    return {
        "config": str(config_path.resolve()),
        "models_dir": str(models_dir),
        "models_found": len(discovered),
        "models_added": added,
        "models_configured": len(existing),
        "llama_dir": str(llama_dir),
    }
