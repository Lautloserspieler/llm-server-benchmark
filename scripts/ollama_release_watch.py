"""Review upstream Ollama releases and prepare a version bump for human review."""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "llmbench/config.py",
    "llmbench/backend_setup.py",
    "tests/test_config.py",
    "tests/test_backend_setup.py",
    "tests/test_runner.py",
    "docs/architecture/backends.md",
    "docs/architecture/backends.en.md",
)
VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
RELEVANT = re.compile(
    r"api|endpoint|context|token|truncat|shift|gpu|cuda|rocm|model|gguf|"
    r"memory|oom|load|runner|server|docker|security|vulnerab|fix|bug",
    re.IGNORECASE,
)
DOCS_ONLY = re.compile(r"\bdocs?\b|documentation|readme|website|typo|spelling", re.IGNORECASE)
CONTRIBUTOR = re.compile(r"first contribution|new contributors?|full changelog", re.IGNORECASE)


def version_key(tag: str) -> tuple[int, int, int] | None:
    match = VERSION.fullmatch(tag)
    return tuple(map(int, match.groups())) if match else None


def current_version(root: Path = ROOT) -> str:
    cfg = (root / "llmbench/config.py").read_text(encoding="utf-8")
    match = re.search(r'^DEFAULT_OLLAMA_IMAGE = "ollama/ollama:(\d+\.\d+\.\d+)"$', cfg, re.MULTILINE)
    if not match:
        raise ValueError("Ollama default must be a concrete version")
    return match.group(1)


def fetch_releases() -> list[dict]:
    releases: list[dict] = []
    for page in range(1, 11):
        url = f"https://api.github.com/repos/ollama/ollama/releases?per_page=100&page={page}"
        request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "llmbench-release-watch"})
        with urllib.request.urlopen(request, timeout=30) as response:
            batch = json.load(response)
        if not isinstance(batch, list):
            raise ValueError("Unexpected GitHub releases response")
        releases.extend(batch)
        if len(batch) < 100:
            break
    return releases


def review(releases: list[dict], baseline: str) -> dict:
    base_key = version_key(baseline)
    if base_key is None:
        raise ValueError("Invalid baseline version")
    stable = [r for r in releases if not r.get("draft") and not r.get("prerelease")
              and version_key(str(r.get("tag_name", ""))) is not None]
    if not any(version_key(str(r["tag_name"])) == base_key for r in stable):
        raise ValueError(f"Baseline {baseline} missing from release history; refusing incomplete review")
    newer = sorted((r for r in stable if version_key(str(r["tag_name"])) > base_key),
                   key=lambda r: version_key(str(r["tag_name"])))
    findings = []
    for release in newer:
        body = str(release.get("body") or "")
        bullets = [re.sub(r"^\s*[-*]\s+", "", line).strip() for line in body.splitlines()
                   if re.match(r"^\s*[-*]\s+", line) and not CONTRIBUTOR.search(line)]
        relevant = [line for line in bullets if RELEVANT.search(line)]
        docs_only = bool(bullets) and all(DOCS_ONLY.search(line) for line in bullets)
        status = "relevant" if relevant else "irrelevant" if docs_only else "unclear"
        findings.append({"version": str(release["tag_name"]).removeprefix("v"),
                         "url": str(release.get("html_url") or ""), "status": status,
                         "evidence": relevant[:6] if relevant else bullets[:3]})
    candidate = findings[-1]["version"] if findings else None
    return {"baseline": baseline, "candidate": candidate, "update": any(
        item["status"] != "irrelevant" for item in findings), "findings": findings}


def bump(root: Path, old: str, new: str) -> None:
    before, after = f"ollama/ollama:{old}", f"ollama/ollama:{new}"
    for name in FILES:
        path = root / name
        content = path.read_text(encoding="utf-8")
        if before not in content:
            raise ValueError(f"Expected pinned reference absent in {name}")
        path.write_text(content.replace(before, after), encoding="utf-8")


def markdown(result: dict) -> str:
    rows = ["## Proposed Ollama reference update", "",
            f"`{result['baseline']}` → `{result['candidate']}`", "",
            "The weekly check found upstream releases that may affect llmbench. This is an automated",
            "proposal for review, not a claim that the new version is compatible.", "",
            "### Release review", ""]
    for item in result["findings"]:
        labels = {"relevant": "Potentially relevant", "unclear": "Needs manual review",
                  "irrelevant": "Documentation only"}
        rows.extend([f"**[{item['version']}]({item['url']}) — {labels[item['status']]}**", ""])
        if item["evidence"]:
            for note in item["evidence"][:4]:
                clean_note = re.sub(r"[\r\n]", " ", note)[:240]
                rows.append(f"- {clean_note}")
        else:
            rows.append("- No actionable release-note bullets were found. Read the upstream release.")
        rows.append("")
    rows.extend(["### Before merging", "", "- [ ] Read the linked release notes and confirm relevance.",
                 "- [ ] Run the pinned context and error tests on CPU and NVIDIA hardware.",
                 "- [ ] Verify the pulled image digest and check report provenance.", "",
                 "Keyword triage may be incomplete. No automatic merge is configured."])
    return "\n".join(rows) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--releases-json", type=Path, help="Fixture instead of GitHub API")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    releases = json.loads(args.releases_json.read_text(encoding="utf-8")) if args.releases_json else fetch_releases()
    result = review(releases, current_version(args.root))
    if result["update"]:
        bump(args.root, result["baseline"], result["candidate"])
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    args.report.with_suffix(".md").write_text(markdown(result), encoding="utf-8")


if __name__ == "__main__":
    main()
