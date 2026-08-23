from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import resolve_path
from .hardware import collect_hardware
from .utils import command_exists, resolve_executable, run_capture


def doctor(cfg: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for key in ("llama_bench", "llama_server"):
        value = cfg.get("tools", {}).get(key)
        ok = command_exists(value)
        item = {"name": key, "configured": value, "ok": ok}
        if ok:
            try:
                exe = resolve_executable(value)
                cp = run_capture([exe, "--help"], timeout=20)
                item["resolved"] = exe
                item["returncode"] = cp.returncode
            except Exception as exc:
                item["ok"] = False
                item["error"] = str(exc)
        checks.append(item)

    models = []
    for m in cfg.get("models", []):
        p = Path(resolve_path(m["path"], cfg))
        models.append({"name": m.get("name"), "path": str(p), "exists": p.exists(), "size_bytes": p.stat().st_size if p.exists() else None})

    return {"checks": checks, "models": models, "hardware": collect_hardware()}
