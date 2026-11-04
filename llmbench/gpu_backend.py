"""Which GPU API a llama.cpp build really uses, and whether that is acceptable.

On NVIDIA cards a Vulkan build is, in practice, much slower than CUDA. A run
must therefore never fall back to Vulkan silently: the installed build is
shown, a Vulkan/CPU build on an NVIDIA system is reported, and a user who
selected CUDA gets an error instead of a Vulkan measurement.

The source of truth is what the binary itself reports with ``--list-devices``
(lines such as ``CUDA0: ...`` or ``Vulkan0: ...``), not what was requested.
"""

from __future__ import annotations

import re
from typing import Any

KNOWN_BACKENDS = ("cuda", "vulkan", "cpu")
_DEVICE_LINE = re.compile(r"^\s*(?P<api>[A-Za-z][A-Za-z]*?)(?P<index>\d+)\s*:\s*(?P<name>.+)$")
_API_ALIASES = {
    "cuda": "cuda",
    "vulkan": "vulkan",
    "hip": "hip",
    "rocm": "hip",
    "metal": "metal",
    "sycl": "sycl",
    "opencl": "opencl",
}


def runtime_gpu_apis(devices_output: str | None) -> list[str]:
    """GPU APIs listed by ``llama-bench --list-devices`` (e.g. ``["cuda"]``).

    An empty list means the binary lists no GPU device at all (CPU only).
    """
    apis: list[str] = []
    for line in (devices_output or "").splitlines():
        match = _DEVICE_LINE.match(line)
        if not match:
            continue
        api = _API_ALIASES.get(match.group("api").lower())
        if api and api not in apis:
            apis.append(api)
    return apis


def effective_backend(tools: dict[str, Any] | None) -> dict[str, Any]:
    """Build type of the tested llama.cpp: installed marker plus runtime check."""
    bench = (tools or {}).get("llama_bench") or {}
    marker = bench.get("build_marker") or {}
    installed = marker.get("backend") if isinstance(marker, dict) else None
    runtime = runtime_gpu_apis(bench.get("devices_output"))
    if runtime:
        actual = "+".join(runtime)
    elif installed:
        actual = str(installed)
    else:
        actual = None
    return {
        "installed": installed,
        "requested": marker.get("requested_backend") if isinstance(marker, dict) else None,
        "runtime_apis": runtime,
        "effective": actual,
    }


def check(
    tools: dict[str, Any] | None,
    *,
    nvidia_present: bool,
    uses_gpu: bool,
    requested: str | None = None,
) -> tuple[str, str] | None:
    """Judge the build. Returns ``("error"|"warning", message)`` or ``None``.

    * ``requested == "cuda"`` and the binary does not list CUDA: error.
    * NVIDIA card present, GPU profiles in the run, but no CUDA: warning.
    """
    info = effective_backend(tools)
    apis = info["runtime_apis"]
    wanted = (requested or info["requested"] or "").lower() or None
    cuda_ok = "cuda" in apis or (not apis and info["installed"] == "cuda")

    if wanted == "cuda" and not cuda_ok:
        return (
            "error",
            f"CUDA wurde angefordert, der installierte llama.cpp-Build nutzt aber "
            f"'{info['effective'] or 'unbekannt'}'. Es wird nicht stillschweigend mit Vulkan/CPU gemessen. "
            "CUDA Toolkit (nvcc) installieren und `llmbench install-llama-cpp --backend cuda --force` ausfuehren.",
        )
    if nvidia_present and uses_gpu and not cuda_ok and wanted in (None, "auto"):
        return (
            "warning",
            f"Auf diesem System steckt eine NVIDIA-GPU, llama.cpp laeuft aber ueber "
            f"'{info['effective'] or 'unbekannt'}' statt CUDA. Vulkan ist auf NVIDIA-Karten erfahrungsgemaess "
            "deutlich langsamer; die Werte sind mit CUDA-Messungen nicht vergleichbar. "
            "Fuer CUDA: CUDA Toolkit (nvcc) installieren und "
            "`llmbench install-llama-cpp --backend cuda --force` ausfuehren.",
        )
    return None


def label(tools: dict[str, Any] | None) -> str:
    """Short text for reports, e.g. ``cuda`` or ``vulkan``."""
    return effective_backend(tools)["effective"] or "unbekannt"
