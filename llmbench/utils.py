from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel

console = Console()


def print_msg(msg: str, style: str = "cyan") -> None:
    console.print(msg, style=style)


def print_err(msg: str) -> None:
    from .i18n import _

    console.print(f"[bold red]{_('FEHLER:')}[/bold red] {msg}")


def ask_yes_no(question: str, default: bool = True) -> bool:
    """Ja/Nein-Frage mit sprachabhaengiger Taste (de: j/n, en: y/n); beide werden akzeptiert."""
    from rich.prompt import Confirm, InvalidResponse

    from .i18n import current_language

    yes_key = "j" if current_language() == "de" else "y"

    class _LocalizedConfirm(Confirm):
        choices = [yes_key, "n"]

        def process_response(self, value: str) -> bool:
            answer = value.strip().lower()
            if answer in ("j", "ja", "y", "yes"):
                return True
            if answer in ("n", "nein", "no"):
                return False
            raise InvalidResponse(self.validate_error_message)

    return _LocalizedConfirm.ask(f"[cyan]{question}[/cyan]", default=default, console=console)


def print_section(title: str) -> None:
    """Abschnittsueberschrift als Linie - einheitlich mit den Setup-Skripten."""
    console.print()
    console.rule(f"[bold cyan]{title}[/bold cyan]", align="left", style="cyan")


def print_panel(msg: str, title: str = "LLM Benchmark") -> None:
    console.print(Panel(msg, title=title, border_style="cyan"))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")


