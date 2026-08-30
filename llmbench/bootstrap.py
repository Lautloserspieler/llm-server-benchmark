from __future__ import annotations

import hashlib
import platform
import shutil
from pathlib import Path
from typing import Any

import yaml


def _exe_suffix() -> str:
    return ".exe" if platform.system() == "Windows" else ""


def _rel_or_abs(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _has_binaries(directory: Path) -> bool:
    def present(stem: str) -> bool:
        # Beide Schreibweisen pruefen: ein Windows-Build kann auch von einer
        # anderen Umgebung aus inspiziert werden.
        return (directory / stem).exists() or (directory / f"{stem}.exe").exists()

    return present("llama-bench") and present("llama-server")


def discover_llama_binaries(
    root: Path | None = None,
    explicit_dir: Path | str | None = None,
    allow_system_search: bool = False,
) -> str | None:
    """Sucht llama-bench und llama-server.

    Standardmaessig ausschliesslich im Projekt. Eine systemweite Suche wuerde
    die bewusst eingefrorene llama.cpp still durch eine andere ersetzen und
    damit genau die Vergleichbarkeit zerstoeren, um die es hier geht.
    Sie ist deshalb nur noch per ausdruecklichem Opt-in erreichbar.
    """
    root = Path(root or Path.cwd()).resolve()
    candidates: list[Path] = []
    if explicit_dir:
        candidates.append(Path(explicit_dir))
    candidates.extend([root / "tools" / "llama.cpp", root / "bin"])

    for p in candidates:
        if p.exists() and p.is_dir() and _has_binaries(p):
            return str(p.resolve())

    if not allow_system_search:
        return None

    system_dirs = [Path("C:/llama.cpp")] if platform.system() == "Windows" else [
        Path("/usr/local/bin"),
        Path("/usr/bin"),
    ]
    for p in system_dirs:
        if p.exists() and p.is_dir() and _has_binaries(p):
            return str(p.resolve())

    bench = shutil.which("llama-bench")
    server = shutil.which("llama-server")
    if bench and server and Path(bench).parent == Path(server).parent:
        return str(Path(bench).parent.resolve())
    return None


def discover_models(
    root: Path,
    models_dir: Path | str | None = None,
    allow_system_search: bool = False,
) -> list[Path]:
    """Findet GGUF-Dateien unterhalb des Modellordners des Projekts.

    Systemweite Ablagen werden bewusst nicht mehr automatisch durchsucht:
    sonst bekommt jeder Server das Modellset, das dort zufaellig liegt.
    """
    search_paths: list[Path] = [Path(models_dir) if models_dir else root / "models"]
    if (root / "models") not in search_paths:
        search_paths.append(root / "models")

    if allow_system_search:
        if platform.system() == "Windows":
            search_paths.append(Path("C:/llm_models"))
        else:
            search_paths.append(Path("~/.cache/llama.cpp/models").expanduser())

    found: list[Path] = []
    for p in search_paths:
        if p.exists() and p.is_dir():
            found.extend(p.rglob("*.gguf"))
    unique = {f.resolve() for f in found}
    return sorted(unique, key=lambda p: p.name.lower())


def unique_model_name(path: Path, taken: set[str]) -> str:
    """Eindeutiger Modellname.

    Der Dateistamm allein reicht nicht: models/q4/mixtral.gguf und
    models/q8/mixtral.gguf ergaeben denselben Ergebnisordner, und der
    zweite Lauf ueberschriebe die Rohdaten des ersten.
    """
    stem = path.stem
    if stem.lower() not in taken:
        return stem
    parent = path.parent.name
    if parent:
        candidate = f"{stem}-{parent}"
        if candidate.lower() not in taken:
            return candidate
    digest = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:6]
    return f"{stem}-{digest}"


def _default_model_entry(path: Path, root: Path, name: str) -> dict[str, Any]:
    return {
        "name": name,
        "path": _rel_or_abs(path, root),
        # CPU-Only ist Voraussetzung fuer den Soak-Test (soak.cpu_profile/gpu_profile
        # werden sonst nicht automatisch gefunden) und macht nebenbei den reinen
        # CPU-Pfad direkt vergleichbar, ohne dass jemand von Hand ein Profil anlegt.
        "profiles": [
            {"name": "Full-GPU", "gpu_layers": -1, "threads": "auto"},
            {"name": "CPU-Only", "gpu_layers": 0, "threads": "auto"},
        ],
    }


def bootstrap_config(
    config_path: str | Path,
    root: str | Path,
    llama_dir: str | Path | None = None,
    models_dir: str | Path | None = None,
    allow_system_search: bool = False,
) -> dict[str, Any]:
    """Legt benchmark.yaml an oder ergaenzt sie und erkennt lokale GGUF-Modelle.

    Vorhandene Modelleintraege und Profileinstellungen bleiben erhalten.
    """
    root = Path(root).resolve()
    config_path = Path(config_path)
    if not config_path.is_absolute():
        config_path = root / config_path

    warnings: list[str] = []

    found_dir = discover_llama_binaries(root, llama_dir, allow_system_search)
    if found_dir:
        llama_dir = Path(found_dir)
    else:
        llama_dir = Path(llama_dir) if llama_dir else root / "tools" / "llama.cpp"
        warnings.append(
            f"llama-bench und llama-server wurden unter {llama_dir} nicht gefunden. "
            "Die Pfade werden trotzdem eingetragen; 'llmbench doctor' pruefen."
        )
    llama_dir = Path(llama_dir).resolve()

    models_dir = Path(models_dir) if models_dir else root / "models"
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
    cfg["project"].setdefault("hash_tools", True)

    ext = ".exe" if (llama_dir / "llama-bench.exe").exists() else _exe_suffix()
    cfg.setdefault("tools", {})
    cfg["tools"]["llama_bench"] = str((llama_dir / f"llama-bench{ext}").resolve())
    cfg["tools"]["llama_server"] = str((llama_dir / f"llama-server{ext}").resolve())

    existing = cfg.get("models") or []
    known_paths: set[str] = set()
    known_names: set[str] = set()
    for model in existing:
        if model.get("name"):
            known_names.add(str(model["name"]).lower())
        value = model.get("path")
        if not value:
            continue
        p = Path(value)
        if not p.is_absolute():
            p = root / p
        known_paths.add(str(p.resolve()).lower())
        if not p.exists():
            warnings.append(
                f"Konfiguriertes Modell '{model.get('name')}' fehlt auf diesem Server: {p}"
            )

    discovered = discover_models(root, models_dir, allow_system_search)
    added = 0
    for model_file in discovered:
        key = str(model_file.resolve()).lower()
        if key in known_paths:
            continue
        name = unique_model_name(model_file, known_names)
        existing.append(_default_model_entry(model_file, root, name))
        known_paths.add(key)
        known_names.add(name.lower())
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
        "llama_binaries_found": bool(found_dir),
        "system_search": allow_system_search,
        "warnings": warnings,
    }
