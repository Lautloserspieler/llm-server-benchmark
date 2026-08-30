from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path

import yaml

from . import __version__
from .bootstrap import bootstrap_config
from .compare import compare_summaries
from .config import load_config, save_example, validate_config, apply_duration_preset
from .doctor import doctor
from .progress import make_reporter
from .runner import run_suite


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
        devices = (x.get("build") or {}).get("devices_output") or ""
        for line in devices.splitlines():
            if "Device" in line or "load_backend" in line:
                print(f"          {line.strip()[:120]}")
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
    power_scheme = (hw.get("power_scheme") or "unbekannt").replace("\ufffd", "?")
    print(f"Energieplan: {power_scheme}")
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


def _auto_install_llama_cpp_windows(root: Path) -> bool:
    """Install llama.cpp automatically when the interactive setup is used on Windows.

    The normal one-click launcher already installs llama.cpp before bootstrap.
    This fallback makes `llmbench setup` self-healing as well, so a missing
    tools/llama.cpp directory never results in a manual path prompt on Windows.
    """
    core_script = root / "scripts" / "START_BENCHMARK_CORE.ps1"
    if not core_script.is_file():
        print(
            f"Automatisches llama.cpp-Setup fehlt: {core_script}",
            file=sys.stderr,
        )
        return False

    print("\nllama.cpp fehlt. Starte automatische Installation...")
    print("Der passende Windows-Build (CUDA bei NVIDIA, sonst CPU) wird von GitHub geladen.")

    try:
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(core_script),
                "-SetupOnly",
            ],
            cwd=str(root),
            check=False,
        )
    except OSError as exc:
        print(f"PowerShell konnte nicht gestartet werden: {exc}", file=sys.stderr)
        return False

    if proc.returncode != 0:
        print(
            f"Automatische llama.cpp-Installation ist mit Exitcode {proc.returncode} fehlgeschlagen.",
            file=sys.stderr,
        )
        return False
    return True


