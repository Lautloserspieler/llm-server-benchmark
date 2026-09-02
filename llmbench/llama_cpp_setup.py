"""Automatische llama.cpp-Installation fuer Linux und macOS.

Spiegelt fuer Unix-Systeme, was `scripts/START_BENCHMARK_CORE.ps1` unter
Windows tut: einen passenden vorgebauten Release von GitHub laden und unter
`tools/llama.cpp/` ablegen, damit kein manueller Build noetig ist.

llama.cpp veroeffentlicht fuer Linux keine vorgebauten CUDA-Pakete (nur fuer
Windows). Bei erkannter GPU wird deshalb zuerst ein Vulkan-Build versucht -
der laeuft auch auf NVIDIA-/AMD-/Intel-GPUs, nur eben nicht ueber CUDA.
Startet dieser Build auf dem Zielsystem nicht (z. B. weil kein passender
Vulkan-Treiber installiert ist), faellt die Installation automatisch auf
einen CPU-Build zurueck, statt hart abzubrechen.
"""

from __future__ import annotations

import contextlib
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

GITHUB_API = "https://api.github.com/repos/ggml-org/llama.cpp"
TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

LogFn = Callable[[str], None]


def _noop(_msg: str) -> None:
    return None


def target_platform() -> tuple[str, str]:
    """(os_key, arch) fuer die Release-Asset-Auswahl, oder RuntimeError."""
    system = platform.system()
    if system == "Linux":
        os_key = "linux"
    elif system == "Darwin":
        os_key = "macos"
    else:
        raise RuntimeError(
            f"Automatische llama.cpp-Installation wird fuer {system} nicht unterstuetzt "
            "(nur Linux und macOS; Windows nutzt START_BENCHMARK_CORE.ps1)."
        )

    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        arch = "x64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    elif machine == "s390x":
        arch = "s390x"
    else:
        raise RuntimeError(f"Automatische llama.cpp-Installation wird fuer Architektur '{machine}' nicht unterstuetzt.")
    return os_key, arch


def looks_like_gpu_present() -> bool:
    """Grober Hinweis auf vorhandene GPU-Hardware, um einen Vulkan-Versuch zu rechtfertigen."""
    if shutil.which("nvidia-smi"):
        return True
    dri = Path("/dev/dri")
    if dri.exists():
        with contextlib.suppress(OSError):
            if any(dri.glob("render*")):
                return True
    lspci = shutil.which("lspci")
    if lspci:
        try:
            out = subprocess.run([lspci], capture_output=True, text=True, timeout=5).stdout
            if re.search(r"VGA compatible controller|3D controller", out, re.IGNORECASE):
                return True
        except Exception:
            pass
    return False


def pinned_tag(root: Path, explicit: str | None = None) -> str | None:
    """Bevorzugter Build: --tag-Parameter, dann LLMBENCH_LLAMACPP_TAG, dann llama-cpp-version.txt."""
    tag = explicit.strip() if explicit else None
    if not tag and os.environ.get("LLMBENCH_LLAMACPP_TAG"):
        tag = os.environ["LLMBENCH_LLAMACPP_TAG"].strip()
    if not tag:
        pin_file = root / "llama-cpp-version.txt"
        if pin_file.exists():
            for line in pin_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    tag = line
                    break
    if tag and not TAG_RE.match(tag):
        raise RuntimeError(f"'{tag}' ist keine gueltige llama.cpp-Release-Kennung (z. B. b10604).")
    return tag


