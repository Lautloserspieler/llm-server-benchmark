from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from llmbench.backends.base import BenchmarkBackend
from llmbench.config import resolve_path
from llmbench.i18n import _
from llmbench.utils import print_msg, write_json

SKIPPED_EXIT_CODE = 2


def require_capabilities(
    backend: BenchmarkBackend,
    backend_name: str,
    capabilities: Iterable[str],
    *,
    workload: str,
    result_path: Path,
) -> int | None:
    """Persist a structured skip when a backend cannot run a stress workload.

    Returning None means the workload is supported. A skip is intentionally
    not a failure: callers return exit code 2, matching the existing quant and
    multi-tenant not-applicable behavior.
    """
    required = tuple(dict.fromkeys(capabilities))
    missing = [name for name in required if not backend.supports(name)]
    if not missing:
        return None

    document = {
        "status": "skipped",
        "reason": "backend_capability_missing",
        "workload": workload,
        "backend": backend_name,
        "required_capabilities": list(required),
        "missing_capabilities": missing,
    }
    write_json(result_path, document)
    print_msg(
        _(
            "Stresstest wird fuer Backend '{backend}' uebersprungen: "
            "fehlende Faehigkeiten: {capabilities}."
        ).format(backend=backend_name, capabilities=", ".join(missing)),
        style="yellow",
    )
    return SKIPPED_EXIT_CODE


def resolve_model_ref(model_path: str, cfg: dict[str, Any], backend_name: str) -> str:
    """Modellpfad bzw. Runtime-Referenz fuer ``backend.start_server``.

    Nicht-llama.cpp-Backends akzeptieren Referenzen wie ``llama3.2:3b`` oder
    ``org/model``; diese duerfen nicht zu einem Dateipfad aufgeloest werden
    (gleiche Regel wie ``runner._model_meta``).
    """
    raw = str(model_path)
    path = Path(raw)
    runtime_ref = (
        backend_name != "llama_cpp"
        and not path.exists()
        and not path.is_absolute()
        and not raw.startswith((".", "~"))
        and "\\" not in raw
    )
    return raw if runtime_ref else resolve_path(raw, cfg)
