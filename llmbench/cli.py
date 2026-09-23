from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from . import __version__
from .backend_setup import SUPPORTED_BACKENDS
from .bootstrap import bootstrap_config
from .compare import compare_summaries
from .config import apply_duration_preset, load_config, save_example, validate_config
from .doctor import doctor
from .i18n import _
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
        for warning in data["warnings"]:
            print(f" - {warning}")
    return 1 if failed else 0


def _auto_install_llama_cpp_windows(root: Path) -> bool:
    core_script = root / "scripts" / "START_BENCHMARK_CORE.ps1"
    if not core_script.is_file():
        print(f"Automatisches llama.cpp-Setup fehlt: {core_script}", file=sys.stderr)
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


def _auto_install_llama_cpp_unix(root: Path) -> bool:
    from llmbench.llama_cpp_setup import ensure_llama_cpp

    print("\nllama.cpp fehlt. Suche einen passenden vorgebauten Build auf GitHub...")
    try:
        state = ensure_llama_cpp(root, log=lambda msg: print(msg))
    except Exception as exc:
        print(f"Automatische llama.cpp-Installation fehlgeschlagen: {exc}", file=sys.stderr)
        return False
    print(f"llama.cpp {state.get('tag')} ({state.get('backend')}) wurde installiert.")
    return True


def run_setup_wizard(allow_system_search: bool = False) -> int:
    from llmbench.download import download_models, verify_suite
    from llmbench.utils import ask_yes_no, console, print_err, print_msg, print_panel
    from rich.prompt import Prompt

    from llmbench.i18n import detect_language, language_preselected, save_language, set_language

    # setup.bat/setup.sh fragen die Sprache bereits ganz am Anfang; nur bei
    # direktem Aufruf von `llmbench setup` wird hier noch gefragt.
    if language_preselected():
        lang_val = detect_language()
    else:
        lang_val = Prompt.ask(
            "[cyan]Which language do you want to use? / Welche Sprache möchtest du nutzen? (de/en)[/cyan]",
            choices=["de", "en"],
            default="de"
        )
        save_language(lang_val)
    set_language(lang_val)

    print_panel(
        _("Ich erstelle die Konfiguration und suche llama.cpp sowie deine Modelle."),
        title=_("LLM Server Benchmark - Einrichtung"),
    )

    root = Path(".").resolve()
    config_path = "benchmark.yaml"
    print_msg(_("Suche llama.cpp und Modelle im Projektordner..."), style="blue")
    result = bootstrap_config(config_path, root, None, None, allow_system_search, language=lang_val)
    llama_dir = result["llama_dir"]
    ext = ".exe" if platform.system() == "Windows" else ""

    if not result["llama_binaries_found"]:
        print_err(_("llama.cpp wurde unter {path} nicht gefunden.").format(path=llama_dir))
        if platform.system() == "Windows":
            if not _auto_install_llama_cpp_windows(root):
                print_err(_("Einrichtung abgebrochen, weil llama.cpp nicht automatisch installiert werden konnte."))
                return 1
            result = bootstrap_config(config_path, root, None, None, allow_system_search, language=lang_val)
            llama_dir = result["llama_dir"]
            if not result["llama_binaries_found"]:
                print_err(
                    _("Das automatische Setup wurde beendet, aber {files} fehlen weiterhin unter {path}.").format(
                        files="llama-bench.exe / llama-server.exe", path="tools\\llama.cpp"
                    )
                )
                return 1
            print_msg(_("llama.cpp automatisch installiert: {path}").format(path=llama_dir), style="green")
        elif _auto_install_llama_cpp_unix(root):
            result = bootstrap_config(config_path, root, None, None, allow_system_search, language=lang_val)
            llama_dir = result["llama_dir"]
            if not result["llama_binaries_found"]:
                print_err(
                    _("Das automatische Setup wurde beendet, aber {files} fehlen weiterhin unter {path}.").format(
                        files="llama-bench / llama-server", path="tools/llama.cpp"
                    )
                )
                return 1
            print_msg(_("llama.cpp automatisch installiert: {path}").format(path=llama_dir), style="green")
        else:
            val = Prompt.ask("[cyan]" + _("Pfad zum llama.cpp-Ordner (Enter zum Abbrechen)") + "[/cyan]")
            if not val:
                print_msg(_("Einrichtung abgebrochen."), style="red")
                return 1
            llama_dir = val
            if not (
                (Path(llama_dir) / f"llama-bench{ext}").exists()
                and (Path(llama_dir) / f"llama-server{ext}").exists()
            ):
                print_err(_("Dort liegen weder llama-bench noch llama-server. Einrichtung abgebrochen."))
                return 1
    else:
        print_msg(_("llama.cpp gefunden: {path}").format(path=llama_dir), style="green")

    models_dir = result.get("models_dir") or str(root / "models")
    complete, missing = verify_suite(models_dir, "all")
    if not complete:
        console.print("\n[bold yellow]" + _("Die Standard-Suite ist noch nicht vollstaendig.") + "[/bold yellow]")
        console.print(_("Fehlend/unvollstaendig: {names}").format(names=", ".join(missing)))
        if ask_yes_no(_("Fehlende Standard-Modelle automatisch von HuggingFace laden?"), default=True):
            try:
                download_models(models_dir, "all")
            except Exception as exc:
                print_err(_("Automatischer Modell-Download fehlgeschlagen: {error}").format(error=exc))
                return 1
        elif result.get("models_found", 0) == 0:
            val = Prompt.ask("[cyan]" + _("Pfad zu einem eigenen Modellordner (Enter zum Abbrechen)") + "[/cyan]")
            if not val:
                print_err(_("Keine Modelle vorhanden. Einrichtung abgebrochen."))
                return 1
            models_dir = val
    else:
        print_msg(_("Standard-Suite vollstaendig vorhanden."), style="green")

    import socket

    server_name = Prompt.ask(
        "[cyan]" + _("Name dieses Servers fuer den Vergleich") + "[/cyan]", default=socket.gethostname()
    )
    result = bootstrap_config(config_path, root, llama_dir, models_dir, allow_system_search)

    cfg_file = Path(result["config"])
    cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
    cfg.setdefault("project", {})["server_name"] = server_name
    cfg_file.write_text(
        yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8"
    )

    for warning in result.get("warnings", []):
        console.print(f"[bold yellow]{_('Hinweis:')}[/bold yellow] {warning}")

    print_panel(
        _("Konfiguration gespeichert: {path}").format(path=cfg_file)
        + "\n"
        + _("Nächster Schritt: {command}").format(command="llmbench doctor --config benchmark.yaml"),
        title=_("Fertig"),
    )
    return 0


