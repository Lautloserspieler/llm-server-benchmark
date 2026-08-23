from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _rel_or_abs(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def discover_llama_binaries() -> str | None:
    """Search common system paths for llama-bench and llama-server.
    Returns the directory containing both, or None.
    """
    import os
    import platform
    ext = ".exe" if platform.system() == "Windows" else ""

    search_paths = [
        Path("."),
        Path("tools/llama.cpp"),
        Path("bin"),
        Path("C:/llama.cpp") if platform.system() == "Windows" else None,
        Path("/usr/local/bin") if platform.system() != "Windows" else None,
        Path("/usr/bin") if platform.system() != "Windows" else None,
    ]

    for p in filter(None, search_paths):
        if p.exists() and p.is_dir():
            if (p / f"llama-bench{ext}").exists() and (p / f"llama-server{ext}").exists():
                return str(p.resolve())

    # Also check if they are in the system PATH
    import shutil
    bench = shutil.which("llama-bench")
    server = shutil.which("llama-server")
    if bench and server:
        parent = Path(bench).parent
        if (parent / Path(server).name).exists():
            return str(parent.resolve())

    return None


def discover_models(root: Path, custom_paths: list[str] | None = None) -> list[Path]:
    """Recursively find all .gguf files in specified paths.
    """
    search_paths = [root / "models"]
    if custom_paths:
        search_paths.extend([Path(p) for p in custom_paths])

    # Add common system paths
    import platform
    if platform.system() == "Windows":
        search_paths.append(Path("C:/llm_models"))
    else:
        search_paths.append(Path("~/.cache/llama.cpp/models").expanduser())

    found = []
    for p in search_paths:
        if p.exists() and p.is_dir():
            found.extend(p.rglob("*.gguf"))

    return sorted(list(set(found)), key=lambda p: p.name.lower())


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
    llama_dir: str | Path | None = None,
    models_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Create/update benchmark.yaml and discover local GGUF models.

    Existing user model entries and profile settings are preserved. New GGUF files
    found below models_dir are added with a conservative Full-GPU profile.
    """
    root = Path(root).resolve()
    config_path = Path(config_path)
    if not config_path.is_absolute():
        config_path = root / config_path

    # 1. Tool Discovery
    if llama_dir is None or not Path(llama_dir).exists():
        found_dir = discover_llama_binaries()
        llama_dir = Path(found_dir) if found_dir else (Path(llama_dir) if llama_dir else Path("tools/llama.cpp"))
    llama_dir = Path(llama_dir).resolve()

    # 2. Model Discovery
    if models_dir is None or not Path(models_dir).exists():
        models_dir = Path(root) / "models"
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

    discovered = discover_models(root, custom_paths=[str(models_dir)])
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
