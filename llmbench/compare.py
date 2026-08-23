from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .llama_bench import flatten_bench_rows
from .report import CSS, esc, fms, fnum
from .utils import read_json, write_json


def load_summary(value: str | Path) -> dict[str, Any]:
    p = Path(value)
    if p.is_dir():
        p = p / "summary.json"
    return read_json(p)


def _server(summary: dict[str, Any]) -> str:
    return str(summary.get("server_name") or "unbekannt")


# --------------------------------------------------------------------- Pruefung


def _collect(summaries: list[dict[str, Any]], getter) -> dict[str, Any]:
    return {_server(s): getter(s) for s in summaries}


def _model_hashes(summary: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for m in summary.get("models", []):
        meta = m.get("model", {})
        if meta.get("name"):
            out[str(meta["name"])] = meta.get("sha256")
    return out


def _profile_settings(summary: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for m in summary.get("models", []):
        name = m.get("model", {}).get("name")
        for profile in m.get("profiles", []):
            out[f"{name}/{profile.get('name')}"] = profile.get("settings")
    return out


def check_consistency(summaries: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Prueft, ob die Laeufe ueberhaupt vergleichbar sind.

    Ohne diese Pruefung stellt der Bericht beliebige Zahlen nebeneinander und
    sieht dabei genauso ueberzeugend aus wie ein korrekter Vergleich.
    """
    issues: list[dict[str, str]] = []

    old = [_server(s) for s in summaries if int(s.get("schema_version") or 1) < 2]
    if old:
        issues.append({
            "level": "warning",
            "topic": "Datenstand",
            "message": (
                "Diese Laeufe stammen aus einer aelteren llmbench-Version und enthalten "
                "keine Angaben zu Konfiguration und Build: " + ", ".join(old)
                + ". Sie lassen sich nicht auf Vergleichbarkeit pruefen."
            ),
        })

    def _mismatch(topic: str, values: dict[str, Any], level: str, hint: str) -> None:
        known = {k: v for k, v in values.items() if v not in (None, "", [], {})}
        if len(set(json.dumps(v, sort_keys=True) for v in known.values())) > 1:
            detail = "; ".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in known.items())
            issues.append({"level": level, "topic": topic, "message": f"{hint} ({detail})"})

    _mismatch(
        "Benchmark-Konfiguration",
        _collect(summaries, lambda s: s.get("config_fingerprint")),
        "error",
        "Die Server wurden mit unterschiedlichen Benchmark-Einstellungen gemessen",
    )
    _mismatch(
        "llama.cpp-Build",
        _collect(summaries, lambda s: (s.get("tools") or {}).get("llama_cpp_build_ids")),
        "error",
        "Es kamen unterschiedliche llama.cpp-Builds zum Einsatz",
    )
    _mismatch(
        "llmbench-Version",
        _collect(summaries, lambda s: s.get("llmbench_version")),
        "warning",
        "Die Laeufe wurden mit unterschiedlichen llmbench-Versionen erzeugt",
    )
    _mismatch(
        "llama-bench-Binary",
        _collect(
            summaries,
            lambda s: ((s.get("tools") or {}).get("llama_bench") or {}).get("binary", {}).get("sha256"),
        ),
        "warning",
        "Die llama-bench-Programmdateien unterscheiden sich (bei gleichem Build "
        "auf verschiedenen Betriebssystemen normal)",
    )

    # Modelle: gleiche Datei auf allen Servern?
    hashes = {_server(s): _model_hashes(s) for s in summaries}
    all_models = sorted({name for per_server in hashes.values() for name in per_server})
    for name in all_models:
        present = {srv: per.get(name) for srv, per in hashes.items() if name in per}
        missing = [srv for srv in hashes if name not in hashes[srv]]
        if missing:
            issues.append({
                "level": "warning",
                "topic": f"Modell {name}",
                "message": "Nicht auf allen Servern getestet. Fehlt bei: " + ", ".join(missing),
            })
        known = {k: v for k, v in present.items() if v}
        if len(set(known.values())) > 1:
            detail = "; ".join(f"{k}: {v[:12]}…" for k, v in known.items())
            issues.append({
                "level": "error",
                "topic": f"Modell {name}",
                "message": f"Gleicher Name, aber unterschiedliche GGUF-Dateien ({detail})",
            })
        elif len(known) < len(present):
            issues.append({
                "level": "warning",
                "topic": f"Modell {name}",
                "message": (
                    "Fuer mindestens einen Server fehlt der SHA256. Mit "
                    "project.hash_models: true laesst sich die Dateigleichheit belegen."
                ),
            })

    # Profileinstellungen je Modell
    settings = {_server(s): _profile_settings(s) for s in summaries}
    all_profiles = sorted({key for per in settings.values() for key in per})
    for key in all_profiles:
        values = {srv: per[key] for srv, per in settings.items() if key in per}
        if len({json.dumps(v, sort_keys=True) for v in values.values()}) > 1:
            issues.append({
                "level": "error",
                "topic": f"Profil {key}",
                "message": "Die Profileinstellungen unterscheiden sich zwischen den Servern",
            })

    return issues


# ---------------------------------------------------------------- Datensaetze


def _records(summary: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for m in summary.get("models", []):
        model_name = m.get("model", {}).get("name")
        for profile in m.get("profiles", []):
            for kind, result in profile.get("benchmarks", {}).items():
                rows = flatten_bench_rows(result)
                if not rows:
                    # Fehlschlaege bleiben sichtbar, statt als Luecke zu erscheinen,
                    # die aussieht wie "nicht gemessen".
                    out.append({
                        "server": _server(summary), "model": model_name,
                        "profile": profile.get("name"), "kind": kind,
                        "test": "(alle)", "status": result.get("status") or "failed",
                        "error": result.get("error"), "avg_ts": None, "stddev_ts": None,
                        "n_prompt": None, "n_gen": None, "n_depth": None,
                    })
                    continue
                for row in rows:
                    out.append({
                        "server": _server(summary), "model": model_name,
                        "profile": profile.get("name"), "kind": kind,
                        "test": row.get("test"), "status": "ok", "error": None,
                        "avg_ts": row.get("avg_ts"), "stddev_ts": row.get("stddev_ts"),
                        "n_prompt": row.get("n_prompt"), "n_gen": row.get("n_gen"),
                        "n_depth": row.get("n_depth"),
                    })
    return out


def _endpoint_records(summary: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for m in summary.get("models", []):
        model_name = m.get("model", {}).get("name")
        ep = m.get("endpoint") or {}
        if ep.get("status") != "ok":
            continue
        for level in ep.get("levels", []):
            out.append({
                "server": _server(summary), "model": model_name,
                "concurrency": level.get("concurrency"),
                "system_tps": level.get("system_tps"),
                "avg_interactivity_tps": level.get("avg_interactivity_tps"),
                "ttft_p50_seconds": level.get("ttft_p50_seconds"),
                "ttft_p95_seconds": level.get("ttft_p95_seconds"),
                "successful": level.get("successful"),
                "requests": level.get("requests"),
            })
    return out


def _efficiency_records(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Tokens/s pro Watt. Beide Groessen werden bereits gemessen, nur bisher
    nie zusammengefuehrt - fuer eine Beschaffungsentscheidung oft die Kernzahl."""
    out = []
    for m in summary.get("models", []):
        model_name = m.get("model", {}).get("name")
        for profile in m.get("profiles", []):
            for kind, result in profile.get("benchmarks", {}).items():
                rows = flatten_bench_rows(result)
                if not rows:
                    continue
                telemetry = result.get("telemetry") or {}
                gpus = telemetry.get("gpus") or []
                power = sum(g.get("avg_power_w") or 0.0 for g in gpus)
                best = max((r.get("avg_ts") or 0.0) for r in rows)
                out.append({
                    "server": _server(summary), "model": model_name,
                    "profile": profile.get("name"), "kind": kind,
                    "best_avg_ts": best or None,
                    "avg_gpu_power_w": power or None,
                    "tokens_per_watt": (best / power) if power > 0 and best else None,
                    "max_temperature_c": max(
                        (g.get("max_temperature_c") or 0.0) for g in gpus
                    ) if gpus else None,
                })
    return out


# ------------------------------------------------------------------- Ausgabe


def _issues_html(issues: list[dict[str, str]]) -> str:
    if not issues:
        return (
            "<div class='notice'><strong>Vergleichbarkeit geprueft.</strong> "
            "Konfiguration, llama.cpp-Build, Modelldateien und Profile stimmen "
            "auf allen Servern ueberein.</div>"
        )
    errors = [i for i in issues if i["level"] == "error"]
    cls = "warn" if not errors else "warn"
    head = (
        f"<strong>{len(errors)} Abweichung(en), die den Vergleich ungueltig machen</strong>"
        if errors
        else "<strong>Hinweise zur Vergleichbarkeit</strong>"
    )
    items = "".join(
        f"<li><strong>{esc(i['topic'])}:</strong> {esc(i['message'])}</li>"
        for i in sorted(issues, key=lambda x: 0 if x["level"] == "error" else 1)
    )
    return f"<div class='{cls}'>{head}<ul>{items}</ul></div>"


def _status_cell(status: str | None, error: str | None = None) -> str:
    label = "Zeitueberschreitung" if status == "timeout" else "Fehler"
    cls = "status-timeout" if status == "timeout" else "status-failed"
    title = f" title='{esc(error)}'" if error else ""
    return f"<td class='num'><span class='{cls}'{title}>{label}</span></td>"


def _bench_table_html(records: list[dict[str, Any]], servers: list[str]) -> str:
    ok_records = [r for r in records if r.get("status") == "ok"]
    # Ein fehlgeschlagener Testbereich liefert keine einzelnen Testzeilen.
    # Er wird trotzdem in jeder Zeile dieses Bereichs angezeigt, damit ein
    # Ausfall nicht wie "nicht getestet" aussieht.
    failures = {
        (r["server"], r["model"], r["profile"], r["kind"]): r
        for r in records if r.get("status") != "ok"
    }

    keys = sorted({(r["model"], r["profile"], r["kind"], r["test"]) for r in ok_records})
    covered = {(k[0], k[1], k[2]) for k in keys}
    for _server_name, model, profile, kind in failures:
        if (model, profile, kind) not in covered:
            keys.append((model, profile, kind, "(gesamter Bereich)"))
            covered.add((model, profile, kind))
    keys = sorted(set(keys))

    lookup = {(r["server"], r["model"], r["profile"], r["kind"], r["test"]): r for r in ok_records}
    rows_html = []
    for key in keys:
        model, profile, kind, _test = key
        numeric = [
            float(lookup[(s, *key)]["avg_ts"])
            for s in servers
            if (s, *key) in lookup and lookup[(s, *key)].get("avg_ts") is not None
        ]
        best = max(numeric) if numeric else None
        cells = []
        for server in servers:
            rec = lookup.get((server, *key))
            if rec is None:
                fail = failures.get((server, model, profile, kind))
                if fail:
                    cells.append(_status_cell(fail.get("status"), fail.get("error")))
                else:
                    cells.append("<td class='num muted'>nicht getestet</td>")
                continue
            value = float(rec["avg_ts"])
            is_best = best is not None and abs(value - best) < 1e-9
            rel = ""
            if best and not is_best:
                rel = f"<br><span class='small muted'>{value / best * 100:.0f} %</span>"
            cells.append(
                f"<td class='num'>{'<strong>' if is_best else ''}{fnum(value)}"
                f"{'</strong>' if is_best else ''}{rel}</td>"
            )
        rows_html.append(
            f"<tr><td>{esc(key[0])}</td><td>{esc(key[1])}</td><td>{esc(key[2])}</td>"
            f"<td>{esc(key[3])}</td>{''.join(cells)}</tr>"
        )
    header = "".join(f"<th class='num'>{esc(s)}</th>" for s in servers)
    return (
        "<div class='table-wrap'><table><thead><tr><th>Modell</th><th>Profil</th><th>Bereich</th>"
        f"<th>Test</th>{header}</tr></thead><tbody>{''.join(rows_html)}</tbody></table></div>"
    )


def _endpoint_table_html(records: list[dict[str, Any]], servers: list[str]) -> str:
    if not records:
        return "<p class='muted'>Keine Endpoint-Ergebnisse in den verglichenen Laeufen.</p>"
    keys = sorted({(r["model"], r["concurrency"]) for r in records})
    lookup = {(r["server"], r["model"], r["concurrency"]): r for r in records}
    rows = []
    for model, conc in keys:
        cells = []
        for server in servers:
            rec = lookup.get((server, model, conc))
            if not rec:
                cells.append("<td class='num muted'>—</td><td class='num muted'>—</td>")
                continue
            cells.append(
                f"<td class='num'>{fnum(rec.get('system_tps'))}</td>"
                f"<td class='num'>{fms(rec.get('ttft_p95_seconds'))}</td>"
            )
        rows.append(
            f"<tr><td>{esc(model)}</td><td class='num'>{esc(conc)}</td>{''.join(cells)}</tr>"
        )
    header = "".join(
        f"<th class='num'>{esc(s)}<br><span class='small'>TPS</span></th>"
        f"<th class='num'>{esc(s)}<br><span class='small'>TTFT P95 ms</span></th>"
        for s in servers
    )
    return (
        "<div class='table-wrap'><table><thead><tr><th>Modell</th>"
        f"<th class='num'>Concurrency</th>{header}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _efficiency_table_html(records: list[dict[str, Any]], servers: list[str]) -> str:
    usable = [r for r in records if r.get("tokens_per_watt")]
    if not usable:
        return (
            "<p class='muted'>Keine GPU-Leistungsdaten verfuegbar. "
            "Tokens/s pro Watt wird nur fuer NVIDIA-GPUs mit NVML erfasst.</p>"
        )
    keys = sorted({(r["model"], r["profile"], r["kind"]) for r in usable})
    lookup = {(r["server"], r["model"], r["profile"], r["kind"]): r for r in usable}
    rows = []
    for key in keys:
        cells = []
        for server in servers:
            rec = lookup.get((server, *key))
            if not rec:
                cells.append("<td class='num muted'>—</td>")
                continue
            cells.append(
                f"<td class='num'>{fnum(rec.get('tokens_per_watt'), 3)}"
                f"<br><span class='small muted'>{fnum(rec.get('avg_gpu_power_w'), 0)} W</span></td>"
            )
        rows.append(
            f"<tr><td>{esc(key[0])}</td><td>{esc(key[1])}</td><td>{esc(key[2])}</td>"
            f"{''.join(cells)}</tr>"
        )
    header = "".join(f"<th class='num'>{esc(s)}</th>" for s in servers)
    return (
        "<div class='table-wrap'><table><thead><tr><th>Modell</th><th>Profil</th><th>Bereich</th>"
        f"{header}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def _hardware_table_html(summaries: list[dict[str, Any]]) -> str:
    rows = []
    for s in summaries:
        hw = s.get("hardware", {})
        gpus = hw.get("gpus") or []
        gpu_text = "<br>".join(
            f"{esc(g.get('name'))} ({fnum(g.get('memory.total'), 0)} MiB)" for g in gpus
        ) or "keine"
        rows.append(
            f"<tr><td>{esc(_server(s))}</td><td>{esc(hw.get('cpu', {}).get('name'))}</td>"
            f"<td>{gpu_text}</td>"
            f"<td class='num'>{fnum((hw.get('memory', {}).get('total_bytes') or 0) / (1024 ** 3))} GiB</td>"
            f"<td class='small'>{esc(hw.get('power_scheme') or 'unbekannt')}</td></tr>"
        )
    return (
        "<div class='table-wrap'><table><thead><tr><th>Server</th><th>CPU</th><th>GPU</th>"
        "<th class='num'>RAM</th><th>Energieplan</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def compare_summaries(inputs: list[str | Path], out_dir: str | Path) -> tuple[Path, list[dict[str, str]]]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summaries = [load_summary(x) for x in inputs]
    servers = [_server(s) for s in summaries]

    issues = check_consistency(summaries)
    records = [r for s in summaries for r in _records(s)]
    endpoint_records = [r for s in summaries for r in _endpoint_records(s)]
    efficiency = [r for s in summaries for r in _efficiency_records(s)]

    write_json(out / "comparison.json", {
        "servers": servers,
        "consistency": issues,
        "records": records,
        "endpoint": endpoint_records,
        "efficiency": efficiency,
    })

    bench_fields = ["server", "model", "profile", "kind", "test", "status", "error",
                    "avg_ts", "stddev_ts", "n_prompt", "n_gen", "n_depth"]
    with (out / "comparison.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=bench_fields)
        w.writeheader()
        w.writerows(records)

    if endpoint_records:
        ep_fields = ["server", "model", "concurrency", "system_tps", "avg_interactivity_tps",
                     "ttft_p50_seconds", "ttft_p95_seconds", "successful", "requests"]
        with (out / "comparison_endpoint.csv").open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=ep_fields)
            w.writeheader()
            w.writerows(endpoint_records)

    page = (
        "<!doctype html><html lang='de'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>LLM Server Vergleich</title><style>{CSS}</style></head><body><main>"
        "<h1>LLM Server Vergleich</h1>"
        "<p class='muted'>Gleiche Modell-, Profil- und Testkombinationen stehen nebeneinander. "
        "Der jeweils hoechste Tokens/s-Wert ist fett markiert, darunter der Abstand zum Besten.</p>"
        + _issues_html(issues)
        + "<h2>Hardware</h2>" + _hardware_table_html(summaries)
        + "<h2>Benchmark-Vergleich</h2>" + _bench_table_html(records, servers)
        + "<h2>Endpoint- und Mehrbenutzer-Vergleich</h2>" + _endpoint_table_html(endpoint_records, servers)
        + "<h2>Effizienz (Tokens/s pro Watt)</h2>" + _efficiency_table_html(efficiency, servers)
        + "</main></body></html>"
    )
    report = out / "comparison.html"
    report.write_text(page, encoding="utf-8")
    return report, issues
