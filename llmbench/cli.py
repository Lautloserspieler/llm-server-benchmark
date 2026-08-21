from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .compare import compare_summaries
from .bootstrap import bootstrap_config
from .config import load_config, save_example, validate_config
from .doctor import doctor
from .runner import run_suite


def _print_doctor(data: dict) -> int:
    print("\nTools")
    print("-----")
    failed = False
    for x in data["checks"]:
        mark = "OK" if x["ok"] else "FEHLT"
        print(f"[{mark:5}] {x['name']}: {x.get('resolved') or x.get('configured')}")
        failed = failed or not x["ok"]
    print("\nModelle")
    print("-------")
    for x in data["models"]:
        mark = "OK" if x["exists"] else "FEHLT"
        print(f"[{mark:5}] {x['name']}: {x['path']}")
        failed = failed or not x["exists"]
    hw = data["hardware"]
    print("\nHardware")
    print("--------")
    print(f"CPU: {hw.get('cpu',{}).get('name')}")
    print(f"RAM: {(hw.get('memory',{}).get('total_bytes') or 0)/(1024**3):.1f} GiB")
    for gpu in hw.get("gpus", []):
        print(f"GPU: {gpu.get('name')} – {gpu.get('memory.total')} MiB VRAM")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="llmbench", description="Reproduzierbarer LLM-Server-Benchmark")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    init = sub.add_parser("init", help="Beispielkonfiguration erzeugen")
    init.add_argument("--output", default="benchmark.yaml")

    doc = sub.add_parser("doctor", help="Installation, Hardware und Modellpfade prüfen")
    doc.add_argument("--config", default="benchmark.yaml")
    doc.add_argument("--json", action="store_true", dest="as_json")

    run = sub.add_parser("run", help="Benchmark-Suite ausführen")
    run.add_argument("--config", default="benchmark.yaml")
    run.add_argument("--model", default=None, help="Nur ein benanntes Modell testen")
    run.add_argument("--skip-endpoint", action="store_true")

    boot = sub.add_parser("bootstrap", help="Lokale Tools eintragen und GGUF-Modelle automatisch erkennen")
    boot.add_argument("--config", default="benchmark.yaml")
    boot.add_argument("--root", default=".")
    boot.add_argument("--llama-dir", default="tools/llama.cpp")
    boot.add_argument("--models-dir", default="models")

    comp = sub.add_parser("compare", help="Mehrere Server-Runs vergleichen")
    comp.add_argument("inputs", nargs="+", help="Run-Ordner oder summary.json-Dateien")
    comp.add_argument("--out", default="comparison")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "init":
        save_example(args.output)
        print(f"Beispielkonfiguration geschrieben: {Path(args.output).resolve()}")
        return 0

    if args.cmd == "bootstrap":
        result = bootstrap_config(args.config, args.root, args.llama_dir, args.models_dir)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.cmd in {"doctor", "run"}:
        cfg = load_config(args.config)
        errors = validate_config(cfg)
        if errors:
            print("Konfigurationsfehler:", file=sys.stderr)
            for e in errors:
                print(f" - {e}", file=sys.stderr)
            return 2

    if args.cmd == "doctor":
        data = doctor(cfg)
        if args.as_json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return 0
        return _print_doctor(data)

    if args.cmd == "run":
        out = run_suite(cfg, selected_model=args.model, skip_endpoint=args.skip_endpoint)
        print(f"\nBenchmark abgeschlossen: {out}")
        print(f"HTML-Bericht: {out / 'report.html'}")
        print(f"CSV: {out / 'benchmarks.csv'}")
        print(f"JSON: {out / 'summary.json'}")
        return 0

    if args.cmd == "compare":
        report = compare_summaries(args.inputs, args.out)
        print(f"Vergleich erstellt: {report}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
