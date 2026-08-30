"""PDF-Bericht eines Benchmarklaufs.

Erzeugt aus summary.json ein druckbares Dokument: Serverdaten, Nachweis der
Testbedingungen, Ergebnistabellen und Telemetrie je Modell und Profil.

reportlab wird bewusst erst beim Aufruf importiert. Fehlt das Paket, bleibt
der Lauf gueltig - es entfaellt nur der PDF-Bericht.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .llama_bench import flatten_bench_rows
from .utils import human_bytes

INK = "#16212b"
MUTED = "#5d6b78"
LINE = "#d3dde2"
SOFT = "#f2f5f7"
ACCENT = "#1769aa"
GOOD = "#177245"
BAD = "#a12622"
WARN = "#8a5a11"

MAX_BARS = 14

# Prompt Processing misst Input-Tokens/s, Text Generation Output-Tokens/s.
# Beide liegen um eine Groessenordnung auseinander und bekommen deshalb je
# ein eigenes Diagramm - auf einer gemeinsamen Skala waeren die
# Generierungsbalken nicht mehr ablesbar.
KIND_TITLES = {
    "prompt": "Prompt Processing – Input-Tokens/s",
    "generation": "Text Generation – Output-Tokens/s",
    "long_context": "Long Context – Output-Tokens/s bei belegtem Kontext",
}


def _require_reportlab():
    try:
        import reportlab  # noqa: F401
    except ImportError as exc:  # pragma: no cover - haengt von der Umgebung ab
        raise RuntimeError(
            "Fuer den PDF-Bericht wird reportlab benoetigt: pip install reportlab"
        ) from exc


def _fmt(value: Any, digits: int = 2) -> str:
    try:
        if value is None:
            return "—"
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _unit(value: Any, unit: str, digits: int = 0) -> str:
    """Zahl mit Einheit. Fehlt der Wert, entfaellt auch die Einheit -
    "— %" liest sich sonst wie eine gemessene Null."""
    text = _fmt(value, digits)
    return text if text == "—" else f"{text} {unit}"


def _bar_chart(entries: list[tuple[str, float]], width: float):
    """Horizontales Balkendiagramm mit einer Reihe.

    Eine Groesse, eine Farbe, Werte direkt am Balken - damit braucht das
    Diagramm keine Legende und bleibt auch im Schwarzweissdruck lesbar.
    """
    from reportlab.graphics.shapes import Drawing, Line, Rect, String
    from reportlab.lib.colors import HexColor

    entries = entries[:MAX_BARS]
    row_height = 15.0
    label_width = min(150.0, width * 0.34)
    value_width = 62.0
    plot_width = max(60.0, width - label_width - value_width)
    height = row_height * len(entries) + 14

    drawing = Drawing(width, height)
    largest = max((v for _, v in entries), default=0.0) or 1.0

    # Grundlinie und zwei dezente Hilfslinien als Groessenanker
    for fraction in (0.5, 1.0):
        x = label_width + plot_width * fraction
        drawing.add(Line(x, 6, x, height - 8, strokeColor=HexColor(LINE), strokeWidth=0.5))
    drawing.add(Line(label_width, 6, label_width, height - 8,
                     strokeColor=HexColor(LINE), strokeWidth=0.8))

    for index, (label, value) in enumerate(entries):
        y = height - 12 - (index + 1) * row_height + 4
        bar_width = max(1.0, plot_width * (float(value) / largest))
        drawing.add(String(label_width - 6, y + 2, label[:32], fontName="Helvetica",
                           fontSize=7.5, fillColor=HexColor(MUTED), textAnchor="end"))
        drawing.add(Rect(label_width, y, bar_width, 8.5, fillColor=HexColor(ACCENT),
                         strokeColor=None))
        drawing.add(String(label_width + bar_width + 5, y + 2, _fmt(value),
                           fontName="Helvetica-Bold", fontSize=7.5, fillColor=HexColor(INK)))
    return drawing


def _table(data: list[list[str]], col_widths: list[float], numeric_from: int = 2):
    from reportlab.lib import colors
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import Table, TableStyle

    table = Table(data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor(INK)),
        ("TEXTCOLOR", (0, 1), (-1, -1), HexColor(INK)),
        ("BACKGROUND", (0, 0), (-1, 0), HexColor(SOFT)),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, HexColor(LINE)),
        ("GRID", (0, 0), (-1, -1), 0.25, HexColor(LINE)),
        ("ALIGN", (numeric_from, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, HexColor("#fafbfc")]),
    ]))
    return table


def _styles():
    from reportlab.lib.colors import HexColor
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=19, leading=23,
                                textColor=HexColor(INK), alignment=0, spaceAfter=2),
        "sub": ParagraphStyle("s", parent=base["Normal"], fontSize=9, leading=12,
                              textColor=HexColor(MUTED), spaceAfter=12),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=12, leading=15,
                             textColor=HexColor(INK), spaceBefore=14, spaceAfter=5,
                             keepWithNext=True),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], fontSize=9.5, leading=12,
                             textColor=HexColor(ACCENT), spaceBefore=9, spaceAfter=3,
                             keepWithNext=True),
        "body": ParagraphStyle("b", parent=base["Normal"], fontSize=8.5, leading=11.5,
                               textColor=HexColor(INK)),
        "muted": ParagraphStyle("m", parent=base["Normal"], fontSize=8, leading=11,
                                textColor=HexColor(MUTED)),
        "mutedKeep": ParagraphStyle("mk", parent=base["Normal"], fontSize=8, leading=11,
                                    textColor=HexColor(MUTED), keepWithNext=True),
        "warn": ParagraphStyle("w", parent=base["Normal"], fontSize=8, leading=11,
                               textColor=HexColor(WARN)),
    }


def _page_furniture(canvas, doc, server_name: str) -> None:
    from reportlab.lib.colors import HexColor

    canvas.saveState()
    canvas.setStrokeColor(HexColor(LINE))
    canvas.setLineWidth(0.5)
    canvas.line(doc.leftMargin, doc.pagesize[1] - doc.topMargin + 12,
                doc.pagesize[0] - doc.rightMargin, doc.pagesize[1] - doc.topMargin + 12)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(HexColor(MUTED))
    canvas.drawString(doc.leftMargin, doc.pagesize[1] - doc.topMargin + 17,
                      f"LLM Server Benchmark – {server_name}")
    canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, doc.bottomMargin - 14,
                           f"Seite {doc.page}")
    canvas.restoreState()


def _hardware_rows(hardware: dict[str, Any]) -> list[list[str]]:
    cpu = hardware.get("cpu") or {}
    memory = hardware.get("memory") or {}
    rows = [
        ["Betriebssystem", str(hardware.get("os") or "—")],
        ["CPU", f"{cpu.get('name') or '—'} ({cpu.get('physical_cores') or '?'} Kerne / "
                f"{cpu.get('logical_cores') or '?'} Threads)"],
        ["Arbeitsspeicher", human_bytes(memory.get("total_bytes"))],
        ["Energieplan", str(hardware.get("power_scheme") or "unbekannt")],
    ]
    for gpu in hardware.get("gpus") or []:
        vram = gpu.get("memory.total")
        detail = f"{gpu.get('vendor') or ''} {gpu.get('name') or '—'}".strip()
        if vram:
            detail += f", {vram} MiB VRAM"
        if gpu.get("driver_version"):
            detail += f", Treiber {gpu['driver_version']}"
        if gpu.get("telemetry") == "none":
            detail += " (keine Telemetrie)"
        rows.append([f"GPU {gpu.get('index', 0)}", detail])
    if not (hardware.get("gpus") or []):
        rows.append(["GPU", "keine erkannt"])
    return rows


def _provenance_rows(summary: dict[str, Any]) -> list[list[str]]:
    tools = summary.get("tools") or {}
    binary = (tools.get("llama_bench") or {}).get("binary") or {}
    bench_cfg = (summary.get("config") or {}).get("benchmark") or {}
    sha = binary.get("sha256") or "nicht berechnet"
    return [
        ["Konfigurations-Fingerabdruck", str(summary.get("config_fingerprint") or "—")],
        ["llmbench-Version", str(summary.get("llmbench_version") or "—")],
        ["llama.cpp-Build", ", ".join(tools.get("llama_cpp_build_ids") or []) or "unbekannt"],
        ["llama-bench SHA256", sha[:48]],
        ["Wiederholungen", str(bench_cfg.get("repetitions") or "—")],
        ["Batch / UBatch", f"{bench_cfg.get('batch_size')} / {bench_cfg.get('ubatch_size')}"],
        ["Flash Attention", str(bench_cfg.get("flash_attention") or "—")],
        ["KV-Cache K / V", f"{bench_cfg.get('cache_type_k')} / {bench_cfg.get('cache_type_v')}"],
    ]


def generate_run_pdf(summary: dict[str, Any], path: str | Path) -> Path:
    _require_reportlab()

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        BaseDocTemplate, Frame, KeepTogether, PageTemplate, Paragraph, Spacer,
    )

    path = Path(path)
    styles = _styles()
    server_name = str(summary.get("server_name") or "unbekannt")

    doc = BaseDocTemplate(
        str(path), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=20 * mm, bottomMargin=18 * mm,
        title=f"LLM Server Benchmark - {server_name}",
        author="llm-server-benchmark",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    doc.addPageTemplates([PageTemplate(
        id="main", frames=[frame],
        onPage=lambda canvas, d: _page_furniture(canvas, d, server_name),
    )])

    width = doc.width
    story: list[Any] = []

    story.append(Paragraph(f"Benchmark-Bericht {server_name}", styles["title"]))
    story.append(Paragraph(
        f"{summary.get('project') or 'LLM Server Benchmark'} &middot; Start "
        f"{summary.get('started_at') or '—'} &middot; Ende {summary.get('finished_at') or '—'}",
        styles["sub"]))

    story.append(Paragraph("Server und Hardware", styles["h2"]))
    story.append(_table([["Merkmal", "Wert"]] + _hardware_rows(summary.get("hardware") or {}),
                        [width * 0.28, width * 0.72], numeric_from=99))

    story.append(Paragraph("Nachweis der Testbedingungen", styles["h2"]))
    story.append(Paragraph(
        "Diese Angaben müssen auf allen verglichenen Servern übereinstimmen. "
        "<font face='Helvetica-Bold'>llmbench compare</font> prüft das und meldet Abweichungen.",
        styles["muted"]))
    story.append(Spacer(1, 4))
    story.append(_table([["Merkmal", "Wert"]] + _provenance_rows(summary),
                        [width * 0.28, width * 0.72], numeric_from=99))

    warnings = summary.get("warnings") or []
    if warnings:
        story.append(Paragraph(f"Hinweise zu diesem Lauf ({len(warnings)})", styles["h2"]))
        for warning in warnings[:20]:
            story.append(Paragraph(f"&bull; {warning}", styles["warn"]))
        if len(warnings) > 20:
            story.append(Paragraph(f"… und {len(warnings) - 20} weitere in summary.json",
                                   styles["muted"]))

    for model in summary.get("models", []):
        meta = model.get("model") or {}
        story.append(Paragraph(str(meta.get("name") or "Modell"), styles["h2"]))

        if model.get("status") == "failed":
            story.append(Paragraph(str(model.get("error") or "Fehlgeschlagen"), styles["warn"]))
            continue

        sha = meta.get("sha256") or "nicht berechnet"
        story.append(Paragraph(
            f"Datei: {meta.get('path') or '—'}<br/>Größe: {human_bytes(meta.get('size_bytes'))}"
            f" &middot; SHA256: {sha[:40]}{'...' if len(sha) > 40 else ''}"
            f" &middot; Quality Gate: {meta.get('quality_gate') or 'nicht bewertet'}",
            styles["muted"]))

        for profile in model.get("profiles", []):
            settings = profile.get("settings") or {}
            block: list[Any] = [Paragraph(
                f"Profil {profile.get('name')} &middot; GPU-Layer {settings.get('gpu_layers')} "
                f"&middot; Threads {settings.get('threads', 'auto')}", styles["h3"])]

            rows = [["Bereich", "Test", "Tokens/s", "Stdabw.", "Prompt", "Gen.", "Tiefe"]]
            charts: dict[str, list[tuple[str, float]]] = {}
            for kind, result in (profile.get("benchmarks") or {}).items():
                bench_rows = flatten_bench_rows(result)
                if not bench_rows:
                    label = ("Zeitüberschreitung" if result.get("status") == "timeout"
                             else "Fehler")
                    rows.append([kind, label, "—", "—", "—", "—", "—"])
                    continue
                for row in bench_rows:
                    rows.append([
                        kind, str(row.get("test")), _fmt(row.get("avg_ts")),
                        _fmt(row.get("stddev_ts")), str(row.get("n_prompt") or 0),
                        str(row.get("n_gen") or 0), str(row.get("n_depth") or 0),
                    ])
                    if row.get("avg_ts"):
                        charts.setdefault(kind, []).append(
                            (str(row.get("test")), float(row["avg_ts"]))
                        )

            block.append(_table(rows, [
                width * 0.14, width * 0.22, width * 0.14, width * 0.12,
                width * 0.12, width * 0.11, width * 0.13,
            ]))

            for kind, entries in charts.items():
                block.append(KeepTogether([
                    Spacer(1, 5),
                    Paragraph(KIND_TITLES.get(kind, kind), styles["muted"]),
                    _bar_chart(entries, width),
                ]))

            telemetry_rows = [["Bereich", "GPU", "CPU Ø", "RAM max.",
                               "GPU Ø", "VRAM max.", "Leistung Ø", "Temp. max."]]
            for kind, result in (profile.get("benchmarks") or {}).items():
                telemetry = result.get("telemetry") or {}
                for gpu in telemetry.get("gpus") or [{}]:
                    telemetry_rows.append([
                        kind, str(gpu.get("index", 0)),
                        _unit(telemetry.get("avg_cpu_percent"), "%"),
                        human_bytes(telemetry.get("max_ram_used_bytes")),
                        _unit(gpu.get("avg_util_gpu_percent"), "%"),
                        human_bytes(gpu.get("max_memory_used_bytes")),
                        _unit(gpu.get("avg_power_w"), "W"),
                        _unit(gpu.get("max_temperature_c"), "°C"),
                    ])
            if len(telemetry_rows) > 1:
                block.append(Spacer(1, 6))
                block.append(Paragraph("Hardware-Telemetrie", styles["mutedKeep"]))
                block.append(_table(telemetry_rows, [
                    width * 0.13, width * 0.07, width * 0.14, width * 0.13,
                    width * 0.14, width * 0.13, width * 0.13, width * 0.13,
                ]))
            story.extend(block)

        endpoint = model.get("endpoint")
        if endpoint and endpoint.get("status") == "ok":
            story.append(Paragraph("Endpoint- und Mehrbenutzer-Test", styles["h3"]))
            ep_rows = [["Parallel", "Erfolgreich", "System-TPS", "TPS/Request",
                        "TTFT P50 ms", "TTFT P95 ms"]]
            for level in endpoint.get("levels", []):
                p50 = level.get("ttft_p50_seconds")
                p95 = level.get("ttft_p95_seconds")
                ep_rows.append([
                    str(level.get("concurrency")),
                    f"{level.get('successful')}/{level.get('requests')}",
                    _fmt(level.get("system_tps")), _fmt(level.get("avg_interactivity_tps")),
                    _fmt(p50 * 1000) if p50 is not None else "—",
                    _fmt(p95 * 1000) if p95 is not None else "—",
                ])
            story.append(_table(ep_rows, [
                width * 0.13, width * 0.17, width * 0.18, width * 0.18,
                width * 0.17, width * 0.17,
            ], numeric_from=1))
        elif endpoint:
            story.append(Paragraph(
                f"Endpoint-Test fehlgeschlagen: {endpoint.get('error')}", styles["warn"]))

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "Erzeugt mit llm-server-benchmark. Rohdaten und Telemetrie je Einzeltest "
        "liegen im selben Ordner unter raw_*.json.", styles["muted"]))

    doc.build(story)
    return path


def generate_compare_pdf(
    summaries: list[dict[str, Any]],
    scores: dict[str, dict[str, Any]],
    issues: list[dict[str, str]],
    path: str | Path,
) -> Path:
    """Erzeugt einen PDF-Vergleichsbericht aus mehreren Server-Laeufen."""
    _require_reportlab()
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    path = Path(path)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("heading", parent=styles["Heading1"], fontSize=18, textColor=colors.HexColor(INK)))
    styles.add(ParagraphStyle("sub", parent=styles["Heading2"], fontSize=13, textColor=colors.HexColor(INK)))
    styles.add(ParagraphStyle("muted_p", parent=styles["Normal"], textColor=colors.HexColor(MUTED), fontSize=8))

    story = []
    story.append(Paragraph("LLM Server Vergleich", styles["heading"]))
    story.append(Spacer(1, 6))

    servers = [str(s.get("server_name") or "unbekannt") for s in summaries]
    story.append(Paragraph(f"Server: {', '.join(servers)}", styles["Normal"]))
    story.append(Spacer(1, 8))

    # Konsistenzprüfung
    if issues:
        errors = [i for i in issues if i["level"] == "error"]
        if errors:
            story.append(Paragraph(f"{len(errors)} Abweichung(en), die den Vergleich ungueltig machen:", styles["sub"]))
        else:
            story.append(Paragraph("Hinweise zur Vergleichbarkeit:", styles["sub"]))
        for issue in issues:
            marker = "FEHLER" if issue["level"] == "error" else "Hinweis"
            story.append(Paragraph(f"[{marker}] {issue['topic']}: {issue['message']}", styles["Normal"]))
        story.append(Spacer(1, 8))
    else:
        story.append(Paragraph(
            "Vergleichbarkeit geprueft: Konfiguration, Build, Modelle und Profile stimmen ueberein.",
            styles["Normal"],
        ))
        story.append(Spacer(1, 8))

    # Gesamtscore-Tabelle
    if scores and any(s.get("total") is not None for s in scores.values()):
        story.append(Paragraph("Gesamtscore", styles["sub"]))
        metric_labels = {"tg": "Text Generation", "pp": "Prompt Processing",
                         "ep_tps": "Endpoint TPS", "eff": "Effizienz"}
        score_header = ["Metrik"] + servers
        score_data = [score_header]
        for metric, label in metric_labels.items():
            row = [label]
            for srv in servers:
                val = scores.get(srv, {}).get("normalized", {}).get(metric)
                row.append(_fmt(val, 1) if val is not None else "—")
            score_data.append(row)
        total_row = ["Gesamtscore"]
        for srv in servers:
            val = scores.get(srv, {}).get("total")
            total_row.append(_fmt(val, 1) if val is not None else "—")
        score_data.append(total_row)

        tbl = Table(score_data, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(SOFT)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(INK)),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(LINE)),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("LINEABOVE", (0, -1), (-1, -1), 1.5, colors.HexColor(INK)),
        ]))
        story.append(tbl)
        story.append(Paragraph(
            "Score: bester Server je Metrik = 100. "
            "Gewichte: TG 35%, PP 25%, Endpoint 25%, Effizienz 15%.",
            styles["muted_p"],
        ))
        story.append(Spacer(1, 12))

    # Hardware-Tabelle
    story.append(Paragraph("Hardware", styles["sub"]))
    hw_header = ["Server", "CPU", "GPU", "RAM"]
    hw_data = [hw_header]
    for s in summaries:
        hw = s.get("hardware", {})
        gpus = hw.get("gpus") or []
        gpu_text = ", ".join(g.get("name", "?") for g in gpus) or "keine"
        ram = f"{(hw.get('memory', {}).get('total_bytes') or 0) / (1024 ** 3):.1f} GiB"
        hw_data.append([str(s.get("server_name") or "?"), hw.get("cpu", {}).get("name", "?"), gpu_text, ram])
    tbl = Table(hw_data, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(SOFT)),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(LINE)),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 12))

    story.append(Paragraph(
        "Details, Diagramme und Einzelwerte stehen im HTML-Bericht (comparison.html).",
        styles["muted_p"],
    ))

    doc.build(story)
    return path
