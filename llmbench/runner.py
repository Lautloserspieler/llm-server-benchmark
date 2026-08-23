from __future__ import annotations

import asyncio
import csv
import traceback
from pathlib import Path
from typing import Any

from . import __version__
from .config import config_fingerprint, public_config, resolve_path
from .endpoint import (
    run_endpoint_load,
    start_llama_server,
    stop_llama_server,
    wait_health,
    run_sanity_check,
)
from .hardware import collect_hardware
from .llama_bench import build_ids_from_rows, flatten_bench_rows, probe_build, run_llama_bench
from .pdf_report import generate_run_pdf
from .progress import Reporter, make_reporter
from .report import generate_run_html
from .tuner import tune_gpu_layers
from .backends.llama_cpp import LlamaCppBackend
from .utils import (
    ensure_dir,
    file_fingerprint,
    hostname,
    safe_name,
    utc_now_compact,
    utc_now_iso,
    write_json,
)

BENCH_KINDS = ("prompt", "generation", "long_context")


def count_tests(cfg: dict[str, Any], selected_model: str | None = None) -> int:
    """Wie viele Einzeltests stehen an. Basis der Restzeitschaetzung."""
    total = 0
    for model in cfg.get("models", []):
        if selected_model and model["name"].lower() != selected_model.lower():
            continue
        total += len(model.get("profiles") or []) * len(BENCH_KINDS)
    return total


