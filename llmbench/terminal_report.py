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
from .i18n import _
from .result_schema import scalar_summary

STATUS_STYLES = {
    "ok": "bold green",
    "timeout": "bold yellow",
    "partial": "bold yellow",
    "skipped_capacity": "bold yellow",
}


def status_label(status: str | None) -> str:
    # Literale _()-Aufrufe, damit die Uebersetzungspruefung sie findet.
    labels = {
        "ok": _("OK"),
        "timeout": _("Zeitueberschreitung"),
        "failed": _("Fehler"),
        "partial": _("Teilweise"),
        "skipped_capacity": _("Kapazitaetsgrenze"),
    }
    return labels.get(str(status), str(status))


def _status_text(status: str | None) -> Text:
    style = STATUS_STYLES.get(str(status), "bold red")
    return Text(status_label(status), style=style)


def _gpu_text(hw: dict[str, Any]) -> str:
    gpus = hw.get("gpus") or []
    if not gpus:
        return _("Keine GPU erkannt")
    parts = []
    for g in gpus:
        vram = g.get("memory.total")
        vram_text = f"{fnum(vram, 0)} MiB VRAM" if vram else _("VRAM unbekannt")
        note = "" if g.get("telemetry") == "nvml" else _(" · keine Telemetrie")
        parts.append(f"{g.get('vendor') or ''} {g.get('name')} ({vram_text}{note})")
    return "\n".join(parts)


def _header(summary: dict[str, Any]) -> Panel:
    hw = summary.get("hardware", {})
    subtitle = (
        f"{_('Projekt')}: {summary.get('project')} · {_('Start')}: {summary.get('started_at')} · "
        f"{_('Energieplan')}: {hw.get('power_scheme') or _('unbekannt')}"
    )
    return Panel(
        subtitle,
        title=f"{_('LLM Server Benchmark')} – {summary.get('server_name')}",
        border_style="cyan",
        title_align="left",
    )


def _hardware_cards(summary: dict[str, Any]) -> Table:
    hw = summary.get("hardware", {})
    cards = [
        (_("Server"), str(summary.get("server_name") or "?")),
        (_("CPU"), str(hw.get("cpu", {}).get("name") or "?")),
        (_("RAM"), human_bytes(hw.get("memory", {}).get("total_bytes"))),
        (_("GPU"), _gpu_text(hw)),
    ]
    grid = Table.grid(padding=(0, 1), expand=True)
    for _idx in cards:
        grid.add_column(ratio=1)
    grid.add_row(
        *[Panel(v, title=k, border_style="blue", title_align="left") for k, v in cards]
    )
    return grid


def _memory_bandwidth_panel(summary: dict[str, Any]) -> Panel | None:
    hardware = summary.get("hardware") or {}
    domains = hardware.get("memory_domains") or []
    rows = []
    for domain in domains:
        item = (domain.get("bandwidth") or {}).get("theoretical") or {}
        if isinstance(item, dict):
            value = item.get("value")
            text = f"{fnum(value)} GB/s" if value is not None else str(item.get("reason") or item.get("status") or "unavailable")
        else:
            text = f"{fnum(item)} GB/s" if item is not None else "unavailable"
        rows.append(f"{domain.get('id')}: theoretical/spec {text}")
    for row in (summary.get("telemetry") or {}).get("memory_bandwidth") or []:
        item = row.get("observed_during_benchmark") or {}
        if isinstance(item, dict):
            value = item.get("value")
            text = f"{fnum(value)} GB/s" if value is not None else str(item.get("reason") or "unavailable")
        else:
            text = f"{fnum(item)} GB/s" if item is not None else "unavailable"
        rows.append(f"{row.get('domain_id')}: observed runtime traffic (experimental) {text}")
    return Panel("\n".join(rows), title="Memory bandwidth", border_style="blue") if rows else None


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
        (_("Konfigurations-Fingerabdruck"), summary.get("config_fingerprint")),
        (_("llmbench-Version"), summary.get("llmbench_version")),
        (_("llama.cpp-Build"), ", ".join(build_ids) or _("unbekannt")),
        (_("llama-bench SHA256"), bench.get("sha256") or _("nicht berechnet")),
        (_("Wiederholungen"), cfg.get("repetitions")),
        (_("Batch / UBatch"), f"{cfg.get('batch_size')} / {cfg.get('ubatch_size')}"),
        (_("Flash Attention"), cfg.get("flash_attention")),
        (_("KV-Cache K/V"), f"{cfg.get('cache_type_k')} / {cfg.get('cache_type_v')}"),
    ]
    table = Table(
        title=_("Nachweis der Testbedingungen"), title_style="bold", title_justify="left",
        box=box.SIMPLE, show_header=False, pad_edge=False,
    )
    table.add_column(style="dim")
    table.add_column()
    for k, v in rows:
        table.add_row(str(k), str(v))
    return table


