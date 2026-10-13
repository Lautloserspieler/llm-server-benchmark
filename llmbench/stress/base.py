from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from llmbench.backends.base import BenchmarkBackend
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
