"""Farbige Ergebnisuebersicht im Terminal.

Auf Linux-Servern oeffnet man den PDF- oder HTML-Bericht oft nicht direkt
(kein Desktop, nur SSH). Diese Ansicht bildet dieselben Abschnitte wie
`report.py`/`pdf_report.py` mit `rich` im Terminal nach, damit ein Lauf auch
ohne geoeffneten Bericht sofort lesbar ist.
"""

from __future__ import annotations

from typing import Any

from rich import box
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .llama_bench import flatten_bench_rows
from .report import fms, fnum
from .utils import human_bytes

STATUS_STYLES = {"ok": "bold green", "timeout": "bold yellow"}
STATUS_LABELS = {"ok": "OK", "timeout": "Zeitueberschreitung", "failed": "Fehler"}


def _status_text(status: str | None) -> Text:
    style = STATUS_STYLES.get(str(status), "bold red")
    label = STATUS_LABELS.get(str(status), str(status))
    return Text(label, style=style)


def _gpu_text(hw: dict[str, Any]) -> str:
    gpus = hw.get("gpus") or []
    if not gpus:
        return "Keine GPU erkannt"
    parts = []
    for g in gpus:
        vram = g.get("memory.total")
        vram_text = f"{fnum(vram, 0)} MiB VRAM" if vram else "VRAM unbekannt"
        note = "" if g.get("telemetry") == "nvml" else " · keine Telemetrie"
        parts.append(f"{g.get('vendor') or ''} {g.get('name')} ({vram_text}{note})")
    return "\n".join(parts)


def _header(summary: dict[str, Any]) -> Panel:
    hw = summary.get("hardware", {})
    subtitle = (
        f"Projekt: {summary.get('project')} · Start: {summary.get('started_at')} · "
        f"Energieplan: {hw.get('power_scheme') or 'unbekannt'}"
    )
    return Panel(
        subtitle,
        title=f"LLM Server Benchmark – {summary.get('server_name')}",
        border_style="cyan",
        title_align="left",
    )


def _hardware_cards(summary: dict[str, Any]) -> Table:
    hw = summary.get("hardware", {})
    cards = [
        ("Server", str(summary.get("server_name") or "?")),
        ("CPU", str(hw.get("cpu", {}).get("name") or "?")),
        ("RAM", human_bytes(hw.get("memory", {}).get("total_bytes"))),
        ("GPU", _gpu_text(hw)),
    ]
    grid = Table.grid(padding=(0, 1), expand=True)
    for _ in cards:
        grid.add_column(ratio=1)
    grid.add_row(
        *[Panel(v, title=k, border_style="blue", title_align="left") for k, v in cards]
    )
    return grid


def _warnings_panel(summary: dict[str, Any]) -> Panel | None:
    warnings = summary.get("warnings") or []
    if not warnings:
        return None
    body = "\n".join(f"• {w}" for w in warnings)
    return Panel(body, title="Hinweise zu diesem Lauf", border_style="yellow", title_align="left")


def _provenance_table(summary: dict[str, Any]) -> Table:
    tools = summary.get("tools") or {}
    bench = (tools.get("llama_bench") or {}).get("binary") or {}
    build_ids = tools.get("llama_cpp_build_ids") or []
    cfg = (summary.get("config") or {}).get("benchmark") or {}
    rows = [
        ("Konfigurations-Fingerabdruck", summary.get("config_fingerprint")),
        ("llmbench-Version", summary.get("llmbench_version")),
        ("llama.cpp-Build", ", ".join(build_ids) or "unbekannt"),
        ("llama-bench SHA256", bench.get("sha256") or "nicht berechnet"),
        ("Wiederholungen", cfg.get("repetitions")),
        ("Batch / UBatch", f"{cfg.get('batch_size')} / {cfg.get('ubatch_size')}"),
        ("Flash Attention", cfg.get("flash_attention")),
        ("KV-Cache K/V", f"{cfg.get('cache_type_k')} / {cfg.get('cache_type_v')}"),
    ]
    table = Table(
        title="Nachweis der Testbedingungen", title_style="bold", title_justify="left",
        box=box.SIMPLE, show_header=False, pad_edge=False,
    )
    table.add_column(style="dim")
    table.add_column()
    for k, v in rows:
        table.add_row(str(k), str(v))
    return table


