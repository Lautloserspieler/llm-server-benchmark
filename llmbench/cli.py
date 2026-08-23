from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

import yaml

from . import __version__
from .bootstrap import bootstrap_config
from .compare import compare_summaries
from .config import load_config, save_example, validate_config
from .doctor import doctor
from .runner import run_suite

try:
    from .server import start_server
except ImportError:  # FastAPI/Uvicorn nicht installiert
    start_server = None


def _print_doctor(data: dict) -> int:
    failed = False
    print("\nWerkzeuge")
    print("---------")
    for x in data["checks"]:
        mark = "OK" if x["ok"] else "FEHLT"
        print(f"[{mark:5}] {x['name']}: {x.get('resolved') or x.get('configured')}")
        if x.get("error"):
            print(f"          {x['error']}")
        flags = x.get("flags") or {}
        if flags.get("missing_optional"):
            print(f"          Optionale Flags fehlen: {', '.join(flags['missing_optional'])}")
        build = (x.get("build") or {}).get("version_output")
        if build:
            print(f"          {build.splitlines()[0][:120]}")
        failed = failed or not x["ok"]

    print("\nModelle")
    print("-------")
    for x in data["models"]:
        mark = "OK" if x["exists"] else "FEHLT"
        print(f"[{mark:5}] {x['name']}: {x['path']}")
        if x.get("hint"):
            print(f"          {x['hint']}")
        failed = failed or not x["exists"]

    hw = data["hardware"]
    print("\nHardware")
    print("--------")
    print(f"CPU: {hw.get('cpu', {}).get('name')}")
    print(f"RAM: {(hw.get('memory', {}).get('total_bytes') or 0) / (1024 ** 3):.1f} GiB")
    print(f"Energieplan: {hw.get('power_scheme') or 'unbekannt'}")
    for gpu in hw.get("gpus", []):
        print(f"GPU: {gpu.get('vendor')} {gpu.get('name')} – {gpu.get('memory.total')} MiB VRAM")

    print(f"\nKonfigurations-Fingerabdruck: {data.get('config_fingerprint')}")
    print("(Dieser Wert muss auf allen verglichenen Servern identisch sein.)")

    if data.get("warnings"):
        print("\nHinweise")
        print("--------")
        for w in data["warnings"]:
            print(f" - {w}")
    return 1 if failed else 0


def _ask(prompt: str, default: str = "") -> str:
    try:
        value = input(prompt).strip()
    except EOFError:
        return default
    return value or default