def _validate_config_path(config_path: str) -> bool:
    try:
        cfg = load_config(config_path)
    except Exception as exc:
        print(f"Konfiguration konnte nicht geladen werden: {exc}", file=sys.stderr)
        return False
    errors = validate_config(cfg)
    if not errors:
        return True
    print("Konfigurationsfehler:", file=sys.stderr)
    for error in errors:
        print(f" - {error}", file=sys.stderr)
    return False


def _performance_mode(cfg: dict, disabled: bool = False) -> Any:
    """Volle Leistung fuer die Dauer eines Laufs (siehe llmbench/performance.py)."""
    from llmbench.performance import PerformanceMode, format_steps
    from llmbench.utils import print_msg

    perf_cfg = cfg.get("performance") or {}
    if disabled or not perf_cfg.get("enabled", True):
        return contextlib.nullcontext(None)

    class _Announcing(PerformanceMode):
        def apply(self) -> dict:
            print_msg(_("Volle Leistung wird eingestellt (Energieplan, Turbo, Power-Limits)..."), style="blue")
            report = super().apply()
            for line in format_steps(self.steps):
                print(f"  {line}")
            if self.failed_steps() or any(s["status"] == "skipped" for s in self.steps):
                print_msg(
                    _("Nicht alles liess sich setzen. Fuer volle Leistung als root bzw. Administrator starten."),
                    style="yellow",
                )
            cfg["_performance_mode"] = report
            return report

    return _Announcing(
        cfg.get("_config_dir") or ".",
        restore_on_exit=bool(perf_cfg.get("restore_after_run", False)),
        use_sudo=bool(perf_cfg.get("use_sudo", True)),
        log=lambda msg: print_msg(msg, style="yellow"),
    )