def _bench_table(profile: dict[str, Any]) -> Table:
    table = Table(box=box.SIMPLE_HEAVY, header_style="bold")
    table.add_column("Bereich")
    table.add_column("Status")
    table.add_column("Test")
    table.add_column("Tokens/s", justify="right")
    table.add_column("Stdabw.", justify="right")
    table.add_column("Prompt", justify="right")
    table.add_column("Gen.", justify="right")
    table.add_column("Depth", justify="right")
    for kind, result in profile.get("benchmarks", {}).items():
        if result.get("status") != "ok":
            table.add_row(
                kind, _status_text(result.get("status")), str(result.get("error") or ""),
                "", "", "", "", "",
            )
            continue
        for row in flatten_bench_rows(result):
            table.add_row(
                kind,
                _status_text("ok"),
                str(row.get("test")),
                Text(fnum(row.get("avg_ts")), style="bold"),
                fnum(row.get("stddev_ts")),
                str(row.get("n_prompt") if row.get("n_prompt") is not None else "—"),
                str(row.get("n_gen") if row.get("n_gen") is not None else "—"),
                str(row.get("n_depth") if row.get("n_depth") is not None else "—"),
            )
    return table


def _telemetry_table(profile: dict[str, Any]) -> Table:
    table = Table(box=box.SIMPLE_HEAVY, header_style="bold")
    table.add_column("Bereich")
    table.add_column("GPU", justify="right")
    table.add_column("CPU Ø", justify="right")
    table.add_column("CPU Max", justify="right")
    table.add_column("RAM Max", justify="right")
    table.add_column("GPU Ø", justify="right")
    table.add_column("VRAM Max", justify="right")
    table.add_column("GPU Power Ø", justify="right")
    table.add_column("Temp Max", justify="right")
    for kind, result in profile.get("benchmarks", {}).items():
        t = result.get("telemetry") or {}
        gpus = t.get("gpus") or [{}]
        for gpu in gpus:
            table.add_row(
                kind,
                str(gpu.get("index", 0)),
                f"{fnum(t.get('avg_cpu_percent'))}%",
                f"{fnum(t.get('max_cpu_percent'))}%",
                human_bytes(t.get("max_ram_used_bytes")),
                f"{fnum(gpu.get('avg_util_gpu_percent'))}%",
                human_bytes(gpu.get("max_memory_used_bytes")),
                f"{fnum(gpu.get('avg_power_w'))} W",
                f"{fnum(gpu.get('max_temperature_c'), 0)} °C",
            )
    return table


def _endpoint_group(ep: dict[str, Any]) -> RenderableType | None:
    if not ep:
        return None
    if ep.get("status") != "ok":
        return Text(f"Endpoint-Test fehlgeschlagen: {ep.get('error')}", style="bold red")
    settings = ep.get("settings") or {}
    head = (
        f"Profil: {ep.get('profile')} · max_tokens {settings.get('max_tokens')} · "
        f"seed {settings.get('seed')} · ignore_eos {settings.get('ignore_eos')} · "
        f"Warmup {(ep.get('warmup') or {}).get('requests')} Requests (verworfen)"
    )
    table = Table(box=box.SIMPLE_HEAVY, header_style="bold")
    table.add_column("Concurrency", justify="right")
    table.add_column("Erfolgreich", justify="right")
    table.add_column("System TPS", justify="right")
    table.add_column("TPS/Request", justify="right")
    table.add_column("TTFT P50 ms", justify="right")
    table.add_column("TTFT P95 ms", justify="right")
    for x in ep.get("levels", []):
        successful = f"{x.get('successful')}/{x.get('requests')}"
        if x.get("note"):
            successful += f"\n{x.get('note')}"
        table.add_row(
            str(x.get("concurrency")),
            successful,
            Text(fnum(x.get("system_tps")), style="bold"),
            fnum(x.get("avg_interactivity_tps")),
            fms(x.get("ttft_p50_seconds")),
            fms(x.get("ttft_p95_seconds")),
        )
    return Group(Text(head, style="dim"), table)


