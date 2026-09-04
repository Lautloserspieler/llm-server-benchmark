from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

SHARD_RE = re.compile(r"^(?P<prefix>.+)-(?P<index>\d{5})-of-(?P<count>\d{5})\.gguf$", re.IGNORECASE)


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


def _available_cpu_threads() -> int:
    """Ermittelt die fuer den Prozess wirklich nutzbaren logischen CPUs.

    Auf Linux respektiert sched_getaffinity() auch cpuset-/Container-Limits.
    Auf anderen Plattformen faellt die Erkennung auf os.cpu_count() zurueck.
    """
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or 1)


def _normalize_cpu_profile_threads(model: dict[str, Any]) -> bool:
    """Macht CPU-Only + threads:auto reproduzierbar und nutzt alle CPUs.

    llama.cpp waehlt bei fehlendem -t auf manchen Hybrid-CPUs absichtlich nur
    einen Teil der Kerne. Fuer einen CPU-Benchmark ist das unerwuenscht: auto
    bedeutet hier deshalb alle fuer den Prozess verfuegbaren logischen CPUs.
    Explizite Threadzahlen des Benutzers bleiben unveraendert.
    """
    changed = False
    profiles = model.get("profiles") or []
    for profile in profiles:
        try:
            gpu_layers = int(profile.get("gpu_layers", -1))
        except (TypeError, ValueError):
            continue
        threads = profile.get("threads", "auto")
        if gpu_layers == 0 and threads in (None, "auto", -1, "-1"):
            profile["threads"] = _available_cpu_threads()
            changed = True
    return changed


def shard_info(path: str | Path) -> tuple[str, int, int] | None:
    """Liefert (Basisname, Index, Anzahl) fuer gesplittete GGUF-Dateien."""
    match = SHARD_RE.match(Path(path).name)
    if not match:
        return None
    return match.group("prefix"), int(match.group("index")), int(match.group("count"))


def logical_model_path(path: str | Path) -> Path:
    """Normalisiert jeden Shard auf den ersten Shard, den llama.cpp erwartet."""
    p = Path(path)
    info = shard_info(p)
    if not info:
        return p
    prefix, _index, count = info
    return p.with_name(f"{prefix}-00001-of-{count:05d}.gguf")


def model_shards(path: str | Path) -> list[Path]:
    """Gibt alle zu einem logischen GGUF-Modell gehoerenden Dateien zurueck."""
    first = logical_model_path(path)
    info = shard_info(first)
    if not info:
        return [first] if first.exists() else []

    prefix, _index, count = info
    found: dict[int, Path] = {}
    for candidate in first.parent.glob(f"{prefix}-*-of-{count:05d}.gguf"):
        candidate_info = shard_info(candidate)
        if not candidate_info:
            continue
        candidate_prefix, candidate_index, candidate_count = candidate_info
        if candidate_prefix == prefix and candidate_count == count:
            found[candidate_index] = candidate
    return [found[index] for index in sorted(found)]


def shard_set_complete(path: str | Path) -> bool:
    info = shard_info(path)
    if not info:
        return Path(path).exists()
    _prefix, _index, count = info
    shards = model_shards(path)
    indices = {shard_info(item)[1] for item in shards if shard_info(item)}
    return len(shards) == count and indices == set(range(1, count + 1))


def _logical_stem(path: Path) -> str:
    info = shard_info(path)
    return info[0] if info else path.stem


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
        explicit = Path(explicit_dir)
        if not explicit.is_absolute():
            explicit = root / explicit
        candidates.append(explicit)
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


def _model_search_paths(root: Path, models_dir: Path | str | None, allow_system_search: bool) -> list[Path]:
    if models_dir:
        primary = Path(models_dir)
        if not primary.is_absolute():
            primary = root / primary
    else:
        primary = root / "models"

    search_paths = [primary]
    project_models = root / "models"
    if project_models.resolve() != primary.resolve():
        search_paths.append(project_models)

    if allow_system_search:
        if platform.system() == "Windows":
            search_paths.append(Path("C:/llm_models"))
        else:
            search_paths.append(Path("~/.cache/llama.cpp/models").expanduser())
    return search_paths


def discover_models(
    root: Path,
    models_dir: Path | str | None = None,
    allow_system_search: bool = False,
) -> list[Path]:
    """Findet logische GGUF-Modelle; Shard-Saetze erscheinen genau einmal.

    Bei `foo-00001-of-00012.gguf` bis `foo-00012-of-00012.gguf` wird nur der
    erste Shard als Modellpfad zurueckgegeben. Unvollstaendige Shard-Saetze
    werden bewusst nicht als testbares Modell gemeldet.
    """
    root = Path(root).resolve()
    logical: dict[Path, Path] = {}
    for directory in _model_search_paths(root, models_dir, allow_system_search):
        if not directory.exists() or not directory.is_dir():
            continue
        for file_path in directory.rglob("*.gguf"):
            first = logical_model_path(file_path).resolve()
            if shard_info(first) and not shard_set_complete(first):
                continue
            logical[first] = first
    return sorted(logical.values(), key=lambda p: (_logical_stem(p).lower(), str(p).lower()))