def _performance_command(args: argparse.Namespace) -> int:
    from llmbench.hardware import collect_hardware
    from llmbench.performance import STATE_FILE, restore_from_state

    cfg = load_config(args.config)
    root = Path(cfg.get("_config_dir") or ".")
    if args.action == "off":
        if restore_from_state(root, log=print):
            print(_("Vorherige Leistungseinstellungen wurden wiederhergestellt."))
        else:
            print(_("Es gibt keine von llmbench geaenderten Leistungseinstellungen."))
        return 0
    if args.action == "on":
        cfg.setdefault("performance", {}).update({"enabled": True, "restore_after_run": False})
        with _performance_mode(cfg) as perf:
            failed = perf.failed_steps()
        print(_("Volle Leistung bleibt aktiv. Zuruecksetzen: llmbench performance off"))
        return 1 if failed else 0
    state = root / STATE_FILE
    print(_("Von llmbench gesetzt: {state}").format(state=_("ja") if state.is_file() else _("nein")))
    print(f"{_('Energieplan')}: {collect_hardware().get('power_scheme') or _('unbekannt')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llmbench", description="Reproduzierbarer LLM-Server-Benchmark")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    setup = sub.add_parser("setup", help="Konfiguration interaktiv erstellen")
    setup.add_argument(
        "--allow-system-search",
        action="store_true",
        help="Auch ausserhalb des Projekts nach llama.cpp und Modellen suchen (gefaehrdet die Vergleichbarkeit)",
    )

    init = sub.add_parser("init", help="Beispielkonfiguration erzeugen")
    init.add_argument("--output", default="benchmark.yaml")

    doc = sub.add_parser("doctor", help="Installation, Hardware und Modellpfade pruefen")
    doc.add_argument("--config", default="benchmark.yaml")
    doc.add_argument("--json", action="store_true", dest="as_json")

    run = sub.add_parser("run", help="Benchmark-Suite ausfuehren")
    run.add_argument("--config", default="benchmark.yaml")
    run.add_argument("--model", default=None, help="Nur ein benanntes Modell testen")
    run.add_argument("--duration", choices=["short", "medium", "long"], default=None)
    run.add_argument(
        "--hardware",
        choices=["cpu", "gpu", "both"],
        default="both",
        help="Nur CPU-, nur GPU-Profile oder beides testen.",
    )
    run.add_argument("--skip-endpoint", action="store_true")
    run.add_argument(
        "--plain",
        action="store_true",
        help="Nur einfache Textausgabe (keine Live-Statuszeile, keine farbige Ergebnisuebersicht).",
    )
    run.add_argument(
        "--no-performance-mode",
        action="store_true",
        help="Energieplan und Power-Limits nicht anfassen (performance.enabled: false).",
    )
    run.add_argument(
        "--stress",
        action="store_true",
        help="Nach dem normalen Lauf zusaetzlich TTFT-, Multi-Tenant-, OOM- und Quant-Stresstests starten.",
    )

    boot = sub.add_parser("bootstrap", help="Werkzeuge eintragen und GGUF-Modelle erkennen")
    boot.add_argument("--config", default="benchmark.yaml")
    boot.add_argument("--root", default=".")
    boot.add_argument("--llama-dir", default="tools/llama.cpp")
    boot.add_argument("--models-dir", default="models")
    boot.add_argument("--allow-system-search", action="store_true")

    install_llama = sub.add_parser(
        "install-llama-cpp",
        help="llama.cpp unter Linux/macOS automatisch von GitHub laden (Vulkan bei GPU, sonst CPU)",
    )
    install_llama.add_argument("--root", default=".")
    install_llama.add_argument("--llama-dir", default=None, help="Ziel, Standard: <root>/tools/llama.cpp")
    install_llama.add_argument("--tag", default=None, help="Feste llama.cpp-Release-Kennung, z.B. b10604")
    install_llama.add_argument(
        "--force", action="store_true", help="Auch neu installieren, wenn bereits ein lauffaehiger Build vorhanden ist"
    )

    install_backend = sub.add_parser(
        "install-backend",
        help="Container-Backend (vLLM) automatisch installieren: Docker-Image laden",
    )
    install_backend.add_argument("--backend", choices=list(SUPPORTED_BACKENDS), required=True)
    install_backend.add_argument("--image", default=None, help="Abweichendes Docker-Image statt des Standards")
    install_backend.add_argument("--root", default=".", help="Projektwurzel fuer die Zustandsdatei")

    uninstall_backend = sub.add_parser(
        "uninstall-backend",
        help="Container-Backend restlos entfernen: Container, Image, Zustandsdatei",
    )
    uninstall_backend.add_argument("--backend", choices=list(SUPPORTED_BACKENDS), required=True)
    uninstall_backend.add_argument(
        "--purge-models",
        action="store_true",
        help="Zusaetzlich das Volume mit heruntergeladenen Modell-Gewichten entfernen",
    )
    uninstall_backend.add_argument("--yes", action="store_true", help="Ohne Rueckfrage entfernen")
    uninstall_backend.add_argument("--root", default=".", help="Projektwurzel fuer die Zustandsdatei")

    comp = sub.add_parser("compare", help="Mehrere Serverlaeufe vergleichen")
    comp.add_argument("inputs", nargs="+", help="Run-Ordner oder summary.json-Dateien")
    comp.add_argument("--out", default="comparison")
    comp.add_argument("--strict", action="store_true")

    exp = sub.add_parser("export", help="Ergebnis-Paket als ZIP erzeugen")
    exp.add_argument("run_dir", help="Pfad zum Ergebnisordner eines Laufs")
    exp.add_argument("--output", default=None)

    dl = sub.add_parser("download", help="Standard-Modelle ueber HuggingFace verwalten")
    dl.add_argument("--suite", choices=["small", "mid", "heavy", "all"], default="small")
    dl.add_argument("--models-dir", default="models")
    dl.add_argument(
        "--verify-only",
        action="store_true",
        help="Nichts herunterladen; nur pruefen, ob die Suite vollstaendig vorhanden ist.",
    )

    for name, help_text in (
        ("stress-ttft", _("TTFT-Latenz unter extremer Parallelitaet")),
        ("stress-multitenant", _("Zwei aktive llama-server-Instanzen gleichzeitig")),
        ("stress-oom", _("Progressiver KV-Cache/Kontext-OOM-Test")),
        ("stress-quant", _("Gleiche Modelle mit verschiedenen Quantisierungen vergleichen")),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--config", default="benchmark.yaml")
        command.add_argument("--out", default=None)
        command.add_argument("--no-performance-mode", action="store_true")

    perf = sub.add_parser(
        "performance",
        help="Volle Leistung (Energieplan, Turbo, CPU/GPU-Power-Limits) ein-/ausschalten oder anzeigen",
    )
    perf.add_argument("action", choices=["on", "off", "status"])
    perf.add_argument("--config", default="benchmark.yaml")

    return parser


def _run_all_stress(config_path: str, out_dir: Path) -> dict[str, int]:
    from llmbench.stress.multitenant import run_multitenant
    from llmbench.stress.oom import run_oom_stress
    from llmbench.stress.quant import run_quant_stress
    from llmbench.stress.ttft import run_ttft_stress
    from llmbench.utils import ensure_dir, print_err, write_json

    stress_root = ensure_dir(out_dir / "stress")
    cfg = load_config(config_path)
    statuses: dict[str, int] = {}

    def _run(name: str, fn: Any) -> int:
        try:
            return fn()
        except Exception as exc:
            print_err(_("Stress-Test '{name}' fehlgeschlagen: {error}").format(name=name, error=exc))
            return 1

    statuses["ttft"] = _run("ttft", lambda: run_ttft_stress(config_path, stress_root / "ttft"))
    statuses["oom"] = _run("oom", lambda: asyncio.run(run_oom_stress(config_path, stress_root / "oom")))
    if len(cfg.get("models", [])) >= 2:
        statuses["multitenant"] = _run(
            "multitenant",
            lambda: asyncio.run(run_multitenant(config_path, stress_root / "multitenant")),
        )
    else:
        statuses["multitenant"] = 2
    statuses["quant"] = _run("quant", lambda: asyncio.run(run_quant_stress(config_path, stress_root / "quant")))
    write_json(stress_root / "index.json", statuses)
    return statuses


def _uninstall_backend(args: argparse.Namespace) -> int:
    """Zeigt vor dem Loeschen, was entfernt wird, und fragt nach.

    Mehrere Gigabyte ohne Rueckfrage zu loeschen waere gegen die sonstige Praxis
    dieses Projekts. Ohne TTY (CI, Pipe) gibt es niemanden, der antworten
    koennte - dann wird nicht blockiert, sondern durchgefuehrt.
    """
    from llmbench.backend_setup import describe_backend_removal, remove_backend

    root = Path(args.root).resolve()
    plan = describe_backend_removal(args.backend, root, purge_models=args.purge_models)

    print(f"Folgendes wird fuer das Backend '{args.backend}' entfernt:")
    print(f" - Container: {plan['container']}")
    print(f" - Docker-Image: {plan['image']}")
    if plan["volume"]:
        print(f" - Docker-Volume (Modell-Gewichte): {plan['volume']}")
    else:
        print(f" - Volume '{plan['volume_kept']}' bleibt erhalten (--purge-models entfernt es ebenfalls)")
    print(f" - Zustandsdatei: {plan['state_file']}")
    if not plan["installed"]:
        print("Hinweis: Es ist keine Installation vermerkt. Es wird trotzdem aufgeraeumt.")

    if not args.yes and sys.stdin.isatty():
        answer = input("Wirklich entfernen? [j/N] ").strip().lower()
        if answer not in {"j", "ja", "y", "yes"}:
            print("Abgebrochen. Es wurde nichts entfernt.")
            return 1

    try:
        remove_backend(args.backend, root, purge_models=args.purge_models, log=print)
    except Exception as exc:
        print(f"Deinstallation des Backends '{args.backend}' fehlgeschlagen: {exc}", file=sys.stderr)
        return 1
    return 0


def _run_stress_command(args: argparse.Namespace) -> int:
    output = args.out
    if args.cmd == "stress-ttft":
        from llmbench.stress.ttft import run_ttft_stress

        return run_ttft_stress(args.config, output)
    if args.cmd == "stress-multitenant":
        from llmbench.stress.multitenant import run_multitenant

        return asyncio.run(run_multitenant(args.config, output))
    if args.cmd == "stress-oom":
        from llmbench.stress.oom import run_oom_stress

        return asyncio.run(run_oom_stress(args.config, output))
    if args.cmd == "stress-quant":
        from llmbench.stress.quant import run_quant_stress

        return asyncio.run(run_quant_stress(args.config, output))
    return 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "setup":
        return run_setup_wizard(args.allow_system_search)

    if args.cmd == "download":
        from llmbench.download import download_models, verify_suite

        if args.verify_only:
            complete, missing = verify_suite(args.models_dir, args.suite)
            if complete:
                print(f"Suite '{args.suite}' ist vollstaendig vorhanden.")
                return 0
            print("Fehlende/unvollstaendige Modelle: " + ", ".join(missing), file=sys.stderr)
            return 1
        try:
            download_models(args.models_dir, args.suite)
            return 0
        except Exception as exc:
            print(f"Modell-Download fehlgeschlagen: {exc}", file=sys.stderr)
            return 1

    if args.cmd == "performance":
        return _performance_command(args)

    if args.cmd.startswith("stress-"):
        if not _validate_config_path(args.config):
            return 2
        with _performance_mode(load_config(args.config), args.no_performance_mode):
            return _run_stress_command(args)

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

    if args.cmd == "install-llama-cpp":
        from llmbench.llama_cpp_setup import ensure_llama_cpp

        root = Path(args.root).resolve()
        llama_dir = Path(args.llama_dir) if args.llama_dir else None
        try:
            state = ensure_llama_cpp(root, llama_dir=llama_dir, tag=args.tag, force=args.force, log=print)
        except Exception as exc:
            print(f"llama.cpp-Installation fehlgeschlagen: {exc}", file=sys.stderr)
            return 1
        print(f"llama.cpp {state.get('tag')} ({state.get('backend')}) bereit.")
        return 0

    if args.cmd == "install-backend":
        from llmbench.backend_setup import ensure_backend

        try:
            state = ensure_backend(args.backend, Path(args.root).resolve(), args.image, log=print)
        except Exception as exc:
            print(f"Installation des Backends '{args.backend}' fehlgeschlagen: {exc}", file=sys.stderr)
            return 1
        print(f"Backend '{args.backend}' ist bereit: {state.get('image')}")
        if state.get("digest"):
            print(f"Image-Digest: {state['digest']}")
        return 0

    if args.cmd == "uninstall-backend":
        return _uninstall_backend(args)

    if args.cmd in {"doctor", "run"}:
        cfg = load_config(args.config)
        if args.cmd == "run" and args.duration:
            cfg = apply_duration_preset(cfg, args.duration)

        errors = validate_config(cfg)
        if errors:
            print("Konfigurationsfehler:", file=sys.stderr)
            for error in errors:
                print(f" - {error}", file=sys.stderr)
            print("\nTipp: `llmbench setup` erstellt die Konfiguration interaktiv.")
            return 2

        if args.cmd == "doctor":
            data = doctor(cfg)
            if args.as_json:
                print(json.dumps(data, indent=2, ensure_ascii=False))
                return 0
            return _print_doctor(data)

        with _performance_mode(cfg, args.no_performance_mode):
            out = run_suite(
                cfg,
                selected_model=args.model,
                skip_endpoint=args.skip_endpoint,
                reporter=make_reporter(force_plain=args.plain),
                hardware_target=args.hardware,
                plain=args.plain,
            )
            print(f"\nBenchmark abgeschlossen: {out}")
            pdf = out / "report.pdf"
            if pdf.exists():
                print(f"PDF-Bericht: {pdf}")
            print(f"HTML-Bericht: {out / 'report.html'}")
            print(f"CSV: {out / 'benchmarks.csv'}")
            print(f"JSON: {out / 'summary.json'}")
            if args.stress:
                statuses = _run_all_stress(args.config, out)
                print(f"Stress-Ergebnisse: {out / 'stress' / 'index.json'} ({statuses})")
        return 0

    if args.cmd == "compare":
        report, issues = compare_summaries(args.inputs, args.out)
        print(f"Vergleich erstellt: {report}")
        errors = [issue for issue in issues if issue["level"] == "error"]
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