def local_now_compact() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_text_atomic(path: str | Path, text: str, *, mode: int | None = None) -> None:
    """Schreibt Text ueber eine Temp-Datei und ersetzt das Ziel atomar."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=p.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            with contextlib.suppress(OSError):
                os.chmod(tmp_name, mode)
        os.replace(tmp_name, p)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def write_json(path: str | Path, data: Any, *, mode: int | None = None) -> None:
    write_text_atomic(
        path,
        json.dumps(redact_secrets(data), indent=2, ensure_ascii=False),
        mode=mode,
    )


_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "api-key",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "passwd",
        "secret",
        "client_secret",
        "authorization",
        "auth",
    }
)
_SECRET_FLAG_NAMES = r"(?:api[-_]?key|token|password|passwd|secret)"
_SECRET_FLAG_EQ_RE = re.compile(
    rf"(?i)^(--?[A-Za-z0-9_-]*{_SECRET_FLAG_NAMES})=(.*)$"
)
_SECRET_FLAG_RE = re.compile(rf"(?i)^(--?[A-Za-z0-9_-]*{_SECRET_FLAG_NAMES})$")
_URL_USERINFO_RE = re.compile(r"(https?://)[^/\s:@]+(?::[^/\s@]*)?@")
_SECRET_TEXT_VALUE = r'''(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;]+)'''
_AUTHORIZATION_RE = re.compile(
    r'''(?i)(\bauthorization["']?\s*[:=][ \t]*)("[^"\r\n]*"|'[^'\r\n]*'|[^\r\n"'<>]+)'''
)
_BEARER_RE = re.compile(r"(?i)\b(bearer)\s+\S+")
_ENV_SECRET_RE = re.compile(
    rf"(?i)\b([A-Z][A-Z0-9_]*(?:_API_KEY|_TOKEN|_PASSWORD|_SECRET)|API_KEY|TOKEN|PASSWORD|SECRET)=({_SECRET_TEXT_VALUE})"
)
_SECRET_FLAG_TEXT_EQ_RE = re.compile(
    rf"(?i)(--?[A-Za-z0-9_-]*{_SECRET_FLAG_NAMES})=({_SECRET_TEXT_VALUE})"
)
_SECRET_FLAG_TEXT_RE = re.compile(
    rf"(?i)(--?[A-Za-z0-9_-]*{_SECRET_FLAG_NAMES})[ \t]+({_SECRET_TEXT_VALUE})"
)


def _redact_string(value: str) -> str:
    def mask(match: re.Match[str], separator: str = "") -> str:
        secret = match.group(2)
        quote = secret[0] if secret.startswith(('"', "'")) else ""
        return f"{match.group(1)}{separator}{quote}***{quote}"

    value = _SECRET_FLAG_TEXT_EQ_RE.sub(lambda m: mask(m, "="), value)
    value = _SECRET_FLAG_TEXT_RE.sub(lambda m: mask(m, " "), value)
    value = _AUTHORIZATION_RE.sub(mask, value)
    value = _BEARER_RE.sub(r"\1 ***", value)
    value = _ENV_SECRET_RE.sub(lambda m: mask(m, "="), value)
    return _URL_USERINFO_RE.sub(r"\1***@", value)


def redact_secrets(value: Any) -> Any:
    """Kopiert eine Struktur und maskiert bekannte Zugangsdatenfelder."""
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and key.lower() in _SECRET_KEYS:
                redacted[key] = "***"
            else:
                redacted[key] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return _redact_sequence(value)
    if isinstance(value, tuple):
        return tuple(_redact_sequence(value))
    if isinstance(value, str):
        return _redact_string(value)
    return value


def _redact_sequence(args: Iterable[Any]) -> list[Any]:
    """Maskiert Flag/Wert-Paare, ohne Typen oder Argumentgrenzen zu aendern."""
    rendered: list[Any] = []
    mask_next = False
    for arg in args:
        if mask_next:
            rendered.append("***")
            mask_next = False
            continue
        if not isinstance(arg, str):
            rendered.append(redact_secrets(arg))
            continue
        eq_match = _SECRET_FLAG_EQ_RE.match(arg)
        if eq_match:
            rendered.append(f"{eq_match.group(1)}=***")
            continue
        if _SECRET_FLAG_RE.match(arg):
            rendered.append(arg)
            mask_next = True
            continue
        rendered.append(_redact_string(arg))
    return rendered


def redact_command(args: Iterable[str]) -> str:
    """Rendert eine Kommandozeile fuer Logs, ohne Secret-Werte zu zeigen."""
    return " ".join(_redact_sequence(args))


def read_json(path: str | Path) -> Any:
    # utf-8-sig transparently accepts both normal UTF-8 and UTF-8 files with a
    # BOM. PowerShell/Windows tooling may emit the latter for .llama-build.json.
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


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
    """Groesse, Aenderungszeit und optional SHA256 einer Datei/eines GGUF-Sets.

    Bei gesplitteten GGUFs wird der komplette Shard-Satz als eine logische Datei
    behandelt. Der kombinierte Hash ist damit auf zwei Servern nur identisch,
    wenn wirklich alle Shards bytegleich vorhanden sind.
    """
    p = Path(path)
    if not p.exists():
        return {"path": str(p), "exists": False}

    files = [p]
    if p.suffix.lower() == ".gguf":
        with contextlib.suppress(Exception):
            from .bootstrap import logical_model_path, model_shards, shard_info, shard_set_complete

            logical = logical_model_path(p)
            if shard_info(logical):
                p = logical
                if not p.exists() or not shard_set_complete(p):
                    return {
                        "path": str(p),
                        "exists": False,
                        "error": "GGUF-Shard-Satz ist unvollstaendig",
                    }
                files = model_shards(p)

    stats = [item.stat() for item in files]
    info: dict[str, Any] = {
        "path": str(p),
        "exists": True,
        "size_bytes": sum(stat.st_size for stat in stats),
        "modified_at": datetime.fromtimestamp(
            max(stat.st_mtime for stat in stats), timezone.utc
        ).isoformat(timespec="seconds"),
    }
    if len(files) > 1:
        info["shards"] = [item.name for item in files]
        info["shard_count"] = len(files)

    if with_hash:
        with contextlib.suppress(OSError):
            if len(files) == 1:
                info["sha256"] = sha256_file(files[0])
            else:
                aggregate = hashlib.sha256()
                for item in files:
                    aggregate.update(item.name.encode("utf-8"))
                    aggregate.update(b"\0")
                    aggregate.update(sha256_file(item).encode("ascii"))
                    aggregate.update(b"\n")
                info["sha256"] = aggregate.hexdigest()
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


def auth_headers(cfg: dict[str, Any]) -> dict[str, str]:
    """Zentralisierte Erstellung von Authorization-Headern."""
    key = cfg.get("api_key")
    return {"Authorization": f"Bearer {key}"} if key else {}


def format_exit_code(code: int | None) -> str:
    """Exitcode lesbar machen - unter Windows sind Abstuerze NTSTATUS-Werte (z. B. -1073741819)."""
    from .i18n import _

    if code is None:
        return _("kein Exitcode")
    unsigned = code & 0xFFFFFFFF
    meanings = {
        0xC0000005: _("Absturz (Zugriffsverletzung)"),
        0xC0000135: _("eine DLL fehlt"),
        0xC0000139: _("eine DLL fehlt"),
        0xC000001D: _("die CPU kennt einen benoetigten Befehlssatz nicht (z. B. AVX)"),
        0xC0000409: _("vom Programm selbst abgebrochen"),
    }
    if unsigned in meanings:
        return f"0x{unsigned:08X} – {meanings[unsigned]}"
    if code < 0 or code > 255:
        return _("Exitcode {code} (0x{hex})").format(code=code, hex=f"{unsigned:08X}")
    return _("Exitcode {code}").format(code=code)


def log_tail(path: str | Path | None, lines: int = 15) -> str:
    """Letzte nicht-leere Zeilen einer Log-Datei (leer, wenn sie fehlt)."""
    if not path:
        return ""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join([line for line in text.splitlines() if line.strip()][-lines:])


def modify_url_port(base_url: str, new_port: int) -> str:
    """Ersetzt den Port einer URL, IPv6-kompatibel."""
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{new_port}"
    return urlunparse((parsed.scheme or "http", netloc, parsed.path, "", "", ""))


def kill_process_tree(proc: subprocess.Popen[Any]) -> None:
    """Terminate a process and all known descendants, then wait for exit.

    Waiting after SIGKILL matters for GPU workloads: until the process has been
    fully reaped, CUDA allocations can still appear in nvidia-smi and the next
    model may start with an artificially low free-VRAM reading.
    """
    try:
        import psutil

        try:
            parent = psutil.Process(proc.pid)
        except psutil.NoSuchProcess:
            with contextlib.suppress(Exception):
                proc.wait(timeout=1)
            return

        children = parent.children(recursive=True)
        for child in reversed(children):
            with contextlib.suppress(Exception):
                child.terminate()
        with contextlib.suppress(Exception):
            parent.terminate()

        _, alive = psutil.wait_procs(children + [parent], timeout=5)
        for item in alive:
            with contextlib.suppress(Exception):
                item.kill()
        if alive:
            psutil.wait_procs(alive, timeout=5)

        with contextlib.suppress(Exception):
            proc.wait(timeout=2)
    except Exception:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            with contextlib.suppress(Exception):
                proc.kill()
            with contextlib.suppress(Exception):
                proc.wait(timeout=5)
