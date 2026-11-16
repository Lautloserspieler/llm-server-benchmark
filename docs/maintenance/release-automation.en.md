# Manual release and CI reports

[Deutsch](release-automation.md) | [English](release-automation.en.md)

## Prepare a release

Open **Actions → Manual release → Run workflow** and select `main`.
Use `mode=prepare` with either an explicit `version` (without `v`) or
`bump=patch/minor/major`. The default `dry_run=true` previews release notes in the
run summary without changing sources, branches, tags or releases.

With `dry_run=false`, the bot updates `VERSION`, `pyproject.toml` and
`llmbench/__init__.py`, promotes both Unreleased sections into the new version,
and appends original commit titles since the nearest reachable stable release
tag. Without such a tag it uses the entire history. Titles are not automatically
translated. Tests, Ruff, mypy, dependency checks and packaging must pass before
a draft PR is opened. Existing release branches are never overwritten.
Tests and Security are explicitly dispatched on the proposed branch.

Edit both changelogs, remove duplicate commit entries, review translations, mark
the PR ready, check CI and merge. Automatically triggered PR checks may require
GitHub approval. Repository settings must allow GitHub Actions to create PRs.

## Publish a release

Run the workflow on `main` with `mode=publish`, the exact `version`, `bump=none`
and initially `dry_run=true`. After reviewing, run with `dry_run=false`.
Version sources must match and both changelogs must contain nonempty release
sections. Quality checks run again. Tagging fails if `main` advanced meanwhile.

The bot creates an annotated `vX.Y.Z` tag and a GitHub Release. Existing tags
must point to the same commit; existing releases are not overwritten. A rerun
can resume an interrupted publication. Docker and Tests are explicitly dispatched
on the tag because tags pushed with `GITHUB_TOKEN` do not trigger push workflows.
No additional PAT is required. The GitHub Release may be visible before Docker
finishes. GHCR publication requires the image scan and release quality gate.
Docker dispatches on branches only validate; dispatches on tags also publish.

## Watchers and reports

Backend release watch accepts `backend=all/llama_cpp/vllm`. Both watchers accept
`force` to allow another proposal after a closed PR. Open and merged PRs remain
blocked. Existing candidate branches are reused, never force-pushed.

Coverage, CodeQL, Trivy and Scorecard run artifacts are retained for 14 days.
The published image's SBOM is extracted by immutable digest and retained for
90 days, including the platform-specific BuildKit SBOM documents. Trivy remains
a HIGH/CRITICAL gate and additionally uploads SARIF to Code Scanning. Fork PRs
only preserve the artifact. CodeQL summaries count all SARIF results by SARIF
level, not only new PR alerts. The existing Wiki sync and DE/EN parity check
remain in place.
