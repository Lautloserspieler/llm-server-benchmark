# GitHub issue labels / Issue-Labels

**Source of truth:** [`.github/issue-labels.json`](../.github/issue-labels.json).

The project uses color-coded labels to tell contributors **what an issue is, what subsystem it covers, how urgently it matters, and which release it targets**. Generic `enhancement` is intentionally removed from managed roadmap issues only; historical/unrelated issues remain untouched.

## Label groups

| Prefix | Meaning / Bedeutung | Color family |
| --- | --- | --- |
| `kind:` | Issue type / Aufgabenart: tracking, feature, bug, validation, maintenance, refactor, documentation | Slate, blue, red, cyan, gray, violet, teal |
| `area:` | Functional ownership / Modul: backends, telemetry, benchmark, reporting, platform, multimodal, datasets | Distinct subsystem colors |
| `priority:` | Urgency / Dringlichkeit: p0 (release blocker), p1 (high), p2 (normal) | Red, orange, yellow |
| `release:` | Target release / Zielversion: 1.7.0, 1.8.0, 1.9.0, 2.0.0 | Light blue, green, orange, violet |

**Rule:** Most technical issues receive one `kind:`, one `area:`, one `release:`, and one `priority:`. Issues that cover two subsystems may receive two `area:` labels. Umbrella tracking issues do not need a priority. Labels describe classification only; issue/PR state and project boards track the actual work status.

## Current roadmap mapping

- **v1.7.0:** #116 and implementation tasks #120–#124
- **v1.8.0:** #117 and implementation tasks #125–#128
- **v1.9.0:** #118 and implementation tasks #129–#132
- **v2.0.0:** #119 and implementation tasks #133–#139
- **Cross-release index:** #140 (`kind:tracking`)

Issue #71 and other historical issues are not changed by this rollout.

## How syncing works / Synchronisierung

The workflow [`sync-issue-labels.yml`](../.github/workflows/sync-issue-labels.yml) runs when the files that define label behavior are pushed to `main`. It is also manually dispatchable in GitHub Actions with a **dry-run** option. It creates missing labels, updates changed descriptions/colors, and assigns taxonomy labels only to the explicit issue numbers in `issue_assignments`.

It **never deletes a repository label**, never touches issues outside the mapping, and preserves any labels outside this managed taxonomy on mapped issues. On mapped issues, legacy `enhancement` is removed so everything is not simply filed as an enhancement.

To preview locally using a suitable token (requires repository issue-read access):

```bash
GITHUB_TOKEN=... python scripts/sync_issue_labels.py --repo Lautloserspieler/llm-server-benchmark --dry-run
```

To synchronize locally (token must have permission to create/update labels and edit issues):

```bash
GITHUB_TOKEN=... python scripts/sync_issue_labels.py --repo Lautloserspieler/llm-server-benchmark
```

Do not store API tokens in version control or commit local credentials.

## Contributor conventions

1. Start at #140 or the release tracker.
2. Select a narrowly scoped child issue and comment on implementation ownership.
3. Do not apply `priority:p0` just because a feature is important; reserve it for correctness failures or blockers of an imminent release.
4. Use `kind:validation` for test/evidence work and `kind:bug` for defects; do not use `kind:feature` for everything.
5. Update `.github/issue-labels.json` for lasting changes to the palette. CI applies changes only after review and merge.
6. Keep any new public contributor documentation available in English and German.