def run_setup_wizard(allow_system_search: bool = False) -> int:
    print("\n--- LLM Server Benchmark: Einrichtung ---")
    print("Ich erstelle die Konfiguration und suche llama.cpp sowie deine Modelle.\n")

    root = Path(".").resolve()
    config_path = "benchmark.yaml"

    print("Suche llama.cpp und Modelle im Projektordner...")
    result = bootstrap_config(config_path, root, None, None, allow_system_search)
    llama_dir = result["llama_dir"]
    models_found = result["models_found"]
    ext = ".exe" if platform.system() == "Windows" else ""

    if not result["llama_binaries_found"]:
        print(f"llama.cpp wurde unter {llama_dir} nicht gefunden.")
        val = _ask("Pfad zum llama.cpp-Ordner (Enter zum Abbrechen): ")
        if not val:
            print("Einrichtung abgebrochen.")
            return 1
        llama_dir = val
        if not (
            (Path(llama_dir) / f"llama-bench{ext}").exists()
            and (Path(llama_dir) / f"llama-server{ext}").exists()
        ):
            print("Dort liegen weder llama-bench noch llama-server. Einrichtung abgebrochen.")
            return 1
    else:
        print(f"llama.cpp gefunden: {llama_dir}")

    models_dir = result.get("models_dir")
    if models_found == 0:
        print("Unter models/ wurden keine GGUF-Dateien gefunden.")
        val = _ask("Pfad zum Modellordner (Enter zum Ueberspringen): ")
        if val:
            models_dir = val
        else:
            print("Keine Modelle konfiguriert. Du kannst sie spaeter in benchmark.yaml ergaenzen.")
    else:
        print(f"{models_found} Modell(e) erkannt.")

    # Der Servername ist die Spaltenueberschrift im spaeteren Vergleich.
    # Ohne Nachfrage steht dort der Hostname, was selten hilfreich ist.
    import socket

    suggestion = socket.gethostname()
    server_name = _ask(f"Name dieses Servers fuer den Vergleich [{suggestion}]: ", suggestion)

    result = bootstrap_config(config_path, root, llama_dir, models_dir, allow_system_search)

    cfg_file = Path(result["config"])
    cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
    cfg.setdefault("project", {})["server_name"] = server_name
    cfg_file.write_text(
        yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8"
    )

    for warning in result.get("warnings", []):
        print(f"Hinweis: {warning}")

    print(f"\nFertig. Konfiguration: {cfg_file}")
    print("Naechster Schritt: llmbench doctor --config benchmark.yaml")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="llmbench", description="Reproduzierbarer LLM-Server-Benchmark")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    setup = sub.add_parser("setup", help="Konfiguration interaktiv erstellen")
    setup.add_argument(
        "--allow-system-search",
        action="store_true",
        help="Auch ausserhalb des Projekts nach llama.cpp und Modellen suchen "
             "(gefaehrdet die Vergleichbarkeit zwischen Servern)",
    )

    init = sub.add_parser("init", help="Beispielkonfiguration erzeugen")
    init.add_argument("--output", default="benchmark.yaml")

    doc = sub.add_parser("doctor", help="Installation, Hardware und Modellpfade pruefen")
    doc.add_argument("--config", default="benchmark.yaml")
    doc.add_argument("--json", action="store_true", dest="as_json")

    run = sub.add_parser("run", help="Benchmark-Suite ausfuehren")
    run.add_argument("--config", default="benchmark.yaml")
    run.add_argument("--model", default=None, help="Nur ein benanntes Modell testen")
    run.add_argument("--skip-endpoint", action="store_true")

    boot = sub.add_parser("bootstrap", help="Werkzeuge eintragen und GGUF-Modelle erkennen")
    boot.add_argument("--config", default="benchmark.yaml")
    boot.add_argument("--root", default=".")
    boot.add_argument("--llama-dir", default="tools/llama.cpp")
    boot.add_argument("--models-dir", default="models")
    boot.add_argument("--allow-system-search", action="store_true")

    comp = sub.add_parser("compare", help="Mehrere Serverlaeufe vergleichen")
    comp.add_argument("inputs", nargs="+", help="Run-Ordner oder summary.json-Dateien")
    comp.add_argument("--out", default="comparison")
    comp.add_argument(
        "--strict",
        action="store_true",
        help="Exitcode 1, wenn die Laeufe nicht unter gleichen Bedingungen entstanden sind",
    )

    srv = sub.add_parser("serve", help="Web-Dashboard starten")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8000)
    srv.add_argument("--config", default="benchmark.yaml")
    srv.add_argument(
        "--allow-remote",
        action="store_true",
        help="Zugriff von anderen Rechnern erlauben (nur in vertrauenswuerdigen Netzen)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "setup":
        return run_setup_wizard(args.allow_system_search)

    if args.cmd == "init":
        save_example(args.output)
        print(f"Beispielkonfiguration geschrieben: {Path(args.output).resolve()}")
        return 0

    if args.cmd == "bootstrap":
        result = bootstrap_config(
            args.config, args.root, args.llama_dir, args.models_dir, args.allow_system_search
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.cmd in {"doctor", "run"}:
        cfg = load_config(args.config)
        errors = validate_config(cfg)
        if errors:
            print("Konfigurationsfehler:", file=sys.stderr)
            for e in errors:
                print(f" - {e}", file=sys.stderr)
            print("\nTipp: `llmbench setup` erstellt die Konfiguration interaktiv.")
            return 2

        if args.cmd == "doctor":
            data = doctor(cfg)
            if args.as_json:
                print(json.dumps(data, indent=2, ensure_ascii=False))
                return 0
            return _print_doctor(data)

        out = run_suite(cfg, selected_model=args.model, skip_endpoint=args.skip_endpoint)
        print(f"\nBenchmark abgeschlossen: {out}")
        print(f"HTML-Bericht: {out / 'report.html'}")
        print(f"CSV: {out / 'benchmarks.csv'}")
        print(f"JSON: {out / 'summary.json'}")
        return 0

    if args.cmd == "compare":
        report, issues = compare_summaries(args.inputs, args.out)
        print(f"Vergleich erstellt: {report}")
        errors = [i for i in issues if i["level"] == "error"]
        for issue in issues:
            marker = "FEHLER " if issue["level"] == "error" else "Hinweis"
            print(f"[{marker}] {issue['topic']}: {issue['message']}")
        if not issues:
            print("Vergleichbarkeit geprueft: Konfiguration, Build, Modelle und Profile stimmen ueberein.")
        if errors and args.strict:
            return 1
        return 0

    if args.cmd == "serve":
        if start_server is None:
            print(
                "Web-Abhaengigkeiten fehlen. Installation: pip install -e \".[web]\"",
                file=sys.stderr,
            )
            return 2
        start_server(args.host, args.port, config_name=args.config, allow_remote=args.allow_remote)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
