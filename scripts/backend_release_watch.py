"""Propose pinned backend releases without installing or merging them."""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKENDS = {
    "llama_cpp": {
        "repo": "ggml-org/llama.cpp",
        "image": None,
        "files": ("llama-cpp-version.txt",),
        "tag": re.compile(r"b\d+"),
    },
    "vllm": {
        "repo": "vllm-project/vllm",
        "image": "vllm/vllm-openai",
        "files": ("llmbench/config.py", "llmbench/backend_setup.py", "tests/test_config.py",
                  "tests/test_runner.py", "tests/test_backend_setup.py"),
        "tag": re.compile(r"v\d+\.\d+\.\d+"),
    },
    "tgi": {
        "repo": "huggingface/text-generation-inference",
        "image": "ghcr.io/huggingface/text-generation-inference",
        "files": ("llmbench/config.py", "llmbench/backend_setup.py", "tests/test_config.py",
                  "tests/test_runner.py"),
        "tag": re.compile(r"v?\d+\.\d+\.\d+"),
    },
}
RELEVANT = re.compile(
    r"api|server|infer|context|token|cuda|rocm|gpu|memory|cache|model|gguf|"
    r"docker|security|vulnerab|fix|bug|crash|performance|breaking", re.IGNORECASE,
)
DOCS_ONLY = re.compile(r"\bdocs?\b|documentation|readme|website|typo|spelling", re.IGNORECASE)
CONTRIBUTOR = re.compile(r"first contribution|new contributors?|full changelog", re.IGNORECASE)


def version_key(tag: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", tag))


def current_reference(root: Path, backend: str) -> str:
    if backend == "llama_cpp":
        lines = (root / "llama-cpp-version.txt").read_text(encoding="utf-8").splitlines()
        return next(line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#"))
    image = BACKENDS[backend]["image"]
    cfg = (root / "llmbench/config.py").read_text(encoding="utf-8")
    key = f"DEFAULT_{backend.upper()}_IMAGE"
    match = re.search(rf'^{key} = "{re.escape(image)}:([^"\n]+)"$', cfg, re.MULTILINE)
    if not match:
        raise ValueError(f"Missing default image for {backend}")
    return match.group(1)


def image_tag(backend: str, release_tag: str) -> str:
    # TGI's GitHub release has a v prefix; its published image uses 3.x.y.
    return release_tag.removeprefix("v") if backend == "tgi" else release_tag


def fetch_releases(backend: str, baseline: str) -> list[dict]:
    releases: list[dict] = []
    repo = BACKENDS[backend]["repo"]
    for page in range(1, 11):
        url = f"https://api.github.com/repos/{repo}/releases?per_page=100&page={page}"
        request = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json", "User-Agent": "llmbench-backend-watch",
        })
        with urllib.request.urlopen(request, timeout=30) as response:
            batch = json.load(response)
        if not isinstance(batch, list):
            raise ValueError("Unexpected GitHub releases response")
        releases.extend(batch)
        if baseline != "latest" and any(
            r.get("tag_name") == baseline or (backend == "tgi" and r.get("tag_name") == f"v{baseline}")
            for r in batch
        ):
            break
        if len(batch) < 100:
            break
    return releases


def review(backend: str, releases: list[dict], baseline: str) -> dict:
    spec = BACKENDS[backend]
    release_baseline = ("v" + baseline if backend == "tgi" and baseline != "latest"
                        and not baseline.startswith("v") else baseline)
    if baseline != "latest" and not spec["tag"].fullmatch(release_baseline):
        raise ValueError(f"Invalid baseline {baseline}")
    # llama.cpp publishes numbered b-builds as GitHub prereleases. The b-tag
    # itself is our candidate policy; vLLM and TGI require stable releases.
    stable = [r for r in releases if not r.get("draft")
              and (backend == "llama_cpp" or not r.get("prerelease"))
              and spec["tag"].fullmatch(str(r.get("tag_name", "")))]
    # A manually pinned llama.cpp build can be marked prerelease upstream.
    if baseline != "latest" and not any(
        r.get("tag_name") == release_baseline and not r.get("draft") for r in releases
    ):
        raise ValueError(f"Baseline {baseline} absent from release history")
    newer = sorted((r for r in stable if baseline == "latest"
                    or version_key(r["tag_name"]) > version_key(release_baseline)),
                   key=lambda r: version_key(r["tag_name"]))
    if baseline == "latest":
        newer = newer[-1:]  # First pin: only the latest stable release is relevant.
    findings = []
    for release in newer:
        bullets = [re.sub(r"^\s*[-*]\s+", "", line).strip()
                   for line in str(release.get("body") or "").splitlines()
                   if re.match(r"^\s*[-*]\s+", line) and not CONTRIBUTOR.search(line)]
        relevant = [line for line in bullets if RELEVANT.search(line)]
        docs_only = bool(bullets) and all(DOCS_ONLY.search(line) for line in bullets)
        status = "relevant" if relevant else "irrelevant" if docs_only else "unclear"
        findings.append({"version": release["tag_name"], "status": status,
                         "evidence": relevant[:4] if relevant else bullets[:3]})
    candidate = findings[-1]["version"] if findings else None
    return {"backend": backend, "baseline": baseline, "candidate": candidate,
            "update": bool(candidate) and (baseline == "latest" or any(
                item["status"] != "irrelevant" for item in findings)), "findings": findings}


