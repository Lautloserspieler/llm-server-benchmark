# Result contract

[🇩🇪 Deutsch](results.md) | [Overview](README.en.md)

## Goal

A result is more than a performance number. It must retain the conditions under which that
number was produced.

Relevant information includes at least:

- schema/llmbench version,
- task and workload,
- runtime/backend identity,
- model identity and configuration,
- hardware and execution environment,
- benchmark parameters,
- performance and quality metrics,
- telemetry and energy scope,
- status, warnings, and errors,
- provenance of derived values.

## Current state

The current text path still builds result data using the existing internal structure and
writes a versioned artifact through `encode_v3(...)`. Phase 0 does not change this
behavior.

## Task/workload/dataset fields (additive in schema v3)

Decision: **no v4**; optional, additive fields within `schema_version: 3`. Rationale: the new
information does not change the meaning of any existing field; a version bump would lock out
all older readers (`validate_summary` rejects `> 3`) for no reason and force a migration. A v4
becomes necessary only when existing fields are reinterpreted or required fields are
introduced (e.g. with the normalized `Run/Workload[]` model).

| Field | Location | Rule |
| --- | --- | --- |
| `task` | top level | optional; if present, a known `TaskId` |
| `workload` | per `benchmarks.<kind>` | optional; shape `<group>.<name>`; unknown but well-formed IDs stay readable (forward compatibility) |
| `dataset` | top level | optional; object with `id`, `version`, `sha256` (64 hex), optional `selection` |

Absent fields (all existing results) are **not** an error and are not written back into the
file. The text path (`runner.py`, `encode_v3`) does not write them yet;
`llmbench.tasks.infer_task_view()` gives old results a view marked `task_inferred: true`
(task `text_generation`, workload derived from the benchmark kind). Missing measurements
stay `null` with `status`/`reason`, never `0`.

## Future normalization

New task types should not be implemented by adding arbitrary top-level fields throughout
`runner.py`. Long term, the normalized model should distinguish at least:

```text
Run
  Hardware
  Runtime
  Model
  Workload[]
    Metrics
    Telemetry
    Artifacts
    Status
```

## Missing values

Missing, unsupported, skipped, and failed measurements are different states and must not
collapse into the same numeric representation.

Examples:

```text
null / not_measured
unsupported
skipped
failed
timeout
success
```

## Comparability

`compare` may only rank values when task, workload, relevant configuration, and
measurement scope are compatible. STT RTF must never be ranked against text tokens/s or
image seconds/image.

## Artifacts

Task-specific files such as audio, images, meshes, or raw traces belong to the workload
result as referenced artifacts. Large binary data should not be embedded in
`summary.json` without an explicit reason.
