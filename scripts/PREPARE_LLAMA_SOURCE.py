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


def resolve_ref(explicit_ref: str | None, pin_file: Path) -> str:
    if explicit_ref:
        return explicit_ref.strip()

    env_ref = os.environ.get("LLMBENCH_LLAMACPP_TAG", "").strip()
    if env_ref:
        return env_ref

    pinned = read_pin(pin_file)
    if pinned:
        return pinned

    try:
        atom = get_url(f"https://github.com/{REPO}/releases.atom", timeout=20).decode("utf-8", errors="ignore")
        tags = []
        for match in re.finditer(r"/releases/tag/(b(\d+))", atom):
            tags.append((int(match.group(2)), match.group(1)))
        if tags:
            tags.sort(reverse=True)
            return tags[0][1]
    except Exception:
        pass

    return "master"


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


def extract_source(zip_path: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination, ignore_errors=True)

    with tempfile.TemporaryDirectory(prefix="llmbench-llama-src-", dir=str(destination.parent)) as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(tmp_dir)

        candidates = [p for p in tmp_dir.iterdir() if p.is_dir() and (p / "CMakeLists.txt").is_file()]
        if not candidates:
            candidates = [p.parent for p in tmp_dir.rglob("CMakeLists.txt") if p.parent.is_dir()]
        if not candidates:
            raise RuntimeError("CMakeLists.txt wurde im llama.cpp-Quellarchiv nicht gefunden.")

        tree = candidates[0]
        shutil.copytree(tree, destination, symlinks=False)

    if not (destination / "CMakeLists.txt").is_file():
        raise RuntimeError("llama.cpp wurde entpackt, aber CMakeLists.txt fehlt im Zielordner.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--ref", default="")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    runtime = root / ".runtime"
    cache = runtime / "cache"
    source_root = runtime / "llama-source"
    pin_file = root / "llama-cpp-version.txt"

    ref = resolve_ref(args.ref or None, pin_file)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", ref):
        raise RuntimeError(f"Ungueltige llama.cpp-Source-Kennung: {ref!r}")

    source_dir = source_root / ref
    zip_path = cache / f"llama-{ref}.zip"

    if args.force:
        shutil.rmtree(source_dir, ignore_errors=True)
        zip_path.unlink(missing_ok=True)

    if source_dir.exists() and (source_dir / "CMakeLists.txt").is_file():
        print(f"llama.cpp-Quellcode bereits vorbereitet: {ref}")
    else:
        if source_dir.exists():
            shutil.rmtree(source_dir, ignore_errors=True)

        if not zip_path.exists() or not zipfile.is_zipfile(zip_path):
            print(f"Lade offiziellen llama.cpp-Quellcode ({ref})...")
            download_zip(source_url(ref), zip_path)

        print("Entpacke llama.cpp robust mit Python zipfile...")
        try:
            extract_source(zip_path, source_dir)
        except Exception:
            # Ein kaputtes Cache-Archiv einmal automatisch neu laden.
            shutil.rmtree(source_dir, ignore_errors=True)
            zip_path.unlink(missing_ok=True)
            print("Erster Entpackversuch fehlgeschlagen. Lade das Source-Archiv neu...")
            download_zip(source_url(ref), zip_path)
            extract_source(zip_path, source_dir)

    ref_file = runtime / "llama-source-ref.txt"
    ref_file.write_text(ref, encoding="utf-8")
    hash_file = runtime / "llama-source-sha256.txt"
    hash_file.write_text(sha256(zip_path), encoding="ascii")

    print(f"llama.cpp Source bereit: {source_dir}")
    print(f"Source-Ref: {ref}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
