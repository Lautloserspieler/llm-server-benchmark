#!/usr/bin/env python3
"""Idempotently sync GitHub issue-label colors and managed roadmap assignments.

Run locally:
  GITHUB_TOKEN=... python scripts/sync_issue_labels.py --repo OWNER/REPO --dry-run
  GITHUB_TOKEN=... python scripts/sync_issue_labels.py --repo OWNER/REPO

Only issue numbers explicitly listed in the configuration are relabeled.
Unrelated existing labels are preserved, and the legacy "enhancement" label is
removed *only* from those managed issues. Labels are never deleted globally.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


API_ROOT = "https://api.github.com"
COLOR_PATTERN = re.compile(r"^[0-9a-fA-F]{6}$")
API_VERSION = "2022-11-28"


def validate_config(config: dict[str, Any]) -> None:
    """Reject invalid or dangerous sync configurations before any mutations."""
    if config.get("schema_version") != 1:
        raise ValueError("Unsupported issue-label config schema_version")
    labels = config.get("labels")
    assignments = config.get("issue_assignments")
    if not isinstance(labels, list) or not labels:
        raise ValueError("labels must be a nonempty list")
    if not isinstance(assignments, dict):
        raise ValueError("issue_assignments must be a mapping")
    names: set[str] = set()
    for label in labels:
        if not isinstance(label, dict):
            raise ValueError("Each label must be an object")
        name = label.get("name")
        color = label.get("color")
        desc = label.get("description")
        if not isinstance(name, str) or not name.strip() or len(name) > 50:
            raise ValueError(f"Invalid label name: {name!r}")
        if name in names:
            raise ValueError(f"Duplicate label name: {name}")
        if not isinstance(color, str) or COLOR_PATTERN.fullmatch(color) is None:
            raise ValueError(f"Invalid hex color for label: {name}")
        if not isinstance(desc, str) or len(desc) > 100:
            raise ValueError(f"Invalid label description: {name}")
        names.add(name)
    for issue_id, targets in assignments.items():
        if not isinstance(issue_id, str) or not issue_id.isdecimal() or int(issue_id) <= 0:
            raise ValueError(f"Invalid issue number: {issue_id!r}")
        if not isinstance(targets, list) or not targets or len(set(targets)) != len(targets):
            raise ValueError(f"Empty/duplicate labels on issue #{issue_id}")
        unknown = set(targets).difference(names)
        if unknown:
            raise ValueError(f"Unknown label(s) on issue #{issue_id}: {sorted(unknown)}")
        for prefix in ("kind:", "priority:", "release:"):
            if sum(value.startswith(prefix) for value in targets) > 1:
                raise ValueError(f"Conflicting {prefix} labels on issue #{issue_id}")


def api_request(token: str, method: str, path: str, data: dict[str, Any] | None = None) -> Any:
    payload = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "llmbench-issue-label-sync",
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = Request(API_ROOT + path, data=payload, headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    except HTTPError as exc:
        detail = exc.read(1200).decode("utf-8", "replace")
        raise RuntimeError(f"GitHub API {method} {path}: HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"GitHub API {method} {path}: {exc}") from exc


def repository_path(repo: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Repository must be OWNER/REPO")
    return "/repos/" + repo


def sync_labels(token: str, repo: str, config: dict[str, Any], *, dry_run: bool) -> None:
    path = repository_path(repo)
    existing: dict[str, dict[str, Any]] = {}
    page = 1
    while True:
        values = api_request(token, "GET", f"{path}/labels?per_page=100&page={page}")
        if not isinstance(values, list):
            raise RuntimeError("Expected a GitHub label list")
        for label in values:
            existing[label["name"]] = label
        if len(values) < 100:
            break
        page += 1

    managed_names = {label["name"] for label in config["labels"]}
    counters = {"created": 0, "updated": 0, "issues": 0, "unchanged": 0}
    for label in config["labels"]:
        name = label["name"]
        old = existing.get(name)
        target = {"color": label["color"].lower(), "description": label["description"]}
        if old is None:
            print(f"{'WOULD CREATE' if dry_run else 'CREATE'} label {name} #{target['color']}")
            if not dry_run:
                api_request(token, "POST", f"{path}/labels", {"name": name, **target})
            counters["created"] += 1
        elif old.get("color", "").lower() != target["color"] or old.get("description") != target["description"]:
            print(f"{'WOULD UPDATE' if dry_run else 'UPDATE'} label {name} #{target['color']}")
            if not dry_run:
                api_request(token, "PATCH", f"{path}/labels/{quote(name, safe='')}", target)
            counters["updated"] += 1

    for number, targets in sorted(config["issue_assignments"].items(), key=lambda entry: int(entry[0])):
        issue = api_request(token, "GET", f"{path}/issues/{number}")
        # Preserve unrelated labels; only remove taxonomy labels no longer assigned
        # and the generic 'enhancement' label from these explicitly managed issues.
        before = [label["name"] for label in issue["labels"]]
        keep = [name for name in before if name not in managed_names and name != "enhancement"]
        after = list(dict.fromkeys(keep + targets))
        if set(before) == set(after):
            counters["unchanged"] += 1
            continue
        print(f"{'WOULD RELABEL' if dry_run else 'RELABEL'} #{number}: {before} -> {after}")
        if not dry_run:
            api_request(token, "PATCH", f"{path}/issues/{number}", {"labels": after})
        counters["issues"] += 1
    print(f"Done (dry_run={dry_run}): {counters}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync llmbench GitHub label palette and issue assignments")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"), required=False)
    parser.add_argument("--config", type=Path, default=Path(".github/issue-labels.json"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.repo:
        parser.error("--repo or GITHUB_REPOSITORY is required")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        parser.error("GITHUB_TOKEN or GH_TOKEN must be provided")
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        validate_config(config)
        sync_labels(token, args.repo, config, dry_run=args.dry_run)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Label sync failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
