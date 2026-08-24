from __future__ import annotations

import hashlib
import json
import re
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return value.strip("._") or "item"


def hostname() -> str:
    return socket.gethostname()


def command_exists(path_or_name: str | None) -> bool:
    if not path_or_name:
        return False
    p = Path(path_or_name)
    if p.exists():
        return True
    from shutil import which
    return which(path_or_name) is not None


def run_capture(cmd: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)


def resolve_executable(path_or_name: str) -> str:
    p = Path(path_or_name)
    if p.exists():
        return str(p.resolve())
    from shutil import which
    found = which(path_or_name)
    if found:
        return found
    raise FileNotFoundError(f"Executable not found: {path_or_name}")


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
            try:
                child.terminate()
            except Exception:
                pass
        try:
            parent.terminate()
        except Exception:
            pass
        _, alive = psutil.wait_procs(children + [parent], timeout=5)
        for item in alive:
            try:
                item.kill()
            except Exception:
                pass
    except Exception:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