def _model_meta(model: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    path = resolve_path(model["path"], cfg)
    p = Path(path)
    meta: dict[str, Any] = {
        "name": model["name"],
        "path": path,
        "exists": p.exists(),
        "size_bytes": p.stat().st_size if p.exists() else None,
        "quality_gate": model.get("quality_gate"),
        "notes": model.get("notes"),
    }
    if p.exists() and cfg["project"].get("hash_models", True):
        meta["sha256"] = file_fingerprint(p, with_hash=True).get("sha256")
    return meta


def _tool_info(cfg: dict[str, Any]) -> dict[str, Any]:
    """Identitaet der Messwerkzeuge festhalten: ohne sie ist ein Vergleich
    zwischen zwei Servern nicht belegbar."""
    with_hash = bool(cfg["project"].get("hash_tools", True))
    info: dict[str, Any] = {"llmbench_version": __version__}
    info["llama_bench"] = probe_build(cfg["tools"]["llama_bench"], with_hash=with_hash)
    server_exe = cfg["tools"].get("llama_server")
    if server_exe:
        info["llama_server"] = {"binary": file_fingerprint(server_exe, with_hash=with_hash)}
    return info


def _resolve_endpoint_profile(model: dict[str, Any], endpoint_cfg: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    profiles = model.get("profiles") or []
    wanted = endpoint_cfg.get("profile")
    if not wanted:
        return profiles[0], None
    match = next((p for p in profiles if p.get("name") == wanted), None)
    if match:
        return match, None
    return profiles[0], (
        f"Profil '{wanted}' aus endpoint.profile existiert bei Modell "
        f"'{model.get('name')}' nicht. Stattdessen wurde '{profiles[0].get('name')}' verwendet."
    )


def run_suite(
    cfg: dict[str, Any],
    selected_model: str | None = None,
    skip_endpoint: bool = False,
    reporter: Reporter | None = None,
) -> Path:
    reporter = reporter or make_reporter()
    server_name = cfg["project"].get("server_name") or hostname()
    output_root = Path(resolve_path(cfg["project"]["output_dir"], cfg))
    run_dir = ensure_dir(output_root / f"{safe_name(server_name)}_{utc_now_compact()}")

    hardware = collect_hardware(output_root)
    write_json(run_dir / "hardware.json", hardware)
    tools = _tool_info(cfg)

    # Backend Initialisierung
    backend = LlamaCppBackend(cfg["tools"]["llama_bench"], cfg["tools"]["llama_server"])

    summary: dict[str, Any] = {
        "schema_version": 2,
        "llmbench_version": __version__,
        "project": cfg["project"].get("name"),
        "server_name": server_name,
        "started_at": utc_now_iso(),
        "config_path": cfg.get("_config_path"),
        # Die tatsaechlich verwendete Konfiguration wandert mit ins Ergebnis.
        # Nur so laesst sich spaeter pruefen, ob zwei Laeufe vergleichbar sind.
        "config": public_config(cfg),
        "config_fingerprint": config_fingerprint(cfg["benchmark"]),
        "tools": tools,
        "hardware": hardware,
        "warnings": [],
        "models": [],
    }

    build_ids: set[str] = set()
    reporter.run_started(server_name, count_tests(cfg, selected_model))

    for model in cfg["models"]:
        if selected_model and model["name"].lower() != selected_model.lower():
            continue
        meta = _model_meta(model, cfg)
        model_dir = ensure_dir(run_dir / safe_name(model["name"]))

        # Auto-Tuning: Suche optimalen Layer-Count, falls aktiviert.
        if cfg["benchmark"].get("auto_tune"):
            reporter.note(f"Auto-Tuning fuer {model['name']} ...")
            endpoint_cfg_tune = dict(cfg.get("endpoint", {}))
            endpoint_cfg_tune.update(model.get("endpoint", {}) or {})
            best_layers = tune_gpu_layers(
                cfg["tools"]["llama_server"],
                meta["path"],
                endpoint_cfg_tune,
                cfg["benchmark"],
                model_dir,
            )
            reporter.note(f"Optimal layers gefunden: {best_layers}")
            # Das Ergebnis in das erste Profil ueberschreiben oder neues Profil anlegen.
            if model.get("profiles"):
                model["profiles"][0]["gpu_layers"] = best_layers
                model["profiles"][0]["name"] = f"Auto-Tuned ({best_layers})"
            else:
                model["profiles"] = [{"name": f"Auto-Tuned ({best_layers})", "gpu_layers": best_layers}]

        model_result: dict[str, Any] = {"model": meta, "profiles": []}
        if not meta["exists"]:
            model_result["status"] = "failed"
            model_result["error"] = f"Modelldatei nicht gefunden: {meta['path']}"
            summary["models"].append(model_result)
            summary["warnings"].append(model_result["error"])
            reporter.note(model_result["error"])
            write_json(run_dir / "summary.partial.json", summary)
            continue

        for profile in model.get("profiles", []):
            profile_dir = ensure_dir(model_dir / safe_name(profile["name"]))
            profile_result: dict[str, Any] = {
                "name": profile["name"],
                "settings": profile,
                "benchmarks": {},
            }
            for kind in BENCH_KINDS:
                reporter.test_started(model["name"], profile["name"], kind)
                try:
                    result = backend.run_benchmark(
                        meta["path"],
                        profile,
                        kind,
                        profile_dir,
                        cfg["benchmark"],
                        on_progress=reporter.progress,
                    )
                except Exception as exc:
                    result = {
                        "kind": kind,
                        "status": "failed",
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                reporter.test_finished(
                    result.get("status", "failed"),
                    flatten_bench_rows(result),
                    result.get("error"),
                )
                build_ids.update(build_ids_from_rows(result))
                for warn in (result.get("telemetry") or {}).get("warnings", []):
                    summary["warnings"].append(f"{model['name']}/{profile['name']}/{kind}: {warn}")
                    reporter.note(warn)
                profile_result["benchmarks"][kind] = result
            model_result["profiles"].append(profile_result)

        endpoint_cfg = dict(cfg.get("endpoint", {}))
        endpoint_cfg.update(model.get("endpoint", {}) or {})
        if endpoint_cfg.get("enabled") and not skip_endpoint:
            profile, note = _resolve_endpoint_profile(model, endpoint_cfg)
            if note:
                summary["warnings"].append(note)
            endpoint_dir = ensure_dir(model_dir / "endpoint")
            reporter.note(f"Endpoint-Test fuer {model['name']} laeuft ...")
            proc = None
            try:
                if endpoint_cfg.get("auto_start", True):
                    proc, command = backend.start_server(
                        meta["path"],
                        profile,
                        endpoint_cfg,
                        cfg["benchmark"],
                        endpoint_dir / "llama-server.log",
                    )
                    cold_start_s = backend.wait_health(
                        endpoint_cfg["base_url"],
                        float(endpoint_cfg.get("startup_timeout_seconds", 300)),
                    )
                else:
                    command = None
                    cold_start_s = backend.wait_health(endpoint_cfg["base_url"], 10)

                # Sanity Check: Sicherstellen, dass der Server korrekt generiert.
                passed, msg = asyncio.run(run_sanity_check(endpoint_cfg["base_url"], endpoint_cfg))
                if not passed:
                    summary["warnings"].append(f"{model['name']}: {msg}")
                    reporter.note(f"Warnung: {msg}")

                ep = run_endpoint_load(
                    endpoint_cfg["base_url"],
                    endpoint_cfg,
                    float(cfg["benchmark"].get("resource_sample_interval", 0.5)),
                    endpoint_dir,
                    target_pid=proc.pid if proc else None,
                )
                ep["server_command"] = command
                ep["profile"] = profile.get("name")
                ep["cold_start_seconds"] = cold_start_s
                ep["sanity_check"] = {"passed": passed, "message": msg}
                model_result["endpoint"] = ep
                for warn in (ep.get("telemetry") or {}).get("warnings", []):
                    summary["warnings"].append(f"{model['name']}/endpoint: {warn}")
            except Exception as exc:
                model_result["endpoint"] = {
                    "status": "failed",
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
                summary["warnings"].append(f"{model['name']}: Endpoint-Test fehlgeschlagen: {exc}")
            finally:
                if proc is not None:
                    backend.stop_server(proc)

        summary["models"].append(model_result)
        write_json(run_dir / "summary.partial.json", summary)

    summary["tools"]["llama_cpp_build_ids"] = sorted(build_ids)
    if len(build_ids) > 1:
        summary["warnings"].append(
            "Innerhalb dieses Laufs wurden mehrere llama.cpp-Builds gemeldet: "
            + ", ".join(sorted(build_ids))
        )
    summary["finished_at"] = utc_now_iso()
    write_json(run_dir / "summary.json", summary)
    _write_csv(run_dir / "benchmarks.csv", summary)
    generate_run_html(summary, run_dir / "report.html")
    try:
        generate_run_pdf(summary, run_dir / "report.pdf")
    except Exception as exc:  # PDF ist Beiwerk, der Lauf bleibt gueltig
        summary["warnings"].append(f"PDF-Bericht konnte nicht erzeugt werden: {exc}")
        write_json(run_dir / "summary.json", summary)
        reporter.note(f"PDF-Bericht uebersprungen: {exc}")
    reporter.run_finished()
    print_summary_table(summary)
    return run_dir


def print_summary_table(summary: dict[str, Any]) -> None:
    """Ergebnisuebersicht direkt im Terminal, damit man den Bericht nicht
    erst oeffnen muss."""
    rows: list[tuple[str, str, str, str, str]] = []
    for m in summary.get("models", []):
        model_name = str(m.get("model", {}).get("name") or "?")
        if m.get("status") == "failed":
            rows.append((model_name, "—", "—", "Fehler", str(m.get("error") or "")))
            continue
        for profile in m.get("profiles", []):
            for kind, result in profile.get("benchmarks", {}).items():
                bench_rows = flatten_bench_rows(result)
                if not bench_rows:
                    label = "Zeitueberschreitung" if result.get("status") == "timeout" else "Fehler"
                    rows.append((model_name, str(profile.get("name")), kind, label, ""))
                    continue
                for row in bench_rows:
                    rows.append((
                        model_name,
                        str(profile.get("name")),
                        str(row.get("test")),
                        f"{float(row.get('avg_ts') or 0):.2f}",
                        f"±{float(row.get('stddev_ts') or 0):.2f}",
                    ))
    if not rows:
        return

    headers = ("Modell", "Profil", "Test", "Tokens/s", "Stdabw.")
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]

    def line(values: tuple[str, ...], filler: str = " ") -> str:
        cells = []
        for i, value in enumerate(values):
            cells.append(value.rjust(widths[i]) if i >= 3 else value.ljust(widths[i]))
        return filler.join(cells).rstrip()

    print()
    print("Ergebnisse")
    print(line(headers))
    print("-" * (sum(widths) + len(widths) - 1))
    for row in rows:
        print(line(row))
    warnings = summary.get("warnings") or []
    if warnings:
        print()
        print(f"Hinweise ({len(warnings)}):")
        for warning in warnings[:10]:
            print(f" - {warning}")
        if len(warnings) > 10:
            print(f"   ... und {len(warnings) - 10} weitere, siehe summary.json")


def _write_csv(path: Path, summary: dict[str, Any]) -> None:
    fields = [
        "server_name", "model", "profile", "kind", "status", "test", "avg_ts", "stddev_ts",
        "n_prompt", "n_gen", "n_depth", "n_threads", "n_gpu_layers", "backend",
        "gpu_info", "cpu_info", "build_commit", "config_fingerprint",
    ]
    static = {"server_name", "model", "profile", "kind", "status", "config_fingerprint"}
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for m in summary.get("models", []):
            model_name = m.get("model", {}).get("name")
            for profile in m.get("profiles", []):
                for kind, result in profile.get("benchmarks", {}).items():
                    base = {
                        "server_name": summary.get("server_name"),
                        "model": model_name,
                        "profile": profile.get("name"),
                        "kind": kind,
                        "status": result.get("status"),
                        "config_fingerprint": summary.get("config_fingerprint"),
                    }
                    rows = flatten_bench_rows(result)
                    if not rows:
                        # Fehlgeschlagene Tests bleiben als Zeile sichtbar,
                        # statt aus der Auswertung zu verschwinden.
                        w.writerow({**base, "test": result.get("error")})
                        continue
                    for row in rows:
                        w.writerow({
                            **base,
                            **{k: row.get(k) for k in fields if k not in static},
                        })