def _github_get(url: str, allow_missing: bool = False) -> Any:
    req = Request(url, headers={"User-Agent": "llm-server-benchmark-installer", "Accept": "application/vnd.github+json"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(req, timeout=30) as resp:  # noqa: S310 - festes https://api.github.com
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404 and allow_missing:
            return None
        if exc.code == 403:
            raise RuntimeError(
                "GitHub hat die Anfrage abgelehnt (403). Meist ist das API-Limit erreicht. "
                "Spaeter erneut versuchen oder GITHUB_TOKEN setzen."
            ) from exc
        raise RuntimeError(f"GitHub-Anfrage fehlgeschlagen ({url}): {exc}") from exc
    except URLError as exc:
        raise RuntimeError(f"GitHub-Anfrage fehlgeschlagen ({url}): {exc}") from exc


def release_candidates(root: Path, tag: str | None = None) -> list[dict[str, Any]]:
    tag = pinned_tag(root, tag)
    if tag:
        release = _github_get(f"{GITHUB_API}/releases/tags/{tag}", allow_missing=True)
        if not release:
            raise RuntimeError(f"Das llama.cpp-Release '{tag}' existiert nicht.")
        return [release]

    releases: list[dict[str, Any]] = []
    for page in (1, 2, 3):
        batch = _github_get(f"{GITHUB_API}/releases?per_page=30&page={page}")
        if not batch:
            break
        releases.extend(r for r in batch if not r.get("draft"))
    if not releases:
        raise RuntimeError("Keine llama.cpp-Releases konnten von GitHub geladen werden.")
    return releases


def asset_pattern(os_key: str, arch: str, backend: str) -> str:
    if os_key == "macos":
        return rf"^llama-.*-bin-macos-{re.escape(arch)}\.tar\.gz$"
    if backend == "vulkan":
        return rf"^llama-.*-bin-ubuntu-vulkan-{re.escape(arch)}\.tar\.gz$"
    return rf"^llama-.*-bin-ubuntu-{re.escape(arch)}\.tar\.gz$"


def find_asset(releases: list[dict[str, Any]], pattern: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    regex = re.compile(pattern)
    for release in releases:
        for asset in release.get("assets") or []:
            if regex.match(str(asset.get("name") or "")):
                return release, asset
    return None


def _backends_to_try(os_key: str, arch: str) -> list[str]:
    if os_key == "macos":
        return ["cpu"]  # macOS-Pakete haben Metal (arm64) bereits eingebaut, kein separates GPU-Paket.
    backends = []
    if arch in ("x64", "arm64") and looks_like_gpu_present():
        backends.append("vulkan")
    backends.append("cpu")
    return backends


def _download_file(url: str, dest: Path) -> None:
    req = Request(url, headers={"User-Agent": "llm-server-benchmark-installer"})
    with urlopen(req, timeout=120) as resp, open(dest, "wb") as f:  # noqa: S310 - Asset-URL kommt von GitHub-API
        shutil.copyfileobj(resp, f)


def _safe_extractall(tf: tarfile.TarFile, dest: Path) -> None:
    dest_resolved = dest.resolve()
    for member in tf.getmembers():
        target = (dest / member.name).resolve()
        if target != dest_resolved and dest_resolved not in target.parents:
            raise RuntimeError(f"Unsicherer Pfad im llama.cpp-Archiv: {member.name}")
    tf.extractall(dest)  # noqa: S202 - Mitglieder wurden oben geprueft


def _extract(archive: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tf:
        _safe_extractall(tf, dest)

    if not (dest / "llama-bench").exists():
        found = next(dest.rglob("llama-bench"), None)
        if found:
            src_dir = found.parent
            for item in src_dir.iterdir():
                target = dest / item.name
                if not target.exists():
                    shutil.move(str(item), str(target))

    for name in ("llama-bench", "llama-server"):
        p = dest / name
        if p.exists():
            p.chmod(p.stat().st_mode | 0o111)


def probe(bench_path: Path) -> tuple[bool, str]:
    if not bench_path.exists():
        return False, "llama-bench fehlt"
    try:
        proc = subprocess.run(
            [str(bench_path), "--list-devices"], capture_output=True, text=True, timeout=30, check=False
        )
        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return proc.returncode == 0, output[:600]
    except Exception as exc:
        return False, str(exc)


def _existing_install_ok(llama_dir: Path, state_file: Path, log: LogFn) -> bool:
    bench = llama_dir / "llama-bench"
    server = llama_dir / "llama-server"
    if not (bench.exists() and server.exists() and state_file.exists()):
        return False
    ok, _output = probe(bench)
    if not ok:
        log("Vorhandene llama.cpp-Installation ist nicht startbar und wird automatisch neu installiert.")
        return False
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return False
    log(f"llama.cpp ist bereits installiert: {llama_dir} (Build {state.get('tag')} / {state.get('backend')})")
    return True


def _install_asset(
    llama_dir: Path,
    release: dict[str, Any],
    asset: dict[str, Any],
    os_key: str,
    arch: str,
    backend: str,
    state_file: Path,
    log: LogFn,
) -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="llmbench-llama-"))
    try:
        archive = tmp_dir / str(asset["name"])
        log(f"Lade {asset['name']}...")
        _download_file(str(asset["browser_download_url"]), archive)
        _extract(archive, llama_dir)

        bench = llama_dir / "llama-bench"
        server = llama_dir / "llama-server"
        if not bench.exists() or not server.exists():
            raise RuntimeError("llama-bench/llama-server wurden nach dem Entpacken nicht gefunden.")

        ok, output = probe(bench)
        if not ok:
            raise RuntimeError(f"llama-bench startet nach der Installation nicht (Backend {backend}). Ausgabe: {output}")

        state = {
            "tag": release.get("tag_name"),
            "backend": backend,
            "platform": f"{os_key}-{arch}",
            "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "main_asset": asset.get("name"),
        }
        state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"llama.cpp {release.get('tag_name')} ({backend}) wurde installiert: {llama_dir}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def ensure_llama_cpp(
    root: Path,
    llama_dir: Path | None = None,
    tag: str | None = None,
    force: bool = False,
    log: LogFn | None = None,
) -> dict[str, Any]:
    """Sorgt dafuer, dass unter `llama_dir` ein lauffaehiger llama.cpp-Build liegt.

    Gibt bei Erfolg den Inhalt der geschriebenen `.llama-build.json` zurueck.
    Wirft RuntimeError, wenn kein Backend fuer diese Plattform startfaehig war.
    """
    log = log or _noop
    root = Path(root)
    llama_dir = Path(llama_dir) if llama_dir else root / "tools" / "llama.cpp"
    state_file = llama_dir / ".llama-build.json"

    os_key, arch = target_platform()

    if not force and _existing_install_ok(llama_dir, state_file, log):
        return json.loads(state_file.read_text(encoding="utf-8"))

    releases = release_candidates(root, tag)

    last_error: Exception | None = None
    for backend in _backends_to_try(os_key, arch):
        pattern = asset_pattern(os_key, arch, backend)
        found = find_asset(releases, pattern)
        if not found:
            log(f"Kein llama.cpp-Paket fuer Backend '{backend}' auf {os_key}-{arch} gefunden.")
            continue
        release, asset = found
        try:
            llama_dir.parent.mkdir(parents=True, exist_ok=True)
            _install_asset(llama_dir, release, asset, os_key, arch, backend, state_file, log)
            return json.loads(state_file.read_text(encoding="utf-8"))
        except Exception as exc:
            last_error = exc
            log(f"Installation mit Backend '{backend}' fehlgeschlagen: {exc}")
            continue

    detail = f" Letzter Fehler: {last_error}" if last_error else ""
    raise RuntimeError(
        f"Automatische llama.cpp-Installation fehlgeschlagen fuer {os_key}-{arch}.{detail} "
        "Lege llama-bench/llama-server manuell unter tools/llama.cpp/ ab."
    )
