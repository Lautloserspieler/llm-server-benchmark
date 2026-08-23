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

try:
    from .server import start_server
except ImportError:
    start_server = None


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


def run_setup_wizard() -> int:
    """Interactive setup wizard to configure benchmark.yaml.
    """
    print("\n--- LLM Server Benchmark Setup Wizard ---")
    print("Ich helfe dir, die Konfiguration automatisch zu erstellen.\n")

    root = Path(".").resolve()
    config_path = "benchmark.yaml"

    # 1. Try automatic bootstrap first
    print("Suche nach llama.cpp und Modellen...")
    result = bootstrap_config(config_path, root, None, None)

    llama_dir = result["llama_dir"]
    models_found = result["models_found"]

    # Validate binaries
    import platform
    ext = ".exe" if platform.system() == "Windows" else ""
    has_binaries = (Path(llama_dir) / f"llama-bench{ext}").exists() and (Path(llama_dir) / f"llama-server{ext}").exists()

    if not has_binaries:
        print(f"⚠️  Konnte llama.cpp in {llama_dir} nicht finden.")
        val = input("Bitte gib den Pfad zum llama.cpp Ordner ein (oder Enter zum Abbrechen): ").strip()
        if not val:
            print("Setup abgebrochen.")
            return 1
        llama_dir = val
        # Re-validate
        if not ((Path(llama_dir) / f"llama-bench{ext}").exists() and (Path(llama_dir) / f"llama-server{ext}").exists()):
            print("❌ Ungültiger Pfad. Die Dateien llama-bench und llama-server müssen dort liegen.")
            return 1
    else:
        print(f"✅ llama.cpp gefunden in: {llama_dir}")

    if models_found == 0:
        print("⚠️  Keine GGUF-Modelle automatisch gefunden.")
        val = input("Bitte gib den Pfad zum Modelle-Ordner ein (oder Enter zum Überspringen): ").strip()
        if val:
            # Trigger bootstrap again with custom path
            result = bootstrap_config(config_path, root, llama_dir, val)
            models_found = result["models_found"]
            print(f"✅ {models_found} Modelle gefunden.")
        else:
            print("Keine Modelle konfiguriert. Du kannst sie später manuell in benchmark.yaml hinzufügen.")
    else:
        print(f"✅ {models_found} Modelle automatisch erkannt.")

    # Final save with corrected tools
    bootstrap_config(config_path, root, llama_dir, result.get("models_dir"))

    print(f"\n✨ Setup abgeschlossen! Konfiguration gespeichert in: {Path(config_path).resolve()}")
    print("Du kannst jetzt den Benchmark mit `llmbench run` starten.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="llmbench", description="Reproduzierbarer LLM-Server-Benchmark")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    setup = sub.add_parser("setup", help="Interaktiver Setup-Wizard für die Konfiguration")

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
    
    srv = sub.add_parser("serve", help="Startet das Web-Dashboard")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8000)
    
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "setup":
        return run_setup_wizard()
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
            print("\n💡 Tipp: Nutze `llmbench setup`, um die Konfiguration interaktiv zu erstellen.")
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

    if args.cmd == "serve":
        if start_server is None:
            print("Web-Abhängigkeiten fehlen. Bitte mit `pip install -e .[web]` installieren.", file=sys.stderr)
            return 2
        start_server(args.host, args.port)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
