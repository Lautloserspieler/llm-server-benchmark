from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile
import urllib.request
import zipfile

REPO = "ggml-org/llama.cpp"
USER_AGENT = "llm-server-benchmark-source-preparer"


def read_pin(pin_file: Path) -> str | None:
    if not pin_file.exists():
        return None
    for raw in pin_file.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        value = raw.strip()
        if value and not value.startswith("#"):
            return value
    return None


def get_url(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def resolve_latest_ref() -> str:
    try:
        atom = get_url(f"https://github.com/{REPO}/releases.atom", timeout=20).decode("utf-8", errors="ignore")
        tags: list[tuple[int, str]] = []
        for match in re.finditer(r"/releases/tag/(b(\d+))", atom):
            tags.append((int(match.group(2)), match.group(1)))
        if tags:
            tags.sort(reverse=True)
            return tags[0][1]
    except Exception:
        pass
    return "master"


def find_cached_ref(source_root: Path) -> str | None:
    """Find the newest already extracted bNNNN source in the persistent workspace."""
    if not source_root.is_dir():
        return None

    candidates: list[tuple[int, str]] = []
    for entry in source_root.iterdir():
        if not entry.is_dir() or not (entry / "CMakeLists.txt").is_file():
            continue
        match = re.fullmatch(r"b(\d+)", entry.name)
        if match:
            candidates.append((int(match.group(1)), entry.name))

    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]

    master = source_root / "master"
    if (master / "CMakeLists.txt").is_file():
        return "master"
    return None


def resolve_ref(
    explicit_ref: str | None,
    pin_file: Path,
    runtime: Path,
    source_root: Path,
    force: bool,
) -> str:
    """Choose the llama.cpp ref without silently updating every launch.

    Priority:
    1. explicit --ref
    2. LLMBENCH_LLAMACPP_TAG
    3. llama-cpp-version.txt
    4. source recorded by this project
    5. any valid source already cached in %LOCALAPPDATA%/LLMBench/src
    6. latest upstream release

    --force intentionally skips cached source selection so an unpinned setup
    can refresh to the latest upstream release.
    """
    if explicit_ref:
        return explicit_ref.strip()

    env_ref = os.environ.get("LLMBENCH_LLAMACPP_TAG", "").strip()
    if env_ref:
        return env_ref

    pinned = read_pin(pin_file)
    if pinned:
        return pinned

    if not force:
        ref_file = runtime / "llama-source-ref.txt"
        path_file = runtime / "llama-source-path.txt"
        if ref_file.is_file():
            previous_ref = ref_file.read_text(encoding="utf-8-sig", errors="ignore").strip()
            previous_path = ""
            if path_file.is_file():
                previous_path = path_file.read_text(encoding="utf-8-sig", errors="ignore").strip()

            candidates: list[Path] = []
            if previous_path:
                candidates.append(Path(previous_path))
            if previous_ref:
                candidates.append(source_root / previous_ref)

            if previous_ref and any((p / "CMakeLists.txt").is_file() for p in candidates):
                print(f"Verwende bereits vorbereiteten llama.cpp-Stand: {previous_ref}")
                return previous_ref

        cached_ref = find_cached_ref(source_root)
        if cached_ref:
            print(f"Verwende persistent gecachten llama.cpp-Stand: {cached_ref}")
            return cached_ref

    return resolve_latest_ref()


