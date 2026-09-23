"""Ladeoptionen fuer llama.cpp, passend zur installierten Version.

Neuere llama.cpp-Builds haben ``--no-mmap`` und ``--mlock`` durch
``-lm/--load-mode <auto|none|mmap|mlock|mmap+mlock|dio>`` ersetzt und brechen
mit ``error: invalid argument: --no-mmap`` ab. Aeltere Builds kennen
``--load-mode`` nicht. Welche Variante gilt, verraet ``<exe> --help``.
"""

from __future__ import annotations

from functools import lru_cache

from .utils import run_capture


@lru_cache(maxsize=16)
def supports_load_mode(exe: str) -> bool:
    """True, wenn ``exe --help`` die Option ``--load-mode`` auffuehrt."""
    try:
        proc = run_capture([exe, "--help"], timeout=15.0)
    except Exception:
        return False
    return "--load-mode" in (proc.stdout or "") + (proc.stderr or "")


def load_flags(exe: str, no_mmap: bool, mlock: bool) -> list[str]:
    """Kommandozeilen-Optionen fuer "ohne mmap laden" und/oder "im RAM sperren"."""
    if not no_mmap and not mlock:
        return []
    if supports_load_mode(exe):
        # mlock ohne mmap laedt das Modell ohnehin komplett in den RAM.
        return ["-lm", "mlock" if mlock else "none"]
    flags = []
    if no_mmap:
        flags.append("--no-mmap")
    if mlock:
        flags.append("--mlock")
    return flags
