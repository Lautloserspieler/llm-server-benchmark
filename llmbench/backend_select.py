"""Backend-Auswahl im Setup.

llama.cpp ist immer dabei. Die Container-Backends (vLLM, spaeter TGI/Ollama)
sind mehrere Gigabyte gross - deshalb wird fuer jedes einzeln gefragt, bevor
ein Image geladen wird. Anschliessend kann das Backend gewaehlt werden, mit dem
der Benchmark standardmaessig laeuft (``tools.backend`` in benchmark.yaml).

LLMBENCH_AUTO_INSTALL=1 beantwortet die Installationsfragen mit Ja, =0 mit Nein;
ohne Terminal wird nichts installiert.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from rich import box
from rich.markup import escape
from rich.table import Table

from . import backend_setup, docker_backend
from .backends import DEFAULT_BACKEND
from .bootstrap import read_config_file, set_default_backend
from .i18n import _
from .utils import ask_yes_no, console, print_err, print_msg, print_section

# Ungefaehre Download-Groesse der Standard-Images, nur fuer die Rueckfrage.
BACKEND_DOWNLOAD_GIB: dict[str, int] = {
    "vllm": 10,
}

# Backends, deren Container immer mit --gpus starten (NVIDIA-only).
NVIDIA_ONLY_BACKENDS = frozenset({"vllm"})

BACKEND_LABELS: dict[str, str] = {
    "llama_cpp": "llama.cpp",
    "vllm": "vLLM",
}


def _label(name: str) -> str:
    return BACKEND_LABELS.get(name, name)


def _interactive() -> bool:
    return sys.stdin.isatty()


def _confirm_install(name: str) -> bool:
    auto = os.environ.get("LLMBENCH_AUTO_INSTALL")
    if auto == "1":
        print_msg(_("{name} wird installiert (LLMBENCH_AUTO_INSTALL=1).").format(name=_label(name)))
        return True
    if auto == "0" or not _interactive():
        return False
    question = _("{name} installieren? (ca. {gib} GB Download)").format(
        name=_label(name), gib=BACKEND_DOWNLOAD_GIB.get(name, "?")
    )
    return ask_yes_no(question, default=False)


def _usable(name: str, docker_ok: bool, gpu_ok: bool) -> bool:
    return docker_ok and (gpu_ok or name not in NVIDIA_ONLY_BACKENDS)


def _status_table(root: Path, docker_ok: bool, gpu_ok: bool) -> Table:
    table = Table(box=box.ROUNDED, border_style="cyan", header_style="bold cyan")
    table.add_column(_("Backend"))
    table.add_column(_("Status"))
    table.add_column(_("Download"), justify="right")
    table.add_row("llama.cpp", "[green]" + _("immer dabei") + "[/green]", "—")
    for name in backend_setup.SUPPORTED_BACKENDS:
        if backend_setup.is_installed(name, root):
            state = "[green]" + _("installiert") + "[/green]"
        elif not docker_ok:
            state = "[yellow]" + _("braucht Docker") + "[/yellow]"
        elif not _usable(name, docker_ok, gpu_ok):
            state = "[yellow]" + _("braucht NVIDIA-GPU in Docker") + "[/yellow]"
        else:
            state = _("nicht installiert")
        table.add_row(_label(name), state, f"~{BACKEND_DOWNLOAD_GIB.get(name, '?')} GB")
    return table


def _choose_default(config_path: Path, available: list[str]) -> None:
    cfg = read_config_file(config_path)
    current = (cfg.get("tools") or {}).get("backend") or DEFAULT_BACKEND
    if current not in available:
        current = DEFAULT_BACKEND
    if not _interactive():
        return
    console.print()
    console.print(_("Mit welchem Backend soll der Benchmark standardmaessig laufen?"))
    for index, name in enumerate(available, start=1):
        marker = "[cyan]>[/cyan]" if name == current else " "
        console.print(f"  {marker} {index}) {_label(name)}")
    default_index = available.index(current) + 1
    prompt = _("Auswahl [1-{count}, Enter = {default}]: ").format(count=len(available), default=default_index)
    answer = console.input("  " + escape(prompt)).strip()
    choice = current
    if answer.isdigit() and 1 <= int(answer) <= len(available):
        choice = available[int(answer) - 1]
    if choice != (cfg.get("tools") or {}).get("backend"):
        set_default_backend(config_path, choice)
    print_msg(_("Standard-Backend: {name}").format(name=_label(choice)), style="green")


def select_backends(root: Path | str, config_path: Path | str) -> int:
    root = Path(root).resolve()
    config_path = Path(config_path)
    if not config_path.is_absolute():
        config_path = root / config_path

    print_section(_("Backends"))
    docker_ok = docker_backend.docker_available()
    gpu_ok = docker_ok and docker_backend.nvidia_runtime_available()
    console.print(_status_table(root, docker_ok, gpu_ok))

    missing = [name for name in backend_setup.SUPPORTED_BACKENDS if not backend_setup.is_installed(name, root)]
    if missing and not docker_ok:
        print_msg(
            _(
                "Docker ist nicht erreichbar - Container-Backends lassen sich erst installieren, "
                "wenn Docker laeuft (spaeter: llmbench install-backend --backend <name>)."
            ),
            style="yellow",
        )

    # Ein optionales Backend, das nicht installiert werden konnte, bricht das
    # Setup nicht ab - llama.cpp funktioniert trotzdem.
    if docker_ok and not gpu_ok and any(name in NVIDIA_ONLY_BACKENDS for name in missing):
        print_msg(
            _(
                "vLLM braucht eine NVIDIA-GPU, die Docker an Container durchreicht "
                "(NVIDIA-Treiber + NVIDIA Container Toolkit) - wird hier nicht angeboten."
            ),
            style="yellow",
        )

    for name in [n for n in missing if _usable(n, docker_ok, gpu_ok)]:
        if not _confirm_install(name):
            continue
        try:
            backend_setup.ensure_backend(name, root, log=lambda msg: print_msg(msg, style="dim"))
            print_msg(_("{name} ist installiert.").format(name=_label(name)), style="green")
        except Exception as exc:
            print_err(_("{name} konnte nicht installiert werden: {error}").format(name=_label(name), error=exc))

    available = [DEFAULT_BACKEND] + [
        name for name in backend_setup.SUPPORTED_BACKENDS if backend_setup.is_installed(name, root)
    ]
    # Ein eingetragenes, aber nicht (mehr) installiertes Backend wuerde beim
    # naechsten Lauf scheitern oder das abgelehnte Image doch noch laden.
    configured = (read_config_file(config_path).get("tools") or {}).get("backend")
    if configured and configured not in available:
        set_default_backend(config_path, DEFAULT_BACKEND)
        print_msg(
            _("{name} ist nicht installiert - Standard-Backend wieder auf {default} gesetzt.").format(
                name=_label(configured), default=_label(DEFAULT_BACKEND)
            ),
            style="yellow",
        )
    if len(available) > 1:
        _choose_default(config_path, available)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=_("Backends fuer den Benchmark auswaehlen und installieren"))
    parser.add_argument("--root", default=".")
    parser.add_argument("--config", default="benchmark.yaml")
    args = parser.parse_args(argv)
    try:
        return select_backends(args.root, args.config)
    except (EOFError, KeyboardInterrupt):
        console.print("\n" + _("Backend-Auswahl abgebrochen."), style="yellow")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
