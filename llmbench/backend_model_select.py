"""Backend-spezifische Modellauswahl fuer Setup und Start-Workflow."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml
from rich import box
from rich.markup import escape
from rich.table import Table

from .bootstrap import discover_models
from .i18n import _
from .download import find_downloaded_model, get_catalog_models
from .model_select import ensure_model_selection
from .utils import console


# Kuratierte, lokale Ollama-Library-Modelle fuer den Text-Benchmark.
# Die Liste bleibt bewusst kleiner als die komplette Ollama-Library: dort gibt es
# hunderte lokale Modelle, darunter Embedding-/Decision-/Vision-Spezialmodelle.
# estimated_gib entspricht der ungefaehren Downloadgroesse des jeweiligen
# Standard-Tags auf ollama.com (Stand Oktober 2026).
OLLAMA_MODEL_CATALOG: tuple[dict[str, Any], ...] = (
    {"name": "Gemma 3 1B", "ref": "gemma3:1b", "estimated_gib": 0.8, "tier": "SMALL"},
    {"name": "Granite 4.2 3B", "ref": "granite4.2:3b", "estimated_gib": 2.2, "tier": "SMALL"},
    {"name": "Qwen3 8B", "ref": "qwen3:8b", "estimated_gib": 5.2, "tier": "SMALL"},
    {"name": "DeepSeek-R1 14B", "ref": "deepseek-r1:14b", "estimated_gib": 9.0, "tier": "MID"},
    {"name": "GPT-OSS 20B", "ref": "gpt-oss:20b", "estimated_gib": 14.0, "tier": "MID"},
    {"name": "Mistral Small 3.2 24B", "ref": "mistral-small3.2:24b", "estimated_gib": 15.0, "tier": "MID"},
    {"name": "Qwen3.8 27B", "ref": "qwen3.8:27b", "estimated_gib": 18.0, "tier": "HEAVY"},
    {"name": "DeepSeek-R1 70B", "ref": "deepseek-r1:70b", "estimated_gib": 43.0, "tier": "HEAVY"},
    {"name": "GPT-OSS 120B", "ref": "gpt-oss:120b", "estimated_gib": 65.0, "tier": "HEAVY"},
    {"name": "Qwen3 235B", "ref": "qwen3:235b", "estimated_gib": 142.0, "tier": "EXTREME"},
)


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _save_config(path: Path, cfg: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")


def _backend(cfg: dict[str, Any]) -> str:
    return str((cfg.get("tools") or {}).get("backend") or "llama_cpp")


def _transformer_dirs(models_dir: Path) -> list[Path]:
    if not models_dir.exists():
        return []
    found = {file.parent.resolve() for file in models_dir.rglob("config.json") if file.is_file()}
    return sorted(found, key=lambda item: str(item).lower())


def _existing_remote_refs(cfg: dict[str, Any], backend: str) -> list[str]:
    refs: list[str] = []
    for model in cfg.get("models") or []:
        if not isinstance(model, dict):
            continue
        value = str(model.get("path") or "").strip()
        if not value:
            continue
        p = Path(value)
        if p.exists() or p.is_absolute() or value.startswith((".", "~")):
            continue
        if backend in {"vllm", "tgi"} and "/" not in value:
            continue
        if value not in refs:
            refs.append(value)
    return refs


def _default_profiles(backend: str) -> list[dict[str, Any]]:
    if backend == "llama_cpp":
        return [
            {"name": "Full-GPU", "gpu_layers": -1, "threads": "auto"},
            {"name": "CPU-Only", "gpu_layers": 0, "threads": "auto"},
        ]
    if backend == "ollama":
        return [
            {"name": "Ollama-GPU", "gpu_layers": -1, "ollama_num_ctx": 32768},
            {"name": "Ollama-CPU", "gpu_layers": 0, "ollama_num_ctx": 32768, "ollama_num_gpu": 0},
        ]
    if backend == "vllm":
        return [{"name": "vLLM-1GPU", "gpu_layers": -1, "tensor_parallel_size": 1, "gpu_memory_utilization": 0.90}]
    if backend == "tgi":
        return [{"name": "TGI-1GPU", "gpu_layers": -1, "tensor_parallel_size": 1}]
    raise ValueError(f"Unsupported backend: {backend}")


def _model_name(reference: str) -> str:
    text = reference.rstrip("/\\")
    leaf = text.replace("\\", "/").split("/")[-1]
    return leaf or "model"


def _write_runtime_models(config_path: Path, backend: str, references: list[str]) -> None:
    cfg = _load_config(config_path)
    models: list[dict[str, Any]] = []
    used: set[str] = set()
    for reference in references:
        base = _model_name(reference)
        name = base
        suffix = 2
        while name.lower() in used:
            name = f"{base}-{suffix}"
            suffix += 1
        used.add(name.lower())
        models.append({"name": name, "path": reference, "profiles": _default_profiles(backend)})
    cfg["models"] = models
    _save_config(config_path, cfg)


def _prompt_ollama_models(config_path: Path, models_dir: Path) -> list[str]:
    local = [str(path) for path in discover_models(models_dir.resolve(), models_dir.resolve())]
    cfg = _load_config(config_path)
    previous = _existing_remote_refs(cfg, "ollama")

    catalog_refs = [str(item["ref"]) for item in OLLAMA_MODEL_CATALOG]
    custom_previous = [value for value in previous if value not in catalog_refs]

    console.print()
    console.print(_("Waehle Ollama-Modelle fuer den Benchmark."), style="bold cyan")
    console.print(
        _("Mehrere Nummern mit Komma trennen, z. B. 1,3,5. Eigene Ollama-Modelle bleiben ueber R moeglich."),
        style="dim",
    )

    table = Table(box=box.ROUNDED, border_style="cyan", header_style="bold cyan")
    table.add_column("#", justify="right", style="bold")
    table.add_column(_("Modell"))
    table.add_column(_("Status"))

    choices: list[str] = []
    for index, item in enumerate(OLLAMA_MODEL_CATALOG, start=1):
        ref = str(item["ref"])
        tier = str(item["tier"])
        name = str(item["name"])
        gib = float(item["estimated_gib"])
        suffix = " [EXTREME]" if tier == "EXTREME" else ""
        table.add_row(str(index), name + suffix, _("ca. {gib:g} GB Download").format(gib=gib))
        choices.append(ref)

    next_index = len(choices) + 1
    for value in local:
        table.add_row(str(next_index), _model_name(value), _("lokale GGUF-Datei"))
        choices.append(value)
        next_index += 1

    for value in custom_previous:
        table.add_row(str(next_index), value, _("bereits konfigurierte Modell-ID"))
        choices.append(value)
        next_index += 1

    standard_refs = [
        str(item["ref"]) for item in OLLAMA_MODEL_CATALOG if item["tier"] != "EXTREME"
    ]
    standard_gib = sum(
        float(item["estimated_gib"]) for item in OLLAMA_MODEL_CATALOG if item["tier"] != "EXTREME"
    )
    table.add_row(
        "A",
        _("Alle Standardmodelle (ohne Extreme)"),
        _("ca. {gib:g} GB gesamt").format(gib=standard_gib),
    )
    table.add_row(
        "R",
        _("Eigenes Ollama-Modell"),
        _("Modellname eingeben, z. B. qwen2.5:0.5b"),
    )
    table.add_row("0", _("Keine Modelle konfigurieren"), _("Konfiguration bleibt ohne Modelle"))
    console.print(table)

    default = "1"
    while True:
        raw = console.input(
            "[magenta]\\[?][/magenta] "
            + escape(_("Auswahl [Standard={default}]: ").format(default=default))
        ).strip() or default
        lowered = raw.lower()

        if lowered == "0":
            _write_runtime_models(config_path, "ollama", [])
            return []

        if lowered == "a":
            _write_runtime_models(config_path, "ollama", standard_refs)
            return standard_refs

        if lowered == "r":
            value = console.input(
                "[magenta]\\[?][/magenta] "
                + escape(_("Ollama-Modellname, z. B. qwen3:8b") + ": ")
            ).strip()
            if not value:
                console.print(_("Bitte eine Modell-ID angeben."), style="yellow")
                continue
            _write_runtime_models(config_path, "ollama", [value])
            return [value]

        selected: list[str] = []
        valid = True
        for part in (item.strip() for item in raw.split(",")):
            if not part.isdigit():
                valid = False
                break
            index = int(part)
            if index < 1 or index > len(choices):
                valid = False
                break
            value = choices[index - 1]
            if value not in selected:
                selected.append(value)

        if not valid or not selected:
            console.print(_("Ungueltige Modellauswahl."), style="yellow")
            continue

        _write_runtime_models(config_path, "ollama", selected)
        return selected


def _prompt_runtime_models(backend: str, config_path: Path, models_dir: Path) -> list[str]:
    if backend == "ollama":
        return _prompt_ollama_models(config_path, models_dir)

    local = [str(path) for path in _transformer_dirs(models_dir)]
    remote_label = _("Hugging-Face-Repo-ID, z. B. Qwen/Qwen3-8B")
    source_label = _("lokales Transformers-Verzeichnis")

    cfg = _load_config(config_path)
    previous = _existing_remote_refs(cfg, backend)

    console.print()
    console.print(_("Waehle ein Modell passend zum Backend {backend}.").format(backend=backend), style="bold cyan")
    table = Table(box=box.ROUNDED, border_style="cyan", header_style="bold cyan")
    table.add_column("#", justify="right", style="bold")
    table.add_column(_("Modell"))
    table.add_column(_("Quelle"))
    for index, value in enumerate(local, start=1):
        table.add_row(str(index), _model_name(value), source_label)
    for offset, value in enumerate(previous, start=len(local) + 1):
        table.add_row(str(offset), value, _("bereits konfigurierte Modell-ID"))
    table.add_row("R", remote_label, _("Runtime laedt das Modell bei Bedarf"))
    table.add_row("0", _("Keine Modelle konfigurieren"), _("Konfiguration bleibt ohne Modelle"))
    console.print(table)

    choices = local + previous
    default = "1" if choices else "R"
    while True:
        raw = console.input(
            "[magenta]\\[?][/magenta] "
            + escape(_("Auswahl [Standard={default}]: ").format(default=default))
        ).strip() or default
        if raw.lower() == "0":
            _write_runtime_models(config_path, backend, [])
            return []
        if raw.lower() == "r":
            value = console.input("[magenta]\\[?][/magenta] " + escape(remote_label + ": ")).strip()
            if not value:
                console.print(_("Bitte eine Modell-ID angeben."), style="yellow")
                continue
            _write_runtime_models(config_path, backend, [value])
            return [value]

        selected: list[str] = []
        valid = True
        for part in (item.strip() for item in raw.split(",")):
            if not part.isdigit():
                valid = False
                break
            index = int(part)
            if index < 1 or index > len(choices):
                valid = False
                break
            value = choices[index - 1]
            if value not in selected:
                selected.append(value)
        if not valid or not selected:
            console.print(_("Ungueltige Modellauswahl."), style="yellow")
            continue
        _write_runtime_models(config_path, backend, selected)
        return selected


def select_models_for_backend(
    config_path: str | Path = "benchmark.yaml",
    models_dir: str | Path = "models",
    *,
    force_select: bool = True,
) -> list[str]:
    config = Path(config_path)
    root = config.resolve().parent
    models = Path(models_dir)
    if not models.is_absolute():
        models = root / models
    models.mkdir(parents=True, exist_ok=True)

    cfg = _load_config(config)
    backend = _backend(cfg)
    if backend == "llama_cpp":
        selected = ensure_model_selection(models, force_select=force_select)
        catalog = get_catalog_models()
        references: list[str] = []
        for name in selected:
            model_path = find_downloaded_model(models, catalog[name])
            if model_path is not None:
                references.append(str(model_path))
        _write_runtime_models(config, backend, references)
        return references
    if backend not in {"ollama", "vllm", "tgi"}:
        raise ValueError(_("Unbekanntes Backend: {backend}").format(backend=backend))
    return _prompt_runtime_models(backend, config, models)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=_("Backend-spezifische Modellauswahl"))
    parser.add_argument("--config", default="benchmark.yaml")
    parser.add_argument("--models-dir", default="models")
    parser.add_argument("--reuse", action="store_true", help=_("Gespeicherte llama.cpp-Auswahl wiederverwenden"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        select_models_for_backend(args.config, args.models_dir, force_select=not args.reuse)
        return 0
    except (EOFError, KeyboardInterrupt):
        console.print("\n" + _("Modellauswahl abgebrochen."), style="yellow")
        return 130
    except Exception as exc:
        console.print("[red]\\[X][/red] " + escape(_("Modellauswahl fehlgeschlagen: {error}").format(error=exc)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