def bump(root: Path, result: dict) -> None:
    backend = result["backend"]
    baseline, candidate = result["baseline"], result["candidate"]
    spec = BACKENDS[backend]
    if not spec["tag"].fullmatch(candidate):
        raise ValueError("Unsafe candidate tag")
    if backend == "llama_cpp":
        path = root / "llama-cpp-version.txt"
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        hits = [i for i, line in enumerate(lines) if line.strip() == baseline]
        if len(hits) != 1:
            raise ValueError("Expected exactly one llama.cpp pin")
        lines[hits[0]] = lines[hits[0]].replace(baseline, candidate)
        path.write_text("".join(lines), encoding="utf-8")
        return
    old, new = f"{spec['image']}:{baseline}", f"{spec['image']}:{image_tag(backend, candidate)}"
    for name in spec["files"]:
        path = root / name
        content = path.read_text(encoding="utf-8")
        if old not in content:
            raise ValueError(f"Expected reference missing in {name}")
        updated = content.replace(old, new)
        if backend == "vllm" and name == "tests/test_backend_setup.py":
            assertion = f'assert written["tag"] == "{baseline}"'
            if assertion not in updated:
                raise ValueError("Expected vLLM default tag assertion missing")
            updated = updated.replace(assertion, f'assert written["tag"] == "{candidate}"', 1)
        path.write_text(updated, encoding="utf-8")


def markdown(result: dict) -> str:
    backend = result["backend"]
    baseline, candidate = result["baseline"], result["candidate"]
    repo = BACKENDS[backend]["repo"]
    rows = [f"## Review {backend} release", "", f"`{baseline}` → `{candidate or 'no candidate'}`", "",
            "Automated proposal only. No backend image or binary has been installed or tested.", ""]
    if candidate and baseline != "latest":
        rows.extend([f"[Compare all changes](https://github.com/{repo}/compare/{baseline}...{candidate})", ""])
    if baseline == "latest":
        rows.extend(["The current default uses a moving `:latest` image. This PR proposes the first",
                     "fixed version. Check that the matching image exists before merging.", ""])
    findings = result["findings"]
    if len(findings) > 12:
        rows.extend([f"Reviewed {len(findings)} releases; showing the latest 12. "
                     "Use the comparison link above for the full range.", ""])
    for item in findings[-12:]:
        tag = item["version"]
        rows.extend([f"### [{tag}](https://github.com/{repo}/releases/tag/{tag}) — {item['status']}", ""])
        for note in item["evidence"]:
            rows.append("- " + re.sub(r"[\r\n]", " ", note)[:240].replace("<", "&lt;"))
        if not item["evidence"]:
            rows.append("- No actionable release-note bullets; inspect the upstream release manually.")
        rows.append("")
    rows.extend(["### Before merging", "", "- [ ] Read the upstream release and verify image/binary provenance.",
                 "- [ ] Run representative model start, API, context and error tests on CPU/GPU as applicable.",
                 "- [ ] Compare measurements against the pinned baseline and record image digest/build tag.", "",
                 "Keyword triage is incomplete. No automatic merge is configured."])
    return "\n".join(rows) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("backend", choices=BACKENDS)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--releases-json", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    baseline = current_reference(args.root, args.backend)
    releases = (json.loads(args.releases_json.read_text(encoding="utf-8"))
                if args.releases_json else fetch_releases(args.backend, baseline))
    result = review(args.backend, releases, baseline)
    if result["update"]:
        bump(args.root, result)
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    args.report.with_suffix(".md").write_text(markdown(result), encoding="utf-8")


if __name__ == "__main__":
    main()
