from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from .llama_bench import flatten_bench_rows
from .utils import human_bytes

CSS = r"""
:root { color-scheme: light; --fg:#15202b; --muted:#5d6b78; --line:#d8dee4; --soft:#f5f7f9; --accent:#1769aa; --good:#177245; --bad:#a12622; }
* { box-sizing: border-box; } body { margin:0; font-family: Inter, Segoe UI, Arial, sans-serif; color:var(--fg); background:#fff; }
main { max-width: 1180px; margin: 0 auto; padding: 36px 28px 64px; } h1 { font-size: 32px; margin: 0 0 4px; }
h2 { margin-top: 34px; padding-bottom: 8px; border-bottom:1px solid var(--line); } h3 { margin-top: 26px; } p { line-height:1.5; }
.muted { color:var(--muted); } .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:12px; margin:20px 0; }
.card { border:1px solid var(--line); border-radius:10px; padding:14px; background:var(--soft); } .card .k { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
.card .v { font-size:19px; font-weight:650; margin-top:4px; } table { width:100%; border-collapse:collapse; margin:12px 0 24px; font-size:14px; }
th,td { border:1px solid var(--line); padding:8px 10px; text-align:left; vertical-align:top; } th { background:#eef2f6; }
td.num,th.num { text-align:right; font-variant-numeric:tabular-nums; } .status-ok { color:var(--good); font-weight:650; } .status-failed { color:var(--bad); font-weight:650; }
code { background:#eef2f6; border-radius:4px; padding:1px 5px; } .small { font-size:12px; } .notice { border-left:4px solid var(--accent); background:#f2f7fc; padding:10px 14px; margin:16px 0; }
@media print { main { max-width:none; padding:12mm; } .no-print { display:none; } }
"""


