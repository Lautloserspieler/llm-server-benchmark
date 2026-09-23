"""Interaktive Auswahl der Standardmodelle fuer Setup und Docker."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich import box
from rich.markup import escape
from rich.table import Table

from .download import (
    download_models,
    find_downloaded_model,
    get_suite_models,
    load_model_selection,
    save_model_selection,
    verify_suite,
)
from .i18n import _
from .utils import console


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
            raise ValueError(_("Ungueltige Auswahl: '{part}'. Bitte Nummern mit Komma trennen.").format(part=part))
        index = int(part)
        if index < 1 or index > len(model_names):
            raise ValueError(_("Modellnummer {index} existiert nicht.").format(index=index))
        name = model_names[index - 1]
        if name not in selected:
            selected.append(name)
    if not selected and value.strip():
        raise ValueError(_("Keine gueltige Modellauswahl erkannt."))
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

    console.print()
    console.print(_("Waehle nur die Modelle aus, die wirklich geladen werden sollen."))
    console.print(_("Mehrere Nummern mit Komma trennen, z.B. 1,2,3."), style="dim")

    table = Table(box=box.ROUNDED, border_style="cyan", header_style="bold cyan")
    table.add_column("#", justify="right", style="bold")
    table.add_column(_("Modell"))
    table.add_column(_("Status"))
    for index, (name, config) in enumerate(catalog.items(), start=1):
        existing = find_downloaded_model(models_root, config)
        if existing is not None:
            state = "[green]" + _("vorhanden") + "[/green]"
        else:
            state = _("ca. {gib} GiB Download").format(gib=f"{config['estimated_gib']:.0f}")
        mark = " [cyan]*[/cyan]" if saved is not None and name in saved else ""
        table.add_row(str(index), name + mark, state)

    total = sum(config["estimated_gib"] for config in catalog.values())
    table.add_row("A", _("Alle Standardmodelle"), _("ca. {gib} GiB gesamt").format(gib=f"{total:.0f}"))
    table.add_row("0", _("Keine neuen Standardmodelle laden"), _("vorhandene/eigene Modelle verwenden"))
    console.print(table)

    default = _default_selection(names, saved)
    while True:
        prompt = _("Auswahl [Standard={default}]: ").format(default=default)
        raw = console.input(f"[magenta]\\[?][/magenta] {escape(prompt)}").strip() or default
        try:
            selected = parse_selection(raw, names)
        except ValueError as exc:
            console.print(f"[yellow]\\[!][/yellow] {escape(str(exc))}")
            continue

        missing_estimate = sum(
            catalog[name]["estimated_gib"]
            for name in selected
            if find_downloaded_model(models_root, catalog[name]) is None
        )
        console.print()
        if selected:
            console.print(_("Ausgewaehlt: {names}").format(names=", ".join(selected)))
            if missing_estimate > 0:
                console.print(
                    _("Voraussichtlich noch zu laden: ca. {gib} GiB").format(gib=f"{missing_estimate:.0f}"),
                    style="dim",
                )
            else:
                console.print(_("Alle ausgewaehlten Modelle sind bereits vorhanden."), style="green")
        else:
            console.print(_("Es werden keine neuen Standardmodelle heruntergeladen."))
        return selected


def ensure_model_selection(models_dir: str | Path, force_select: bool = False) -> list[str]:
    """Waehlt Modelle, speichert die Auswahl und stellt nur diese Modelle bereit."""
    models_root = Path(models_dir)
    models_root.mkdir(parents=True, exist_ok=True)

    selected = None if force_select else load_model_selection(models_root)
    if selected is None:
        selected = prompt_model_selection(models_root)
        path = save_model_selection(models_root, selected)
        console.print(_("Auswahl gespeichert: {path}").format(path=path), style="dim")

    if not selected:
        return []

    complete, missing = verify_suite(models_root, "all", model_names=selected)
    if complete:
        console.print("[green]\\[OK][/green] " + _("Alle ausgewaehlten Standardmodelle sind bereits vollstaendig vorhanden."))
        return selected

    console.print(_("Fehlend/unvollstaendig: {names}").format(names=", ".join(missing)))
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
        console.print("\n" + _("Modellauswahl abgebrochen."), style="yellow")
        return 130
    except Exception as exc:
        console.print("[red]\\[X][/red] " + escape(_("Modellauswahl/Download fehlgeschlagen: {error}").format(error=exc)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
