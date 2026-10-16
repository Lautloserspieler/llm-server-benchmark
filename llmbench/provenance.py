"""Zeilen des Abschnitts "Nachweis der Testbedingungen", gemeinsam fuer alle Berichte."""

from __future__ import annotations

from typing import Any

from .i18n import _

CONTAINER_BACKENDS = ("ollama", "vllm", "tgi")


def condition_rows(summary: dict[str, Any]) -> list[tuple[str, str]]:
    """Backend-passende Testbedingungen.

    Batch/UBatch, Flash Attention, KV-Cache-Typ und der llama.cpp-Build sind nur
    bei llama.cpp Einstellungen, die llmbench selbst setzt. Bei Ollama, vLLM und
    TGI wuerden sie falsche Bedingungen nahelegen und werden daher ersetzt.
    """
    tools = summary.get("tools") or {}
    cfg = (summary.get("config") or {}).get("benchmark") or {}
    backend = str(summary.get("backend") or "llama_cpp")

    rows: list[tuple[str, Any]] = [
        (_("Konfigurations-Fingerabdruck"), summary.get("config_fingerprint")),
        (_("llmbench-Version"), summary.get("llmbench_version")),
    ]

    if backend in CONTAINER_BACKENDS:
        info = tools.get(backend) or {}
        digest = str(info.get("digest") or "")
        rows += [
            (_("Backend"), backend),
            (_("Container-Image"), info.get("image") or _("unbekannt")),
            (_("Image-Digest"), digest[:19] if digest else _("unbekannt")),
            (_("Wiederholungen"), cfg.get("repetitions")),
            (
                _("Backend-Einstellungen"),
                _("Standardwerte des Backends (Batch, Flash Attention und KV-Cache setzt llmbench hier nicht)"),
            ),
        ]
    else:
        binary = (tools.get("llama_bench") or {}).get("binary") or {}
        rows += [
            (_("llama.cpp-Build"), ", ".join(tools.get("llama_cpp_build_ids") or []) or _("unbekannt")),
            (_("llama-bench SHA256"), (binary.get("sha256") or _("nicht berechnet"))[:48]),
            (_("Wiederholungen"), cfg.get("repetitions")),
            (_("Batch / UBatch"), f"{cfg.get('batch_size')} / {cfg.get('ubatch_size')}"),
            (_("Flash Attention"), cfg.get("flash_attention")),
            (_("KV-Cache K/V"), f"{cfg.get('cache_type_k')} / {cfg.get('cache_type_v')}"),
        ]
    return [(label, "—" if value is None else str(value)) for label, value in rows]
