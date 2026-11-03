# Security hardening (v1.7.0)

Deutsch: [SECURITY_HARDENING.de.md](SECURITY_HARDENING.de.md)

This page records the security controls that live in the repository and the steps that must be
performed in the GitHub repository settings. It is the reference for the v1.7.0 hardening work.

## Controls enforced by the repository

- **Archive extraction:** `llmbench/archive.py` validates every TAR/ZIP member before writing.
  Absolute paths, `..`, backslashes, unsafe symlinks, hardlinks, special files, oversized archives and
  excessive member counts are rejected. Extraction uses a staging directory and only replaces the
  install directory after validation succeeds. TAR permits validated relative symlinks inside the destination; ZIP rejects symlinks.
- **Secret handling:** `llmbench/utils.py` redacts credentials in JSON persistence, command logs,
  error messages and exported logs. Configuration files that may contain an API key are written
  atomically with owner-only permissions on POSIX.
- **Workflow permissions:** release-watch workflows use read-only review jobs and write permissions
  only in the dedicated proposal jobs. Draft PRs are created, but nothing is merged automatically.
- **Action pinning:** every remote action is pinned to a full 40-character commit SHA. Dependabot
  continues to propose updates for GitHub Actions, pip and Docker.
- **Image pinning:** CUDA base images and backend images are pinned to a version and `sha256`
  digest. `tests/test_supply_chain.py` guards the pinning.

## Required GitHub repository settings (manual)

These settings cannot be enforced by files in the repository:

1. Protect `main` with a ruleset/branch protection rule:
   - require a pull request before merging,
   - require at least one approval and review from the code owner,
   - dismiss stale approvals after new commits,
   - require the status checks from `tests.yml`, `security.yml` and `docker-image.yml`,
   - block force pushes and branch deletion.
2. Keep the release-watch bot able to create branches and draft PRs, but do not grant it permission
   to merge or to bypass the ruleset. Auto-merge must stay disabled for `bot/*` branches.
3. Keep "Allow GitHub Actions to create and approve pull requests" disabled unless the release
   watch needs it; the bot uses the workflow token instead of approving its own PRs.

## Alert triage

- Treat CodeQL `high`/`critical` findings with a reproducible path as release blockers.
- Medium findings may be fixed or documented as accepted risk; the rationale belongs in the
  pull request or this document.
- Close a code-scanning alert only after the fix is merged or the false-positive rationale is
  recorded.
- Re-run CodeQL and OpenSSF Scorecard after changes to `.github/workflows/**`, `Dockerfile`,
  `pyproject.toml`, dependency files or `SECURITY.md`.

## Image and installer updates

Resolve a new manifest digest with:

```bash
docker buildx imagetools inspect <image>:<tag> --format '{{json .Manifest.Digest}}'
```

Update the tag and digest together in `Dockerfile`, `compose.yaml`, `compose.build.yaml`, `llmbench/config.py` and
`llmbench/backend_setup.py`. The release-watch draft PR intentionally drops the old digest; add the
fresh digest before merging.

For installers:

- Python downloads remain SHA-256 verified.
- `Invoke-UiDownload` retries, writes `.part` files, enforces a size limit and verifies an optional
  SHA-256 value.
- `Assert-LlamaZipSafe` rejects ZIP entries that would escape the extraction directory.
- Authenticode verification for Visual Studio Build Tools, CUDA and Docker Desktop is a follow-up;
  until then those installers rely on HTTPS and the vendor download endpoints.

## Follow-ups by audit ID

| ID | Status in v1.7.0 | Next step |
| --- | --- | --- |
| SEC-06 | Documented | Apply the ruleset described above in GitHub settings. |
| SEC-07 | Documented | Keep `CODEOWNERS` and the maintenance process current. |
| SEC-11 | Partially addressed | CodeQL covers Python and Actions with `security-extended`; deterministic archive tests are in place. Add Hypothesis/Atheris targets for archive and config parsers as a separate change. |
| SEC-12 | Addressed | `SECURITY.md` and `SECURITY.de.md` describe reporting and scope. |
| SEC-13 | Reviewed | Intentional broad exception handlers remain documented; no blind removal. Run `ruff` and CodeQL before releases. |

## Local verification

```bash
ruff check llmbench tests scripts
python -m compileall -q llmbench
python -m pytest -q
actionlint .github/workflows/*.yml   # if actionlint is installed
```

Manual checks that require real hardware or a GitHub runner:

- `workflow_dispatch` for both release watches: review job is read-only, proposal job creates a
  draft PR.
- `workflow_dispatch` for the wiki workflow: publishing succeeds without the token appearing in
  the remote URL or logs.
- Clean Fedora installation, Windows installer path, NVIDIA GPU start and the 8-hour soak test
  (issue #124).