def _incomplete_shard_sets(root: Path, models_dir: Path | str | None, allow_system_search: bool) -> list[Path]:
    incomplete: set[Path] = set()
    for directory in _model_search_paths(root, models_dir, allow_system_search):
        if not directory.exists() or not directory.is_dir():
            continue
        for file_path in directory.rglob("*.gguf"):
            first = logical_model_path(file_path).resolve()
            if shard_info(first) and not shard_set_complete(first):
                incomplete.add(first)
    return sorted(incomplete, key=lambda p: str(p).lower())


def unique_model_name(path: Path, taken: set[str]) -> str:
    """Eindeutiger Modellname ohne Shard-Suffix."""
    stem = _logical_stem(path)
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
        "profiles": [
            {"name": "Full-GPU", "gpu_layers": -1, "threads": "auto"},
            {"name": "CPU-Only", "gpu_layers": 0, "threads": _available_cpu_threads()},
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

    Vorhandene Modelleintraege und explizite Profileinstellungen bleiben erhalten.
    CPU-Only-Profile mit ``threads: auto`` werden dagegen auf alle fuer den Prozess
    verfuegbaren logischen CPUs aufgeloest, damit llama.cpp auf Hybrid-CPUs nicht
    nur einen Teil der Kerne benchmarked. Alte, versehentlich eingetragene
    Folge-Shards werden automatisch entfernt.
    """
    root = Path(root).resolve()
    config_path = Path(config_path)
    if not config_path.is_absolute():
        config_path = root / config_path

    warnings: list[str] = []

    found_dir = discover_llama_binaries(root, llama_dir, allow_system_search)
    if found_dir:
        llama_dir_path = Path(found_dir)
    else:
        llama_dir_path = Path(llama_dir) if llama_dir else root / "tools" / "llama.cpp"
        if not llama_dir_path.is_absolute():
            llama_dir_path = root / llama_dir_path
        warnings.append(
            f"llama-bench und llama-server wurden unter {llama_dir_path} nicht gefunden. "
            "Die Pfade werden trotzdem eingetragen; 'llmbench doctor' pruefen."
        )
    llama_dir_path = llama_dir_path.resolve()

    models_dir_path = Path(models_dir) if models_dir else root / "models"
    if not models_dir_path.is_absolute():
        models_dir_path = root / models_dir_path
    models_dir_path = models_dir_path.resolve()
    models_dir_path.mkdir(parents=True, exist_ok=True)

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

    ext = ".exe" if (llama_dir_path / "llama-bench.exe").exists() else _exe_suffix()
    cfg.setdefault("tools", {})
    cfg["tools"]["llama_bench"] = str((llama_dir_path / f"llama-bench{ext}").resolve())
    cfg["tools"]["llama_server"] = str((llama_dir_path / f"llama-server{ext}").resolve())

    existing_raw = cfg.get("models") or []
    existing: list[dict[str, Any]] = []
    known_paths: set[str] = set()
    known_names: set[str] = set()

    for model in existing_raw:
        model = dict(model)
        if _normalize_cpu_profile_threads(model):
            warnings.append(
                f"CPU-Only-Profil von '{model.get('name', '?')}' nutzt automatisch "
                f"alle {_available_cpu_threads()} verfuegbaren CPU-Threads."
            )

        value = model.get("path")
        if not value:
            existing.append(model)
            if model.get("name"):
                known_names.add(str(model["name"]).lower())
            continue

        p = Path(value)
        if not p.is_absolute():
            p = root / p
        info = shard_info(p)
        if info and info[1] != 1:
            warnings.append(
                f"Alter Folge-Shard '{p.name}' wurde aus der Konfiguration entfernt; "
                "gesplittete GGUF-Modelle werden nur ueber Shard 00001 geladen."
            )
            continue

        p = logical_model_path(p)
        model["path"] = _rel_or_abs(p, root)
        existing.append(model)
        if model.get("name"):
            known_names.add(str(model["name"]).lower())
        known_paths.add(str(p.resolve()).lower())
        if not p.exists():
            warnings.append(f"Konfiguriertes Modell '{model.get('name')}' fehlt auf diesem Server: {p}")
        elif shard_info(p) and not shard_set_complete(p):
            warnings.append(f"Konfiguriertes Shard-Modell '{model.get('name')}' ist unvollstaendig: {p}")

    for first in _incomplete_shard_sets(root, models_dir_path, allow_system_search):
        info = shard_info(first)
        expected = info[2] if info else "?"
        found = len(model_shards(first))
        warnings.append(
            f"Unvollstaendiges GGUF-Shard-Set wird nicht eingebunden: {first.name} "
            f"({found}/{expected} Dateien vorhanden)."
        )

    discovered = discover_models(root, models_dir_path, allow_system_search)
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
        "models_dir": str(models_dir_path),
        "models_found": len(discovered),
        "models_added": added,
        "models_configured": len(existing),
        "llama_dir": str(llama_dir_path),
        "llama_binaries_found": bool(found_dir),
        "system_search": allow_system_search,
        "warnings": warnings,
    }