def esc(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def fnum(v: Any, digits: int = 2) -> str:
    try:
        return f"{float(v):.{digits}f}"
    except Exception:
        return "—"


def _gpu_text(hw: dict[str, Any]) -> str:
    gpus = hw.get("gpus") or []
    if not gpus:
        return "Keine NVIDIA-GPU erkannt"
    return "<br>".join(f"{esc(g.get('name'))} ({fnum(g.get('memory.total'),0)} MiB VRAM)" for g in gpus)


def _bench_table(model: dict[str, Any], profile: dict[str, Any]) -> str:
    rows_html: list[str] = []
    for kind, result in profile.get("benchmarks", {}).items():
        if result.get("status") != "ok":
            rows_html.append(f"<tr><td>{esc(kind)}</td><td colspan='6' class='status-failed'>Fehler: {esc(result.get('error'))}</td></tr>")
            continue
        for row in flatten_bench_rows(result):
            rows_html.append("<tr>" f"<td>{esc(kind)}</td>" f"<td>{esc(row.get('test'))}</td>" f"<td class='num'><strong>{fnum(row.get('avg_ts'))}</strong></td>" f"<td class='num'>{fnum(row.get('stddev_ts'))}</td>" f"<td class='num'>{esc(row.get('n_prompt'))}</td>" f"<td class='num'>{esc(row.get('n_gen'))}</td>" f"<td class='num'>{esc(row.get('n_depth'))}</td>" "</tr>")
    return "<table><thead><tr><th>Bereich</th><th>Test</th><th class='num'>Tokens/s</th><th class='num'>Stdabw.</th><th class='num'>Prompt</th><th class='num'>Gen.</th><th class='num'>Depth</th></tr></thead><tbody>" + "".join(rows_html) + "</tbody></table>"


def _telemetry_table(profile: dict[str, Any]) -> str:
    rows = []
    for kind, result in profile.get("benchmarks", {}).items():
        t = result.get("telemetry") or {}
        gpu = (t.get("gpus") or [{}])[0] if t.get("gpus") else {}
        rows.append("<tr>" f"<td>{esc(kind)}</td>" f"<td class='num'>{fnum(t.get('avg_cpu_percent'))}%</td>" f"<td class='num'>{fnum(t.get('max_cpu_percent'))}%</td>" f"<td class='num'>{human_bytes(t.get('max_ram_used_bytes'))}</td>" f"<td class='num'>{fnum(gpu.get('avg_util_gpu_percent'))}%</td>" f"<td class='num'>{human_bytes(gpu.get('max_memory_used_bytes'))}</td>" f"<td class='num'>{fnum(gpu.get('avg_power_w'))} W</td>" "</tr>")
    return "<table><thead><tr><th>Bereich</th><th class='num'>CPU Ø</th><th class='num'>CPU Max</th><th class='num'>RAM Max</th><th class='num'>GPU Ø</th><th class='num'>VRAM Max</th><th class='num'>GPU Power Ø</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"


def _endpoint_table(ep: dict[str, Any]) -> str:
    if not ep:
        return ""
    if ep.get("status") != "ok":
        return f"<p class='status-failed'>Endpoint-Test fehlgeschlagen: {esc(ep.get('error'))}</p>"
    rows = []
    for x in ep.get("levels", []):
        rows.append("<tr>" f"<td class='num'>{esc(x.get('concurrency'))}</td>" f"<td class='num'>{esc(x.get('successful'))}/{esc(x.get('requests'))}</td>" f"<td class='num'><strong>{fnum(x.get('system_tps'))}</strong></td>" f"<td class='num'>{fnum(x.get('avg_interactivity_tps'))}</td>" f"<td class='num'>{fnum((x.get('ttft_p50_seconds') or 0)*1000)}</td>" f"<td class='num'>{fnum((x.get('ttft_p95_seconds') or 0)*1000)}</td>" "</tr>")
    return "<table><thead><tr><th class='num'>Concurrency</th><th class='num'>Erfolgreich</th><th class='num'>System TPS</th><th class='num'>TPS/Request</th><th class='num'>TTFT P50 ms</th><th class='num'>TTFT P95 ms</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"


def generate_run_html(summary: dict[str, Any], path: str | Path) -> None:
    hw = summary.get("hardware", {})
    cards = [("Server", summary.get("server_name")), ("CPU", hw.get("cpu", {}).get("name")), ("RAM", human_bytes(hw.get("memory", {}).get("total_bytes"))), ("GPU", _gpu_text(hw))]
    body = ["<!doctype html><html lang='de'><head><meta charset='utf-8'>", "<meta name='viewport' content='width=device-width,initial-scale=1'>", f"<title>{esc(summary.get('server_name'))} – LLM Benchmark</title><style>{CSS}</style></head><body><main>", f"<h1>LLM Server Benchmark – {esc(summary.get('server_name'))}</h1>", f"<p class='muted'>Projekt: {esc(summary.get('project'))} · Start: {esc(summary.get('started_at'))}</p>", "<div class='cards'>"]
    for k, v in cards:
        body.append(f"<div class='card'><div class='k'>{esc(k)}</div><div class='v'>{v if k=='GPU' else esc(v)}</div></div>")
    body.extend(["</div>", "<div class='notice'>Tokens/s aus <code>llama-bench</code> messen Inferenzkernleistung ohne Tokenisierung und Sampling. Endpoint-Tests messen zusätzlich reale Server-Interaktivität und TTFT.</div>"])
    for m in summary.get("models", []):
        meta = m.get("model", {})
        body.append(f"<h2>{esc(meta.get('name'))}</h2><div class='cards'>")
        body.append(f"<div class='card'><div class='k'>GGUF-Größe</div><div class='v'>{human_bytes(meta.get('size_bytes'))}</div></div>")
        body.append(f"<div class='card'><div class='k'>SHA256</div><div class='v small'>{esc((meta.get('sha256') or 'nicht berechnet')[:20])}…</div></div>")
        body.append(f"<div class='card'><div class='k'>Quality Gate</div><div class='v'>{esc(meta.get('quality_gate') or 'nicht bewertet')}</div></div></div>")
        for profile in m.get("profiles", []):
            body.append(f"<h3>Profil: {esc(profile.get('name'))}</h3>")
            s = profile.get("settings", {})
            body.append(f"<p class='muted'>GPU-Layer: <code>{esc(s.get('gpu_layers'))}</code> · Threads: <code>{esc(s.get('threads','auto'))}</code></p>")
            body.append(_bench_table(m, profile))
            body.append("<h3>Hardware-Telemetrie</h3>")
            body.append(_telemetry_table(profile))
        if m.get("endpoint"):
            body.append("<h3>Endpoint-/Multi-User-Test</h3>")
            body.append(_endpoint_table(m["endpoint"]))
    body.append("<p class='muted small'>Erzeugt mit llm-server-benchmark.</p></main></body></html>")
    Path(path).write_text("".join(body), encoding="utf-8")
