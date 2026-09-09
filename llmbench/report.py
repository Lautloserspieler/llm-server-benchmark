from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from .llama_bench import flatten_bench_rows
from .utils import human_bytes
from .i18n import _

CSS = r"""
:root { color-scheme: light dark; --fg:#15202b; --muted:#5d6b78; --line:#d8dee4; --soft:#f5f7f9;
        --accent:#1769aa; --good:#177245; --bad:#a12622; --warn:#8a5a11; --bg:#fff; --th:#eef2f6; }
@media (prefers-color-scheme: dark) {
  :root { --fg:#e3eaef; --muted:#9fb0bb; --line:#2b3841; --soft:#18222a; --accent:#5fb3d4;
          --good:#5fbf8b; --bad:#e2806c; --warn:#d7a94f; --bg:#0f161b; --th:#1c2831; }
}
* { box-sizing: border-box; } body { margin:0; font-family: Inter, Segoe UI, Arial, sans-serif; color:var(--fg); background:var(--bg); }
main { max-width: 1180px; margin: 0 auto; padding: 36px 28px 64px; } h1 { font-size: 32px; margin: 0 0 4px; }
h2 { margin-top: 34px; padding-bottom: 8px; border-bottom:1px solid var(--line); } h3 { margin-top: 26px; } p { line-height:1.5; }
.muted { color:var(--muted); } .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:12px; margin:20px 0; }
.card { border:1px solid var(--line); border-radius:10px; padding:14px; background:var(--soft); } .card .k { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
.card .v { font-size:19px; font-weight:650; margin-top:4px; word-break:break-word; }
.table-wrap { overflow-x:auto; } table { width:100%; border-collapse:collapse; margin:12px 0 24px; font-size:14px; }
th,td { border:1px solid var(--line); padding:8px 10px; text-align:left; vertical-align:top; } th { background:var(--th); }
td.num,th.num { text-align:right; font-variant-numeric:tabular-nums; } .status-ok { color:var(--good); font-weight:650; }
.status-failed { color:var(--bad); font-weight:650; } .status-timeout { color:var(--warn); font-weight:650; }
code { background:var(--th); border-radius:4px; padding:1px 5px; } .small { font-size:12px; }
.notice { border-left:4px solid var(--accent); background:var(--soft); padding:10px 14px; margin:16px 0; }
.warn { border-left:4px solid var(--warn); background:var(--soft); padding:10px 14px; margin:16px 0; }
.warn ul { margin:6px 0 0 18px; padding:0; } .warn li { margin:3px 0; }
@media print { main { max-width:none; padding:12mm; } .no-print { display:none; } }
"""


