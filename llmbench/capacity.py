"""Speicher-Preflight fuer GPU-Profile.

Die Messung soll unmoegliche Full-GPU-Konfigurationen nicht minutenlang in
Unified-Memory/Paging oder einen vorhersehbaren OOM laufen lassen. Die Pruefung
ist absichtlich konservativ und greift nur, wenn die VRAM-Groesse bekannt ist
und ein Profil wirklich alle Layer auf die GPU legen will (``gpu_layers=-1``).
Hybrid-Profile bleiben unangetastet, weil deren reale VRAM-Belegung ohne
Modell-Metadaten nicht verlaesslich aus der GGUF-Dateigroesse abgeleitet werden
kann.
"""

from __future__ import annotations

import contextlib
from functools import lru_cache
from typing import Any

from .hardware import collect_hardware
from .utils import file_fingerprint, human_bytes

MIB = 1024 * 1024
DEFAULT_FULL_GPU_BUDGET_FRACTION = 0.90


def total_gpu_vram_bytes(hardware: dict[str, Any]) -> int:
    """Summiert bekannten VRAM in Bytes.

    ``hardware.collect_hardware`` liefert fuer NVIDIA/Intel ``memory.total`` in
    MiB. Telemetrie-Snapshots koennen dagegen bereits ``memory_total_bytes``
    enthalten; beide Formen werden akzeptiert.
    """
    total = 0
    for gpu in hardware.get("gpus", []) or []:
        raw_bytes = gpu.get("memory_total_bytes")
        if raw_bytes not in (None, ""):
            try:
                total += max(0, int(float(raw_bytes)))
                continue
            except (TypeError, ValueError):
                pass
        raw_mib = gpu.get("memory.total")
        if raw_mib not in (None, ""):
            with contextlib.suppress(TypeError, ValueError):
                total += max(0, int(float(raw_mib) * MIB))
    return total


def _gpu_layers(profile: dict[str, Any]) -> int | None:
    try:
        return int(profile.get("gpu_layers", -1))
    except (TypeError, ValueError):
        return None


def is_gpu_profile(profile: dict[str, Any]) -> bool:
    layers = _gpu_layers(profile)
    return layers is not None and layers != 0


def is_full_gpu_profile(profile: dict[str, Any]) -> bool:
    return _gpu_layers(profile) == -1


def profile_vram_issue(
    model_meta: dict[str, Any],
    profile: dict[str, Any],
    hardware: dict[str, Any],
    default_budget_fraction: float = DEFAULT_FULL_GPU_BUDGET_FRACTION,
) -> str | None:
    """Liefert einen Grund zum Ueberspringen eines vorhersehbar zu grossen Profils.

    Nur Full-GPU wird blockiert. ``allow_oversized_gpu: true`` ist ein bewusstes
    Opt-out fuer Experimente mit Unified Memory oder speziellen Backends.
    """
    if not is_full_gpu_profile(profile) or profile.get("allow_oversized_gpu"):
        return None

    model_size = model_meta.get("size_bytes")
    try:
        model_size_bytes = int(model_size)
    except (TypeError, ValueError):
        return None
    if model_size_bytes <= 0:
        return None

    vram_bytes = total_gpu_vram_bytes(hardware)
    if vram_bytes <= 0:
        return None

    fraction = profile.get("vram_fit_fraction", default_budget_fraction)
    try:
        fraction = float(fraction)
    except (TypeError, ValueError):
        fraction = default_budget_fraction
    fraction = min(0.98, max(0.50, fraction))
    budget = int(vram_bytes * fraction)

    if model_size_bytes <= budget:
        return None

    return (
        "Full-GPU wurde vor dem Start uebersprungen: Die GGUF-Gewichte sind "
        f"{human_bytes(model_size_bytes)} gross, fuer Gewichte sind bei "
        f"{human_bytes(vram_bytes)} erkanntem VRAM konservativ nur "
        f"{human_bytes(budget)} ({fraction * 100:.0f} %) freigegeben. "
        "Nutze ein Hybrid-/Partial-Offload-Profil oder setze im Profil "
        "allow_oversized_gpu: true, wenn Unified Memory bewusst getestet werden soll."
    )


@lru_cache(maxsize=1)
def current_hardware() -> dict[str, Any]:
    """Ein Prozess braucht fuer alle Preflights nur einen Hardware-Snapshot."""
    return collect_hardware()


def profile_vram_issue_for_path(
    model_path: str,
    profile: dict[str, Any],
    hardware: dict[str, Any] | None = None,
) -> str | None:
    fingerprint = file_fingerprint(model_path, with_hash=False)
    if not fingerprint.get("exists"):
        return None
    return profile_vram_issue(
        {"size_bytes": fingerprint.get("size_bytes")},
        profile,
        hardware if hardware is not None else current_hardware(),
    )
