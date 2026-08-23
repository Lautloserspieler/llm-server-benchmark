from __future__ import annotations

import contextlib
import hashlib
import json
import re
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Iterable
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def utc_now_compact() -> str:
    """Zeitstempel fuer Ordnernamen. Bewusst UTC, damit Laeufe von Servern in
    verschiedenen Zeitzonen chronologisch sortierbar bleiben."""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")


def local_now_compact() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256_file(path: str | Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def file_fingerprint(path: str | Path, with_hash: bool = True) -> dict[str, Any]:
    """Groesse, Aenderungszeit und optional SHA256 einer Datei."""
    p = Path(path)
    if not p.exists():
        return {"path": str(p), "exists": False}
    stat = p.stat()
    info: dict[str, Any] = {
        "path": str(p),
        "exists": True,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
    }
    if with_hash:
        with contextlib.suppress(OSError):
            info["sha256"] = sha256_file(p)
    return info


def human_bytes(value: float | int | None) -> str:
    if value is None:
        return "—"
    n = float(value)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    idx = 0
    while abs(n) >= 1024 and idx < len(units) - 1:
        n /= 1024.0
        idx += 1
    return f"{n:.2f} {units[idx]}"


def safe_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip())
    return value.strip("._") or "item"


def hostname() -> str:
    return socket.gethostname()


def command_exists(path_or_name: str | None) -> bool:
    if not path_or_name:
        return False
    if Path(path_or_name).exists():
        return True
    from shutil import which

    return which(path_or_name) is not None


def run_capture(cmd: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def resolve_executable(path_or_name: str) -> str:
    p = Path(path_or_name)
    if p.exists():
        return str(p.resolve())
    from shutil import which

    found = which(path_or_name)
    if found:
        return found
    raise FileNotFoundError(f"Programm nicht gefunden: {path_or_name}")


def csv_value(values: Iterable[Any]) -> str:
    return ",".join(str(v) for v in values)


def is_windows() -> bool:
    return sys.platform.startswith("win")


def kill_process_tree(proc: subprocess.Popen[Any]) -> None:
    try:
        import psutil

        parent = psutil.Process(proc.pid)
        children = parent.children(recursive=True)
        for child in children:
            with contextlib.suppress(Exception):
                child.terminate()
        with contextlib.suppress(Exception):
            parent.terminate()
        _, alive = psutil.wait_procs(children + [parent], timeout=5)
        for item in alive:
            with contextlib.suppress(Exception):
                item.kill()
    except Exception:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            with contextlib.suppress(Exception):
                proc.kill()
