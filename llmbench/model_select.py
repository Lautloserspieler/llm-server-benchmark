"""Interaktive Auswahl der Standardmodelle fuer Setup und Docker."""

from __future__ import annotations

import argparse
from pathlib import Path

from .download import (
    download_models,
    find_downloaded_model,
    get_suite_models,
    load_model_selection,
    save_model_selection,
    verify_suite,
)


def parse_selection(value: str, model_names: list[str]) -> list[str]:
    """Parst '1,3,5', 'all/a' oder '0' in eine geordnete Modellauswahl."""
    raw = value.strip().lower()
    if raw in {"a", "all", "alle"}:
        return list(model_names)
    if raw in {"0", "none", "keine", "skip"}:
        return []

    selected: list[str] = []
    for part in (item.strip() for item in value.split(",")):
        if not part:
            continue
        if not part.isdigit():
            raise ValueError(f"Ungueltige Auswahl: '{part}'. Bitte Nummern mit Komma trennen.")
        index = int(part)
        if index < 1 or index > len(model_names):
            raise ValueError(f"Modellnummer {index} existiert nicht.")
        name = model_names[index - 1]
        if name not in selected:
            selected.append(name)
    if not selected and value.strip():
        raise ValueError("Keine gueltige Modellauswahl erkannt.")
    return selected


def _default_selection(model_names: list[str], saved: list[str] | None) -> str:
    if saved is not None:
        indices = [str(model_names.index(name) + 1) for name in saved if name in model_names]
        return ",".join(indices) if indices else "0"
    # Bandbreitenfreundlicher Standard: nur das erste kleine Modell (~6 GiB).
    return "1"


def prompt_model_selection(models_dir: str | Path) -> list[str]:
    models_root = Path(models_dir)
    models_root.mkdir(parents=True, exist_ok=True)
    catalog = get_suite_models("all")
    names = list(catalog)
    saved = load_model_selection(models_root)

    print("")
    print("====================================================")
    print("  Modell-Auswahl fuer den Benchmark")
    print("====================================================")
    print("Waehle nur die Modelle aus, die wirklich geladen werden sollen.")
    print("Mehrere Nummern mit Komma trennen, z.B. 1,2,3.")
    print("")

    for index, (name, config) in enumerate(catalog.items(), start=1):
        existing = find_downloaded_model(models_root, config)
        state = "vorhanden" if existing is not None else f"ca. {config['estimated_gib']:.0f} GiB Download"
        selected_mark = " *" if saved is not None and name in saved else ""
        print(f"  {index}: {name:<28} [{state}]{selected_mark}")

    total = sum(config["estimated_gib"] for config in catalog.values())
    print(f"  A: Alle Standardmodelle        [ca. {total:.0f} GiB gesamt]")
    print("  0: Keine neuen Standardmodelle laden (vorhandene/eigene Modelle verwenden)")
    print("")

    default = _default_selection(names, saved)
    while True:
        raw = input(f"Auswahl [Standard={default}]: ").strip() or default
        try:
            selected = parse_selection(raw, names)
        except ValueError as exc:
            print(f"[!] {exc}")
            continue

        missing_estimate = sum(
            catalog[name]["estimated_gib"]
            for name in selected
            if find_downloaded_model(models_root, catalog[name]) is None
        )
        if selected:
            print("")
            print("Ausgewaehlt: " + ", ".join(selected))
            if missing_estimate > 0:
                print(f"Voraussichtlich noch zu laden: ca. {missing_estimate:.0f} GiB")
            else:
                print("Alle ausgewaehlten Modelle sind bereits vorhanden.")
        else:
            print("")
            print("Es werden keine neuen Standardmodelle heruntergeladen.")
        return selected


def ensure_model_selection(models_dir: str | Path, force_select: bool = False) -> list[str]:
    """Waehlt Modelle, speichert die Auswahl und stellt nur diese Modelle bereit."""
    models_root = Path(models_dir)
    models_root.mkdir(parents=True, exist_ok=True)

    selected = None if force_select else load_model_selection(models_root)
    if selected is None:
        selected = prompt_model_selection(models_root)
        path = save_model_selection(models_root, selected)
        print(f"Auswahl gespeichert: {path}")

    if not selected:
        return []

    complete, missing = verify_suite(models_root, "all", model_names=selected)
    if complete:
        print("[OK] Alle ausgewaehlten Standardmodelle sind bereits vollstaendig vorhanden.")
        return selected

    print("Fehlend/unvollstaendig: " + ", ".join(missing))
    download_models(models_root, "all", model_names=selected)
    return selected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standardmodelle fuer llmbench gezielt auswaehlen")
    parser.add_argument("--models-dir", default="models")
    parser.add_argument(
        "--select",
        action="store_true",
        help="Auswahl auch dann erneut anzeigen, wenn bereits eine gespeicherte Auswahl existiert.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ensure_model_selection(args.models_dir, force_select=args.select)
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\nModellauswahl abgebrochen.")
        return 130
    except Exception as exc:
        print(f"Modellauswahl/Download fehlgeschlagen: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