def esc(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def fnum(v: Any, digits: int = 2) -> str:
    try:
        if v is None:
            return "—"
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def fms(seconds: Any) -> str:
    """Sekunden als Millisekunden. Fehlende Werte bleiben leer statt 0,00."""
    if seconds is None:
        return "—"
    try:
        return f"{float(seconds) * 1000:.2f}"
    except (TypeError, ValueError):
        return "—"


def status_cell(status: str | None) -> str:
    cls = {"ok": "status-ok", "timeout": "status-timeout"}.get(str(status), "status-failed")
    label = {"ok": "OK", "timeout": "Zeitueberschreitung", "failed": "Fehler"}.get(str(status), str(status))
    return f"<span class='{cls}'>{esc(_(label))}</span>"


def _gpu_text(hw: dict[str, Any]) -> str:
    gpus = hw.get("gpus") or []
    if not gpus:
        return _("Keine GPU erkannt")
    parts = []
    for g in gpus:
        vram = g.get("memory.total")
        vram_text = f"{fnum(vram, 0)} MiB VRAM" if vram else _("VRAM unbekannt")
        note = "" if g.get("telemetry") == "nvml" else _(" · keine Telemetrie")
        parts.append(f"{esc(g.get('vendor') or '')} {esc(g.get('name'))} ({vram_text}{note})")
    return "<br>".join(parts)


def _warnings_block(summary: dict[str, Any]) -> str:
    warnings = summary.get("warnings") or []
    if not warnings:
        return ""
    items = "".join(f"<li>{esc(w)}</li>" for w in warnings)
    return (
        f"<div class='warn'><strong>{_('Hinweise zu diesem Lauf')}</strong>"
        f"<ul>{items}</ul></div>"
    )


def _bench_table(profile: dict[str, Any]) -> str:
    rows_html: list[str] = []
    for kind, result in profile.get("benchmarks", {}).items():
        if result.get("status") != "ok":
            rows_html.append(
                f"<tr><td>{esc(kind)}</td><td>{status_cell(result.get('status'))}</td>"
                f"<td colspan='6'>{esc(result.get('error'))}</td></tr>"
            )
            continue
        for row in flatten_bench_rows(result):
            rows_html.append(
                "<tr>"
                f"<td>{esc(kind)}</td><td>{status_cell('ok')}</td>"
                f"<td>{esc(row.get('test'))}</td>"
                f"<td class='num'><strong>{fnum(row.get('avg_ts'))}</strong></td>"
                f"<td class='num'>{fnum(row.get('stddev_ts'))}</td>"
                f"<td class='num'>{esc(row.get('n_prompt'))}</td>"
                f"<td class='num'>{esc(row.get('n_gen'))}</td>"
                f"<td class='num'>{esc(row.get('n_depth'))}</td>"
                "</tr>"
            )
    return (
        f"<div class='table-wrap'><table><thead><tr><th>{_('Bereich')}</th><th>{_('Status')}</th><th>{_('Test')}</th>"
        f"<th class='num'>{_('Tokens/s')}</th><th class='num'>{_('Stdabw.')}</th><th class='num'>{_('Prompt')}</th>"
        f"<th class='num'>{_('Gen.')}</th><th class='num'>{_('Depth')}</th></tr></thead><tbody>"
        + "".join(rows_html)
        + "</tbody></table></div>"
    )


def _telemetry_table(profile: dict[str, Any]) -> str:
    rows = []
    for kind, result in profile.get("benchmarks", {}).items():
        t = result.get("telemetry") or {}
        gpus = t.get("gpus") or [{}]
        for gpu in gpus:
            rows.append(
                "<tr>"
                f"<td>{esc(kind)}</td>"
                f"<td class='num'>{esc(gpu.get('index', 0))}</td>"
                f"<td class='num'>{fnum(t.get('avg_cpu_percent'))}%</td>"
                f"<td class='num'>{fnum(t.get('max_cpu_percent'))}%</td>"
                f"<td class='num'>{human_bytes(t.get('max_ram_used_bytes'))}</td>"
                f"<td class='num'>{fnum(gpu.get('avg_util_gpu_percent'))}%</td>"
                f"<td class='num'>{human_bytes(gpu.get('max_memory_used_bytes'))}</td>"
                f"<td class='num'>{fnum(gpu.get('avg_power_w'))} W</td>"
                f"<td class='num'>{fnum(gpu.get('max_temperature_c'), 0)} °C</td>"
                "</tr>"
            )
    return (
        f"<div class='table-wrap'><table><thead><tr><th>{_('Bereich')}</th><th class='num'>{_('GPU')}</th>"
        f"<th class='num'>{_('CPU Ø')}</th><th class='num'>{_('CPU Max')}</th><th class='num'>{_('RAM Max')}</th>"
        f"<th class='num'>{_('GPU Ø')}</th><th class='num'>{_('VRAM Max')}</th><th class='num'>{_('GPU Power Ø')}</th>"
        f"<th class='num'>{_('Temp Max')}</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _endpoint_table(ep: dict[str, Any]) -> str:
    if not ep:
        return ""
    if ep.get("status") != "ok":
        return f"<p class='status-failed'>{_('Endpoint-Test fehlgeschlagen')}: {esc(ep.get('error'))}</p>"
    settings = ep.get("settings") or {}
    head = (
        f"<p class='muted small'>{_('Profil')}: <code>{esc(ep.get('profile'))}</code> · "
        f"max_tokens {esc(settings.get('max_tokens'))} · seed {esc(settings.get('seed'))} · "
        f"ignore_eos {esc(settings.get('ignore_eos'))} · "
        f"Warmup {esc((ep.get('warmup') or {}).get('requests'))} {_('Requests (verworfen)')}</p>"
    )
    rows = []
    for x in ep.get("levels", []):
        note = f"<br><span class='small status-timeout'>{esc(x.get('note'))}</span>" if x.get("note") else ""
        rows.append(
            "<tr>"
            f"<td class='num'>{esc(x.get('concurrency'))}</td>"
            f"<td class='num'>{esc(x.get('successful'))}/{esc(x.get('requests'))}{note}</td>"
            f"<td class='num'><strong>{fnum(x.get('system_tps'))}</strong></td>"
            f"<td class='num'>{fnum(x.get('avg_interactivity_tps'))}</td>"
            f"<td class='num'>{fms(x.get('ttft_p50_seconds'))}</td>"
            f"<td class='num'>{fms(x.get('ttft_p95_seconds'))}</td>"
            "</tr>"
        )
    return head + (
        f"<div class='table-wrap'><table><thead><tr><th class='num'>{_('Concurrency')}</th>"
        f"<th class='num'>{_('Erfolgreich')}</th><th class='num'>{_('System TPS')}</th>"
        f"<th class='num'>{_('TPS/Request')}</th><th class='num'>{_('TTFT P50 ms')}</th>"
        f"<th class='num'>{_('TTFT P95 ms')}</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _soak_table(soak_runs: list[dict[str, Any]]) -> str:
    if not soak_runs:
        return ""
    rows = []
    for run in soak_runs:
        if run.get("status") != "ok":
            rows.append(
                f"<tr><td>{esc(run.get('label'))}</td>"
                f"<td colspan='6'>{status_cell(run.get('status'))} {esc(run.get('error'))}</td></tr>"
            )
            continue
        for path_label, path_data in (("CPU", run.get("cpu") or {}), ("GPU", run.get("gpu") or {})):
            throttle = (
                f"<span class='status-timeout'>{_('Ja')}</span>" if path_data.get("throttling_suspected") else _("Nein")
            )
            rows.append(
                "<tr>"
                f"<td>{esc(run.get('label'))}</td>"
                f"<td>{esc(path_label)}</td>"
                f"<td class='num'>{fnum(path_data.get('avg_tps'))}</td>"
                f"<td class='num'>{fnum(path_data.get('early_window_avg_tps'))}</td>"
                f"<td class='num'>{fnum(path_data.get('late_window_avg_tps'))}</td>"
                f"<td class='num'>{esc(path_data.get('successful', 0))}/{esc(path_data.get('requests', 0))}</td>"
                f"<td>{throttle}</td>"
                "</tr>"
            )
    temp_parts = []
    for run in soak_runs:
        for gpu in (run.get("telemetry") or {}).get("gpus") or []:
            if gpu.get("max_temperature_c"):
                temp_parts.append(f"{esc(run.get('label'))}: GPU {esc(gpu.get('index', 0))} {fnum(gpu.get('max_temperature_c'), 0)} °C")
    temp_note = f"<p class='muted small'>{_('Maximaltemperatur waehrend der Dauerlast: ')} {', '.join(temp_parts)}</p>" if temp_parts else ""
    return (
        f"<div class='table-wrap'><table><thead><tr><th>{_('Dauer')}</th><th>{_('Pfad')}</th>"
        f"<th class='num'>{_('Ø Tokens/s')}</th><th class='num'>{_('Frueh')}</th><th class='num'>{_('Spaet')}</th>"
        f"<th class='num'>{_('Erfolgreich')}</th><th>{_('Throttling')}</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table></div>" + temp_note
    )


def _provenance_block(summary: dict[str, Any]) -> str:
    tools = summary.get("tools") or {}
    bench = (tools.get("llama_bench") or {}).get("binary") or {}
    build_ids = tools.get("llama_cpp_build_ids") or []
    cfg = (summary.get("config") or {}).get("benchmark") or {}
    rows = [
        (_("Konfigurations-Fingerabdruck"), summary.get("config_fingerprint")),
        (_("llmbench-Version"), summary.get("llmbench_version")),
        (_("llama.cpp-Build"), ", ".join(build_ids) or _("unbekannt")),
        (_("llama-bench SHA256"), (bench.get("sha256") or _("nicht berechnet"))),
        (_("Wiederholungen"), cfg.get("repetitions")),
        (_("Batch / UBatch"), f"{cfg.get('batch_size')} / {cfg.get('ubatch_size')}"),
        (_("Flash Attention"), cfg.get("flash_attention")),
        (_("KV-Cache K/V"), f"{cfg.get('cache_type_k')} / {cfg.get('cache_type_v')}"),
    ]
    cells = "".join(
        f"<tr><th>{esc(k)}</th><td><code>{esc(v)}</code></td></tr>" for k, v in rows
    )
    return (
        f"<h2>{_('Nachweis der Testbedingungen')}</h2>"
        f"<p class='muted'>{_('Diese Angaben muessen auf allen verglichenen Servern uebereinstimmen. ')}"
        "<code>llmbench compare</code> {_('prueft das automatisch.')}</p>"
        f"<div class='table-wrap'><table><tbody>{cells}</tbody></table></div>"
    )


def generate_run_html(summary: dict[str, Any], path: str | Path) -> None:
    hw = summary.get("hardware", {})
    cards = [
        (_("Server"), summary.get("server_name")),
        (_("CPU"), hw.get("cpu", {}).get("name")),
        (_("RAM"), human_bytes(hw.get("memory", {}).get("total_bytes"))),
        (_("GPU"), _gpu_text(hw)),
    ]
    body = [
        "<!doctype html><html lang='de'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{esc(summary.get('server_name'))} – LLM Benchmark</title><style>{CSS}</style>",
        "</head><body><main>",
        f"<h1>{_('LLM Server Benchmark')} – {esc(summary.get('server_name'))}</h1>",
        f"<p class='muted'>{_('Projekt')}: {esc(summary.get('project'))} · {_('Start')}: {esc(summary.get('started_at'))} "
        f"· {_('Energieplan')}: {esc(hw.get('power_scheme') or _('unbekannt'))}</p>",
        "<div class='cards'>",
    ]
    for k, v in cards:
        body.append(
            f"<div class='card'><div class='k'>{esc(k)}</div>"
            f"<div class='v'>{v if k == _('GPU') else esc(v)}</div></div>"
        )
    body.append("</div>")
    body.append(_warnings_block(summary))
    body.append(
        f"<div class='notice'>{_('Tokens/s aus <code>llama-bench</code> messen die Inferenzkernleistung ')}"
        f"{_('ohne Tokenisierung und Sampling. Endpoint-Tests messen zusaetzlich reale ')}"
        f"{_('Server-Interaktivitaet und TTFT.')}</div>"
    )
    body.append(_provenance_block(summary))

    for m in summary.get("models", []):
        meta = m.get("model", {})
        body.append(f"<h2>{esc(meta.get('name'))}</h2>")
        if m.get("status") == "failed":
            body.append(f"<p class='status-failed'>{esc(m.get('error'))}</p>")
            continue
        body.append("<div class='cards'>")
        body.append(
            f"<div class='card'><div class='k'>{_('GGUF-Groesse')}</div>"
            f"<div class='v'>{human_bytes(meta.get('size_bytes'))}</div></div>"
        )
        sha = meta.get("sha256") or _("nicht berechnet")
        body.append(
            f"<div class='card'><div class='k'>SHA256</div>"
            f"<div class='v small'><code>{esc(sha[:32])}{'…' if len(sha) > 32 else ''}</code></div></div>"
        )
        body.append(
            f"<div class='card'><div class='k'>{_('Quality Gate')}</div>"
            f"<div class='v'>{esc(meta.get('quality_gate') or _('nicht bewertet'))}</div></div></div>"
        )
        for profile in m.get("profiles", []):
            body.append(f"<h3>{_('Profil')}: {esc(profile.get('name'))}</h3>")
            s = profile.get("settings", {})
            body.append(
                f"<p class='muted'>GPU-Layer: <code>{esc(s.get('gpu_layers'))}</code> · "
                f"Threads: <code>{esc(s.get('threads', 'auto'))}</code></p>"
            )
            body.append(_bench_table(profile))
            body.append(f"<h3>{_('Hardware-Telemetrie')}</h3>")
            body.append(_telemetry_table(profile))
        if m.get("endpoint"):
            body.append(f"<h3>{_('Endpoint-/Multi-User-Test')}</h3>")
            body.append(_endpoint_table(m["endpoint"]))
        if m.get("soak"):
            body.append(f"<h3>{_('Dauerlast-Test (CPU + GPU gleichzeitig)')}</h3>")
            body.append(_soak_table(m["soak"]))

    body.append(f"<p class='muted small'>{_('Erzeugt mit llm-server-benchmark.')}</p></main></body></html>")
    Path(path).write_text("".join(body), encoding="utf-8")