def _bench_table(profile: dict[str, Any]) -> Table:
    table = Table(box=box.SIMPLE_HEAVY, header_style="bold")
    table.add_column(_("Bereich"))
    table.add_column(_("Status"))
    table.add_column(_("Test"))
    table.add_column(_("Tokens/s"), justify="right")
    table.add_column(_("Stdabw."), justify="right")
    table.add_column(_("Prompt"), justify="right")
    table.add_column(_("Gen."), justify="right")
    table.add_column(_("Depth"), justify="right")
    for kind, result in profile.get("benchmarks", {}).items():
        bench_rows = flatten_bench_rows(result)
        if not bench_rows:
            table.add_row(
                kind, _status_text(result.get("status")), str(result.get("error") or ""),
                "", "", "", "", "",
            )
            continue
        row_status = "partial" if result.get("status") == "partial" else "ok"
        for row in bench_rows:
            table.add_row(
                kind,
                _status_text(row_status),
                str(row.get("test")),
                Text(fnum(row.get("avg_ts")), style="bold"),
                fnum(row.get("stddev_ts")),
                str(row.get("n_prompt") if row.get("n_prompt") is not None else "—"),
                str(row.get("n_gen") if row.get("n_gen") is not None else "—"),
                str(row.get("n_depth") if row.get("n_depth") is not None else "—"),
            )
        if result.get("status") == "partial" and result.get("error"):
            table.add_row(
                kind, _status_text("partial"), str(result["error"]),
                "", "", "", "", "",
            )
    return table


def _context_capability_group(capability: dict[str, Any] | None) -> RenderableType | None:
    if not capability:
        return None

    maximum = capability.get("maximum_verified_context")
    failed = capability.get("first_failed_context")
    head = (
        f"{_('Maximal verifizierter Kontext')}: "
        f"{maximum if maximum is not None else '—'} {_('Tokens')}"
    )
    if failed is not None:
        head += (
            f" · {_('Erste fehlgeschlagene Kontextstufe')}: "
            f"{failed} {_('Tokens')}"
        )

    table = Table(box=box.SIMPLE_HEAVY, header_style="bold")
    table.add_column(_("Kontexttiefe"), justify="right")
    table.add_column(_("Prefill Tokens/s"), justify="right")
    table.add_column(_("Decode Tokens/s"), justify="right")
    table.add_column(_("Kombiniert Tokens/s"), justify="right")
    table.add_column(_("Ergebnis"))

    labels = {
        "pass": _("OK"),
        "oom": _("Kapazitaetsgrenze"),
        "timeout": _("Zeitueberschreitung"),
        "failed": _("Fehler"),
        "partial": _("Teilweise"),
        "unknown": _("unbekannt"),
    }
    for row in capability.get("curve") or []:
        result = str(row.get("result") or "unknown")
        table.add_row(
            str(row.get("populated_context") if row.get("populated_context") is not None else "—"),
            fnum(row.get("prefill_tps")),
            fnum(row.get("decode_tps")),
            fnum(row.get("combined_tps")),
            labels.get(result, result),
        )

    return Group(
        Text(_("Kontext-Kapazitaet"), style="bold"),
        Text(head, style="dim"),
        table,
    )


def _kv_cache_table(kv_cache: dict[str, Any] | None) -> Table | None:
    if not kv_cache:
        return None
    labels = (
        ("effective_max_context", _("Effektiver maximaler Kontext"), "tokens"),
        ("kv_dtype", _("KV-Datentyp"), ""), ("k_dtype", _("K-Datentyp"), ""), ("v_dtype", _("V-Datentyp"), ""),
        ("memory_allocation", _("KV-Zuweisung"), "bytes"), ("token_capacity", _("KV-Token-Kapazitaet"), "tokens"),
        ("prefix_caching", _("Prefix-Caching"), ""), ("attention_backend", _("Attention-Backend"), ""),
        ("memory_budget_fraction", _("Speicherbudget"), "fraction"), ("runtime_version", _("Runtime-Version"), ""),
        ("residency", _("KV-Residenz"), ""),
    )
    table = Table(title=_("Effektive KV-Cache-Konfiguration"), box=box.SIMPLE, show_header=True)
    table.add_column(_("Feld"))
    table.add_column(_("Wert"))
    table.add_column(_("Quelle"))
    any_row = False
    for key, label, unit in labels:
        item = kv_cache.get(key)
        value = item.get("value") if isinstance(item, dict) else item
        has_value = value is not None
        if value is None:
            value = "—"
        if key == "memory_allocation" and isinstance(value, (int, float)):
            value = human_bytes(value)
        elif key == "memory_budget_fraction" and has_value:
            value = f"{float(value):.2%}"
        elif unit:
            value = f"{value} {unit}"
        source = (item.get("source") or item.get("status") or item.get("reason") or "unknown") if isinstance(item, dict) else ""
        table.add_row(label, str(value), str(source))
        any_row = True
    return table if any_row else None


