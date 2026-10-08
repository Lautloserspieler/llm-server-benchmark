"""Shared compact rows for power, thermal, energy and efficiency reports."""
from __future__ import annotations

from typing import Any

from .i18n import _


def _number(value: Any, unit: str = "", *, digits: int = 2, scale: float = 1.0) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return _("nicht verfuegbar")
    text = f"{float(value) * scale:.{digits}f}"
    return f"{text} {unit}".rstrip()


def system_power_rows(profile: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """Return report-ready rows without exposing raw telemetry samples."""
    rows: list[tuple[str, str, str, str]] = []
    for kind, result in (profile.get("benchmarks") or {}).items():
        telemetry = result.get("telemetry") or {}
        if not telemetry:
            continue

        cpu = telemetry.get("cpu") or {}
        if cpu:
            rows.extend([
                (
                    str(kind),
                    "CPU",
                    _("Auslastung Ø / Max"),
                    f"{_number(cpu.get('avg_util_percent'), '%')} / "
                    f"{_number(cpu.get('max_util_percent'), '%')}",
                ),
                (
                    str(kind),
                    "CPU",
                    _("Frequenz Ø / Min / Max"),
                    f"{_number(cpu.get('avg_frequency_mhz'), 'GHz', scale=0.001)} / "
                    f"{_number(cpu.get('min_frequency_mhz'), 'GHz', scale=0.001)} / "
                    f"{_number(cpu.get('max_frequency_mhz'), 'GHz', scale=0.001)}",
                ),
                (
                    str(kind),
                    "CPU",
                    _("Temperatur Ø / Max"),
                    f"{_number(cpu.get('avg_temperature_c'), '°C')} / "
                    f"{_number(cpu.get('max_temperature_c'), '°C')}",
                ),
                (
                    str(kind),
                    "CPU",
                    _("Paketleistung Ø / Max"),
                    f"{_number(cpu.get('avg_package_power_w'), 'W')} / "
                    f"{_number(cpu.get('max_package_power_w'), 'W')}",
                ),
                (
                    str(kind),
                    "CPU",
                    _("Energie"),
                    _number(cpu.get("energy_wh"), "Wh", digits=3),
                ),
            ])

        for gpu in telemetry.get("gpus") or []:
            component = f"GPU {gpu.get('index', 0)}"
            rows.extend([
                (
                    str(kind),
                    component,
                    _("Auslastung Ø / Max"),
                    f"{_number(gpu.get('avg_util_gpu_percent'), '%')} / "
                    f"{_number(gpu.get('max_util_gpu_percent'), '%')}",
                ),
                (
                    str(kind),
                    component,
                    _("Temperatur Max"),
                    _number(gpu.get("max_temperature_c"), "°C"),
                ),
                (
                    str(kind),
                    component,
                    _("Leistung Ø / Max"),
                    f"{_number(gpu.get('avg_power_w'), 'W')} / "
                    f"{_number(gpu.get('max_power_w'), 'W')}",
                ),
                (
                    str(kind),
                    component,
                    _("Energie"),
                    _number(gpu.get("energy_wh"), "Wh", digits=3),
                ),
            ])

        power = telemetry.get("power") or {}
        if power:
            coverage = ", ".join(str(item) for item in power.get("coverage") or [])
            rows.extend([
                (
                    str(kind),
                    _("Gemessene Komponenten"),
                    _("Messumfang"),
                    coverage or _("nicht verfuegbar"),
                ),
                (
                    str(kind),
                    _("Gemessene Komponenten"),
                    _("Leistung Ø / Max"),
                    f"{_number(power.get('avg_component_power_w'), 'W')} / "
                    f"{_number(power.get('max_component_power_w'), 'W')}",
                ),
                (
                    str(kind),
                    _("Gemessene Komponenten"),
                    _("Energie"),
                    _number(power.get("component_energy_wh"), "Wh", digits=3),
                ),
            ])
            if power.get("wall_power_w") is not None or power.get("wall_energy_wh") is not None:
                rows.extend([
                    (
                        str(kind),
                        _("Wall-Power"),
                        _("Leistung"),
                        _number(power.get("wall_power_w"), "W"),
                    ),
                    (
                        str(kind),
                        _("Wall-Power"),
                        _("Energie"),
                        _number(power.get("wall_energy_wh"), "Wh", digits=3),
                    ),
                ])

        efficiency = result.get("efficiency") or {}
        if efficiency:
            rows.extend([
                (
                    str(kind),
                    _("Effizienz"),
                    _("Tokens/Joule"),
                    _number(efficiency.get("tokens_per_joule"), "tokens/J", digits=4),
                ),
                (
                    str(kind),
                    _("Effizienz"),
                    _("Wh / 1k Tokens"),
                    _number(efficiency.get("wh_per_1k_tokens"), "Wh/1k tokens", digits=4),
                ),
            ])
    return rows