def run_setup_wizard(allow_system_search: bool = False) -> int:
    from llmbench.utils import console, print_panel, print_err, print_msg
    from rich.prompt import Prompt

    print_panel(
        "Ich erstelle die Konfiguration und suche llama.cpp sowie deine Modelle.",
        title="LLM Server Benchmark - Einrichtung"
    )

    root = Path(".").resolve()
    config_path = "benchmark.yaml"

    print_msg("Suche llama.cpp und Modelle im Projektordner...", style="blue")
    result = bootstrap_config(config_path, root, None, None, allow_system_search)
    llama_dir = result["llama_dir"]
    models_found = result["models_found"]
    ext = ".exe" if platform.system() == "Windows" else ""

    if not result["llama_binaries_found"]:
        print_err(f"llama.cpp wurde unter {llama_dir} nicht gefunden.")

        if platform.system() == "Windows":
            if not _auto_install_llama_cpp_windows(root):
                print_err("Einrichtung abgebrochen, weil llama.cpp nicht automatisch installiert werden konnte.")
                return 1

            result = bootstrap_config(config_path, root, None, None, allow_system_search)
            llama_dir = result["llama_dir"]
            models_found = result["models_found"]
            if not result["llama_binaries_found"]:
                print_err(
                    "Das automatische Setup wurde beendet, aber llama-bench.exe oder "
                    "llama-server.exe fehlen weiterhin unter tools\\llama.cpp."
                )
                return 1
            print_msg(f"llama.cpp automatisch installiert: {llama_dir}", style="green")
        else:
            val = Prompt.ask("[cyan]Pfad zum llama.cpp-Ordner (Enter zum Abbrechen)[/cyan]")
            if not val:
                print_msg("Einrichtung abgebrochen.", style="red")
                return 1
            llama_dir = val
            if not (
                (Path(llama_dir) / f"llama-bench{ext}").exists()
                and (Path(llama_dir) / f"llama-server{ext}").exists()
            ):
                print_err("Dort liegen weder llama-bench noch llama-server. Einrichtung abgebrochen.")
                return 1
    else:
        print_msg(f"llama.cpp gefunden: {llama_dir}", style="green")

    models_dir = result.get("models_dir") or "models"
    if models_found == 0:
        console.print("\n[bold yellow]Unter models/ wurden keine GGUF-Dateien gefunden.[/bold yellow]")
        console.print("Die neue V2 Benchmark-Suite erfordert standardisierte Modelle.")
        dl_ask = Prompt.ask(
            "[cyan]Sollen ALLE Standard-Modelle (inkl. Heavy & MoE) automatisch von HuggingFace heruntergeladen werden?[/cyan]",
            choices=["j", "n"],
            default="j"
        )
        if dl_ask.lower() == "j":
            from llmbench.download import download_models
            try:
                download_models(models_dir, "all")
                print_msg("\nModelle erfolgreich heruntergeladen. Sie werden nun eingebunden.", style="bold green")
            except Exception as e:
                print_err(f"Fehler beim automatischen Download: {e}")
        else:
            val = Prompt.ask("[cyan]Pfad zu einem eigenen Modellordner (Enter zum Ueberspringen)[/cyan]")
            if val:
                models_dir = val
            else:
                console.print("[yellow]Keine Modelle konfiguriert. Du kannst sie spaeter in benchmark.yaml ergaenzen oder 'llmbench download' nutzen.[/yellow]")
    else:
        print_msg(f"{models_found} Modell(e) erkannt.", style="green")

    import socket
    suggestion = socket.gethostname()
    server_name = Prompt.ask(f"[cyan]Name dieses Servers fuer den Vergleich[/cyan]", default=suggestion)

    result = bootstrap_config(config_path, root, llama_dir, models_dir, allow_system_search)

    cfg_file = Path(result["config"])
    cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
    cfg.setdefault("project", {})["server_name"] = server_name
    cfg_file.write_text(
        yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8"
    )

    for warning in result.get("warnings", []):
        console.print(f"[bold yellow]Hinweis:[/bold yellow] {warning}")

    print_panel(f"Konfiguration gespeichert: {cfg_file}\nNaechster Schritt: llmbench doctor --config benchmark.yaml", title="Fertig")
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
    run.add_argument("--duration", choices=["short", "medium", "long"], default=None, help="Vordefinierte Dauer: short, medium oder long")
    run.add_argument(
        "--hardware",
        choices=["cpu", "gpu", "both"],
        default="both",
        help="Nur CPU-, nur GPU-Profile oder beides testen (Standard: both). "
             "Der Soak-Test laeuft nur bei 'both', weil er CPU und GPU gleichzeitig braucht.",
    )
    run.add_argument("--skip-endpoint", action="store_true")
    run.add_argument(
        "--plain",
        action="store_true",
        help="Statt der sich aktualisierenden Statuszeile nur einfache Zeilen ausgeben",
    )

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

    exp = sub.add_parser("export", help="Ergebnis-Paket als ZIP erzeugen")
    exp.add_argument("run_dir", help="Pfad zum Ergebnisordner eines Laufs")
    exp.add_argument("--output", default=None, help="Pfad fuer die ZIP-Datei (Standard: <run_dir>.zip)")

    dl = sub.add_parser("download", help="Automatischer Download der Standard-Modelle ueber HuggingFace")
    dl.add_argument("--suite", choices=["small", "mid", "heavy", "all"], default="small")
    dl.add_argument("--models-dir", default="models")

    stress_ttft = sub.add_parser("stress-ttft", help="Time to First Token (TTFT) Latenz unter extremer Last")
    stress_ttft.add_argument("--config", default="benchmark.yaml")

    stress_mt = sub.add_parser("stress-multitenant", help="Concurrency-Test mit zwei aktiven llama-server-Instanzen")
    stress_mt.add_argument("--config", default="benchmark.yaml")

    stress_oom = sub.add_parser("stress-oom", help="KV-Cache OOM Stresstest mit massiven RAG-Prompts")
    stress_oom.add_argument("--config", default="benchmark.yaml")

    stress_quant = sub.add_parser("stress-quant", help="Quantisierungs-Vergleich fuer Speicherbandbreiten-Engpaesse")
    stress_quant.add_argument("--config", default="benchmark.yaml")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "setup":
        return run_setup_wizard(args.allow_system_search)

    if args.cmd == "download":
        from llmbench.download import download_models
        download_models(args.models_dir, args.suite)
        return 0

    if args.cmd == "stress-multitenant":
        import asyncio
        from llmbench.stress.multitenant import run_multitenant
        return asyncio.run(run_multitenant(args.config))

    if args.cmd == "stress-oom":
        import asyncio
        from llmbench.stress.oom import run_oom_stress
        return asyncio.run(run_oom_stress(args.config))

    if args.cmd == "stress-quant":
        import asyncio
        from llmbench.stress.quant import run_quant_stress
        return asyncio.run(run_quant_stress(args.config))

    if args.cmd == "stress-ttft":
        print("TTFT (Time to First Token) wird bereits automatisch bei jedem 'llmbench run' erfasst!")
        print("Starte den normalen Benchmark-Lauf. Das 95. Perzentil (p95) der Latenz")
        print("findest du im finalen PDF-Report unter 'Server-Interaktivitaet'.")
        print("Verwende: llmbench run")
        return 0

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

        if args.cmd == "run" and args.duration:
            cfg = apply_duration_preset(cfg, args.duration)

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

        out = run_suite(
            cfg,
            selected_model=args.model,
            skip_endpoint=args.skip_endpoint,
            reporter=make_reporter(force_plain=args.plain),
            hardware_target=args.hardware,
        )
        print(f"\nBenchmark abgeschlossen: {out}")
        pdf = out / "report.pdf"
        if pdf.exists():
            print(f"PDF-Bericht: {pdf}")
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

    if args.cmd == "export":
        from .export import export_run
        try:
            zip_path = export_run(args.run_dir, args.output)
            print(f"Ergebnis-Paket erzeugt: {zip_path}")
            return 0
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