def _soak_table(soak_runs: list[dict[str, Any]]) -> RenderableType | None:
    if not soak_runs:
        return None
    table = Table(box=box.SIMPLE_HEAVY, header_style="bold")
    table.add_column("Dauer")
    table.add_column("Pfad")
    table.add_column("Ø Tokens/s", justify="right")
    table.add_column("Frueh", justify="right")
    table.add_column("Spaet", justify="right")
    table.add_column("Erfolgreich", justify="right")
    table.add_column("Throttling")
    temp_parts = []
    for run in soak_runs:
        if run.get("status") != "ok":
            table.add_row(str(run.get("label")), _status_text(run.get("status")), "", "", "", "", str(run.get("error") or ""))
            continue
        for path_label, path_data in (("CPU", run.get("cpu") or {}), ("GPU", run.get("gpu") or {})):
            throttle = Text("Ja", style="bold yellow") if path_data.get("throttling_suspected") else Text("Nein")
            table.add_row(
                str(run.get("label")),
                path_label,
                fnum(path_data.get("avg_tps")),
                fnum(path_data.get("early_window_avg_tps")),
                fnum(path_data.get("late_window_avg_tps")),
                f"{path_data.get('successful', 0)}/{path_data.get('requests', 0)}",
                throttle,
            )
        for gpu in (run.get("telemetry") or {}).get("gpus") or []:
            if gpu.get("max_temperature_c"):
                temp_parts.append(f"{run.get('label')}: GPU {gpu.get('index', 0)} {fnum(gpu.get('max_temperature_c'), 0)} °C")
    if not temp_parts:
        return table
    temp_note = Text("Maximaltemperatur waehrend der Dauerlast: " + ", ".join(temp_parts), style="dim")
    return Group(table, temp_note)


def build_run_report(summary: dict[str, Any]) -> list[RenderableType]:
    """Baut die renderbaren Abschnitte des Laufberichts fuer das Terminal."""
    renderables: list[RenderableType] = [_header(summary), _hardware_cards(summary)]
    warnings_panel = _warnings_panel(summary)
    if warnings_panel is not None:
        renderables.append(warnings_panel)
    renderables.append(_provenance_table(summary))

    for m in summary.get("models", []):
        meta = m.get("model", {})
        renderables.append(Text(f"\n{meta.get('name')}", style="bold underline"))
        if m.get("status") == "failed":
            renderables.append(Text(str(m.get("error") or ""), style="bold red"))
            continue

        sha = meta.get("sha256") or "nicht berechnet"
        sha_short = sha if sha == "nicht berechnet" else f"{sha[:16]}…"
        renderables.append(Text(
            f"GGUF-Groesse: {human_bytes(meta.get('size_bytes'))} · SHA256: {sha_short} · "
            f"Quality Gate: {meta.get('quality_gate') or 'nicht bewertet'}",
            style="dim",
        ))

        for profile in m.get("profiles", []):
            s = profile.get("settings", {})
            renderables.append(Text(
                f"\nProfil: {profile.get('name')}  (GPU-Layer: {s.get('gpu_layers')} · "
                f"Threads: {s.get('threads', 'auto')})",
                style="bold",
            ))
            renderables.append(_bench_table(profile))
            renderables.append(Text("Hardware-Telemetrie", style="bold"))
            renderables.append(_telemetry_table(profile))

        if m.get("endpoint"):
            renderables.append(Text("\nEndpoint-/Multi-User-Test", style="bold"))
            endpoint_group = _endpoint_group(m["endpoint"])
            if endpoint_group is not None:
                renderables.append(endpoint_group)

        if m.get("soak"):
            renderables.append(Text("\nDauerlast-Test (CPU + GPU gleichzeitig)", style="bold"))
            soak_table = _soak_table(m["soak"])
            if soak_table is not None:
                renderables.append(soak_table)

    return renderables


def print_run_report(summary: dict[str, Any], console: Console | None = None) -> None:
    """Zeigt den vollstaendigen Laufbericht farbig im Terminal an."""
    console = console or Console()
    console.print()
    for renderable in build_run_report(summary):
        console.print(renderable)
