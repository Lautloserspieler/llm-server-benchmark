#!/usr/bin/env python3
"""Check that every reference of the shared model catalog really exists.

Needs network access (huggingface.co and registry.ollama.ai), so it is not part of
the normal test run. Run it before changing the catalog and from time to time:

    python scripts/verify_model_catalog.py
    python scripts/verify_model_catalog.py --backend vllm --only qwen3-8b

Exit code 0: all checked references exist. 1: at least one is missing.
2: nothing could be checked (network blocked).
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
from typing import Any

import httpx

from llmbench import model_catalog

HF_API = "https://huggingface.co/api/models/"
OLLAMA_REGISTRY = "https://registry.ollama.ai/v2/"
OK, MISSING, UNREACHABLE = "ok", "missing", "unreachable"


def check_huggingface(client: httpx.Client, repo: str, patterns: tuple[str, ...] = ()) -> tuple[str, str]:
    try:
        response = client.get(HF_API + repo)
    except httpx.HTTPError as exc:
        return UNREACHABLE, type(exc).__name__
    if response.status_code == 404:
        return MISSING, "repository not found"
    if response.status_code in (401, 403):
        # Gated repositories answer 401/403 without a token: they exist.
        return OK, "gated (needs HF_TOKEN)"
    if response.status_code != 200:
        return UNREACHABLE, f"HTTP {response.status_code}"
    if patterns:
        files = [str(item.get("rfilename", "")) for item in response.json().get("siblings", [])]
        if not any(fnmatch.fnmatch(name.lower(), pattern.lower()) for name in files for pattern in patterns):
            return MISSING, f"no file matches {', '.join(patterns)}"
    return OK, ""


def check_ollama(client: httpx.Client, tag: str) -> tuple[str, str]:
    name, _, version = tag.partition(":")
    namespace, _, model = name.rpartition("/")
    path = f"{namespace or 'library'}/{model}/manifests/{version or 'latest'}"
    try:
        response = client.get(
            OLLAMA_REGISTRY + path,
            headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json"},
        )
    except httpx.HTTPError as exc:
        return UNREACHABLE, type(exc).__name__
    if response.status_code == 404:
        return MISSING, "tag not found"
    if response.status_code != 200:
        return UNREACHABLE, f"HTTP {response.status_code}"
    return OK, ""


def verify(
    client: httpx.Client, backends: tuple[str, ...], only: set[str] | None = None
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for model in model_catalog.CATALOG:
        if only and model.id not in only:
            continue
        for backend in backends:
            reference = model.reference(backend)
            if reference is None:
                results.append({"model": model.id, "backend": backend, "ref": "-", "status": "unmapped", "detail": ""})
                continue
            if backend == "ollama":
                status, detail = check_ollama(client, reference.ref)
            else:
                status, detail = check_huggingface(client, reference.ref, reference.patterns)
            results.append(
                {"model": model.id, "backend": backend, "ref": reference.ref, "status": status, "detail": detail}
            )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", action="append", choices=("llama_cpp", "ollama", "vllm"), dest="backends")
    parser.add_argument("--only", action="append", help="catalog model id (repeatable)")
    args = parser.parse_args(argv)
    backends = tuple(args.backends or ("ollama", "llama_cpp", "vllm"))

    with httpx.Client(timeout=20, follow_redirects=True) as client:
        results = verify(client, backends, set(args.only) if args.only else None)

    for row in results:
        print(f"{row['status']:<11} {row['model']:<22} {row['backend']:<10} {row['ref']}  {row['detail']}".rstrip())
    checked = [r for r in results if r["status"] in (OK, MISSING)]
    if not checked:
        print("\nNothing could be checked (network blocked?).", file=sys.stderr)
        return 2
    missing = [r for r in results if r["status"] == MISSING]
    if missing:
        print(f"\n{len(missing)} reference(s) not found. Fix them in llmbench/model_catalog.py.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