def _telemetry_table(profile: dict[str, Any]) -> Table:
    table = Table(box=box.SIMPLE_HEAVY, header_style="bold")
    table.add_column(_("Bereich"))
    table.add_column(_("GPU"), justify="right")
    table.add_column(_("CPU Ø"), justify="right")
    table.add_column(_("CPU Max"), justify="right")
    table.add_column(_("RAM Max"), justify="right")
    table.add_column(_("GPU Ø"), justify="right")
    table.add_column(_("VRAM Max"), justify="right")
    table.add_column(_("GPU Power Ø"), justify="right")
    table.add_column(_("Temp Max"), justify="right")
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
        return Text(f"{_('Endpoint-Test fehlgeschlagen')}: {ep.get('error')}", style="bold red")
    settings = ep.get("settings") or {}
    head = (
        f"{_('Profil')}: {ep.get('profile')} · max_tokens {settings.get('max_tokens')} · "
        f"seed {settings.get('seed')} · ignore_eos {settings.get('ignore_eos')} · "
        f"Warmup {(ep.get('warmup') or {}).get('requests')} {_('Requests (verworfen)')}"
    )
    table = Table(box=box.SIMPLE_HEAVY, header_style="bold")
    table.add_column(_("Concurrency"), justify="right")
    table.add_column(_("Erfolgreich"), justify="right")
    table.add_column(_("System TPS"), justify="right")
    table.add_column(_("TPS/Request"), justify="right")
    table.add_column(_("TTFT P50 ms"), justify="right")
    table.add_column(_("TTFT P95 ms"), justify="right")
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
    table.add_column(_("Dauer"))
    table.add_column(_("Pfad"))
    table.add_column(_("Ø Tokens/s"), justify="right")
    table.add_column(_("Frueh"), justify="right")
    table.add_column(_("Spaet"), justify="right")
    table.add_column(_("Erfolgreich"), justify="right")
    table.add_column(_("Throttling"))
    temp_parts = []
    for run in soak_runs:
        if run.get("status") != "ok":
            table.add_row(str(run.get("label")), _status_text(run.get("status")), "", "", "", "", str(run.get("error") or ""))
            continue
        for path_label, path_data in (("CPU", run.get("cpu") or {}), ("GPU", run.get("gpu") or {})):
            throttle = Text(_("Ja"), style="bold yellow") if path_data.get("throttling_suspected") else Text(_("Nein"))
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
    temp_note = Text(_("Maximaltemperatur waehrend der Dauerlast: ") + ", ".join(temp_parts), style="dim")
    return Group(table, temp_note)


def build_run_report(summary: dict[str, Any]) -> list[RenderableType]:
    """Baut die renderbaren Abschnitte des Laufberichts fuer das Terminal."""
    persisted_summary = summary
    summary = scalar_summary(summary)
    renderables: list[RenderableType] = [_header(summary), _hardware_cards(summary)]
    bandwidth = _memory_bandwidth_panel(persisted_summary)
    if bandwidth is not None:
        renderables.append(bandwidth)
    warnings_panel = _warnings_panel(summary)
    if warnings_panel is not None:
        renderables.append(warnings_panel)
    renderables.append(_provenance_table(summary))

    for model_index, m in enumerate(summary.get("models", [])):
        meta = m.get("model", {})
        renderables.append(Text(f"\n{meta.get('name')}", style="bold underline"))
        if m.get("status") == "failed":
            renderables.append(Text(str(m.get("error") or ""), style="bold red"))
            continue

        sha = meta.get("sha256") or _("nicht berechnet")
        sha_short = sha if sha == _("nicht berechnet") else f"{sha[:16]}…"
        renderables.append(Text(
            f"{_('GGUF-Groesse')}: {human_bytes(meta.get('size_bytes'))} · SHA256: {sha_short} · "
            f"{_('Quality Gate')}: {meta.get('quality_gate') or _('nicht bewertet')}",
            style="dim",
        ))

        for profile_index, profile in enumerate(m.get("profiles", [])):
            s = profile.get("settings", {})
            renderables.append(Text(
                f"\n{_('Profil')}: {profile.get('name')}  (GPU-Layer: {s.get('gpu_layers')} · "
                f"Threads: {s.get('threads', 'auto')})",
                style="bold",
            ))
            renderables.append(_bench_table(profile))
            context_group = _context_capability_group(profile.get("context_capability"))
            if context_group is not None:
                renderables.append(context_group)
            raw_profiles = ((persisted_summary.get("models") or [])[model_index].get("profiles") or [])
            raw_profile = raw_profiles[profile_index] if profile_index < len(raw_profiles) else profile
            kv_table = _kv_cache_table(raw_profile.get("kv_cache"))
            if kv_table is not None:
                renderables.append(kv_table)
            renderables.append(Text(_("Hardware-Telemetrie"), style="bold"))
            renderables.append(_telemetry_table(profile))

        if m.get("endpoint"):
            renderables.append(Text(f"\n{_('Endpoint-/Multi-User-Test')}", style="bold"))
            endpoint_group = _endpoint_group(m["endpoint"])
            if endpoint_group is not None:
                renderables.append(endpoint_group)

        if m.get("soak"):
            renderables.append(Text(f"\n{_('Dauerlast-Test (CPU + GPU gleichzeitig)')}", style="bold"))
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
