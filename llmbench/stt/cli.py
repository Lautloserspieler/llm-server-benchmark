"""Experimentelles CLI fuer den STT-Prototypen.

Aufrufbar ueber `python -m llmbench.stt.cli --config config.yaml`. Ist bewusst
separat von `llmbench run`, damit der Prototyp nicht die stabile Pipeline
beruehrt.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..config import load_config
from ..i18n import _, set_language
from ..utils import console
from .config import STTConfig
from .runner import run_stt_benchmark


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=_("STT-Benchmark-Prototyp"))
    parser.add_argument("--config", "-c", required=True, help=_("Pfad zur llmbench-Konfiguration"))
    parser.add_argument("--output", "-o", default=None, help=_("Ergebnisverzeichnis (Default aus config)"))
    parser.add_argument("--max-samples", type=int, default=None, help=_("Maximale Anzahl Samples"))
    parser.add_argument("--lang", default=None, help=_("Sprache fuer Meldungen"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    raw_cfg = load_config(args.config)

    if args.lang:
        set_language(args.lang)
        raw_cfg.setdefault("project", {})["language"] = args.lang

    stt_cfg = STTConfig(**raw_cfg.get("stt", {}))
    if args.max_samples is not None:
        stt_cfg.max_samples = args.max_samples

    output_dir = Path(args.output) if args.output else Path(raw_cfg.get("project", {}).get("output_dir", "results"))

    def on_progress(message: str, state: dict | None):
        console.print(f"[dim]{message}[/dim]")

    result = run_stt_benchmark(stt_cfg, output_dir, on_progress=on_progress)
    if result.get("status") != "ok":
        console.print(f"[red]{result.get('reason', 'STT fehlgeschlagen')}[/red]")
        return 1

    console.print(_("STT-Benchmark abgeschlossen. Ergebnisse in {path}").format(path=output_dir / stt_cfg.output_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