def source_url(ref: str) -> str:
    if ref == "master":
        return f"https://codeload.github.com/{REPO}/zip/refs/heads/master"
    return f"https://codeload.github.com/{REPO}/zip/refs/tags/{ref}"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_zip(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    if tmp.exists():
        tmp.unlink()

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as response, tmp.open("wb") as out:
        shutil.copyfileobj(response, out, length=1024 * 1024)

    if not zipfile.is_zipfile(tmp):
        tmp.unlink(missing_ok=True)
        raise RuntimeError("Heruntergeladene llama.cpp-Datei ist kein gueltiges ZIP-Archiv.")

    tmp.replace(target)


def safe_rmtree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def extract_source(zip_path: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    safe_rmtree(destination)

    with tempfile.TemporaryDirectory(prefix="x-", dir=str(destination.parent)) as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(tmp_dir)

        candidates = [p for p in tmp_dir.iterdir() if p.is_dir() and (p / "CMakeLists.txt").is_file()]
        if not candidates:
            candidates = [p.parent for p in tmp_dir.rglob("CMakeLists.txt") if p.parent.is_dir()]
        if not candidates:
            raise RuntimeError("CMakeLists.txt wurde im llama.cpp-Quellarchiv nicht gefunden.")

        shutil.move(str(candidates[0]), str(destination))

    if not (destination / "CMakeLists.txt").is_file():
        raise RuntimeError("llama.cpp wurde entpackt, aber CMakeLists.txt fehlt im Zielordner.")


def get_short_work_root() -> Path:
    explicit = os.environ.get("LLMBENCH_WORK_ROOT", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return (Path(local_app_data) / "LLMBench").resolve()

    return (Path(tempfile.gettempdir()) / "LLMBench").resolve()


def write_source_metadata(runtime: Path, ref: str, source_dir: Path, work_root: Path, zip_path: Path) -> None:
    (runtime / "llama-source-ref.txt").write_text(ref, encoding="utf-8")
    (runtime / "llama-source-path.txt").write_text(str(source_dir), encoding="utf-8")
    (runtime / "llama-work-root.txt").write_text(str(work_root), encoding="utf-8")

    hash_file = runtime / "llama-source-sha256.txt"
    if zip_path.is_file():
        hash_file.write_text(sha256(zip_path), encoding="ascii")
    else:
        hash_file.unlink(missing_ok=True)
        print("Hinweis: Source-Cache-ZIP fehlt; SHA-256-Metadatum wird uebersprungen.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--ref", default="")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    runtime = root / ".runtime"
    cache = runtime / "cache"
    work_root = get_short_work_root()
    source_root = work_root / "src"
    pin_file = root / "llama-cpp-version.txt"

    runtime.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    source_root.mkdir(parents=True, exist_ok=True)

    ref = resolve_ref(args.ref or None, pin_file, runtime, source_root, args.force)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", ref):
        raise RuntimeError(f"Ungueltige llama.cpp-Source-Kennung: {ref!r}")

    source_dir = source_root / ref
    zip_path = cache / f"llama-{ref}.zip"

    if args.force:
        safe_rmtree(source_dir)
        zip_path.unlink(missing_ok=True)

    if source_dir.exists() and (source_dir / "CMakeLists.txt").is_file():
        print(f"llama.cpp-Quellcode bereits vorbereitet: {ref}")
    else:
        safe_rmtree(source_dir)

        if not zip_path.exists() or not zipfile.is_zipfile(zip_path):
            print(f"Lade offiziellen llama.cpp-Quellcode ({ref})...")
            download_zip(source_url(ref), zip_path)

        print(f"Entpacke llama.cpp in kurzen Windows-Pfad: {source_dir}")
        try:
            extract_source(zip_path, source_dir)
        except Exception:
            safe_rmtree(source_dir)
            zip_path.unlink(missing_ok=True)
            print("Erster Entpackversuch fehlgeschlagen. Lade das Source-Archiv neu...")
            download_zip(source_url(ref), zip_path)
            extract_source(zip_path, source_dir)

    if not (source_dir / "CMakeLists.txt").is_file():
        raise RuntimeError(f"Vorbereiteter llama.cpp-Source ist unvollstaendig: {source_dir}")

    write_source_metadata(runtime, ref, source_dir, work_root, zip_path)

    print(f"llama.cpp Source bereit: {source_dir}")
    print(f"Source-Ref: {ref}")
    print(f"Kurzer Build-Workspace: {work_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
