from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .llama_bench import flatten_bench_rows
from .report import CSS, esc, fnum
from .utils import read_json, write_json


def load_summary(value: str | Path) -> dict[str, Any]:
    p = Path(value)
    if p.is_dir():
        p = p / "summary.json"
    return read_json(p)


def _records(summary: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for m in summary.get("models", []):
        model_name = m.get("model", {}).get("name")
        for profile in m.get("profiles", []):
            for kind, result in profile.get("benchmarks", {}).items():
                for row in flatten_bench_rows(result):
                    out.append({"server": summary.get("server_name"), "model": model_name, "profile": profile.get("name"), "kind": kind, "test": row.get("test"), "avg_ts": row.get("avg_ts"), "stddev_ts": row.get("stddev_ts"), "n_prompt": row.get("n_prompt"), "n_gen": row.get("n_gen"), "n_depth": row.get("n_depth")})
    return out


def compare_summaries(inputs: list[str | Path], out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summaries = [load_summary(x) for x in inputs]
    records = [r for s in summaries for r in _records(s)]
    write_json(out / "comparison.json", {"servers": [s.get("server_name") for s in summaries], "records": records})
    with (out / "comparison.csv").open("w", newline="", encoding="utf-8-sig") as f:
        fields = ["server", "model", "profile", "kind", "test", "avg_ts", "stddev_ts", "n_prompt", "n_gen", "n_depth"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(records)
    servers = [str(s.get("server_name")) for s in summaries]
    keys = sorted({(r["model"], r["profile"], r["kind"], r["test"]) for r in records})
    lookup = {(r["server"], r["model"], r["profile"], r["kind"], r["test"]): r for r in records}
    rows_html = []
    for key in keys:
        vals = []
        numeric = []
        for server in servers:
            rec = lookup.get((server, *key))
            value = rec.get("avg_ts") if rec else None
            try:
                numeric.append(float(value))
            except Exception:
                pass
        best = max(numeric) if numeric else None
        for server in servers:
            rec = lookup.get((server, *key))
            v = rec.get("avg_ts") if rec else None
            try:
                is_best = best is not None and abs(float(v) - best) < 1e-9
            except Exception:
                is_best = False
            vals.append(f"<td class='num'>{'<strong>' if is_best else ''}{fnum(v)}{'</strong>' if is_best else ''}</td>")
        rows_html.append(f"<tr><td>{esc(key[0])}</td><td>{esc(key[1])}</td><td>{esc(key[2])}</td><td>{esc(key[3])}</td>{''.join(vals)}</tr>")
    hw_rows = []
    for s in summaries:
        hw = s.get("hardware", {})
        gpu = (hw.get("gpus") or [{}])[0]
        hw_rows.append(f"<tr><td>{esc(s.get('server_name'))}</td><td>{esc(hw.get('cpu',{}).get('name'))}</td><td>{esc(gpu.get('name'))}</td><td class='num'>{fnum(gpu.get('memory.total'),0)} MiB</td><td class='num'>{fnum((hw.get('memory',{}).get('total_bytes') or 0)/(1024**3))} GiB</td></tr>")
    page = ("<!doctype html><html lang='de'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>" f"<title>LLM Server Vergleich</title><style>{CSS}</style></head><body><main>" "<h1>LLM Server Vergleich</h1><p class='muted'>Gleiche Modell-/Profil-/Testkombinationen werden direkt gegenübergestellt. Der jeweils höchste Tokens/s-Wert ist fett markiert.</p>" "<h2>Hardware</h2><table><thead><tr><th>Server</th><th>CPU</th><th>GPU</th><th class='num'>VRAM</th><th class='num'>RAM</th></tr></thead>" f"<tbody>{''.join(hw_rows)}</tbody></table>" "<h2>Benchmark-Vergleich</h2><table><thead><tr><th>Modell</th><th>Profil</th><th>Bereich</th><th>Test</th>" + "".join(f"<th class='num'>{esc(s)}</th>" for s in servers) + f"</tr></thead><tbody>{''.join(rows_html)}</tbody></table>" "</main></body></html>")
    report = out / "comparison.html"
    report.write_text(page, encoding="utf-8")
    return report
