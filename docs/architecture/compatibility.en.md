# Compatibility contract

[🇩🇪 Deutsch](compatibility.md) | [Overview](README.en.md)

## Principle

New architecture phases must not unnecessarily invalidate existing reproducible text
benchmarks. Migrations must be explicit, testable, and documented.

## Configuration

- Missing new optional keys use documented defaults.
- Existing `tools.backend` configurations for llama.cpp/vLLM remain valid.
- A new required field needs a clear migration strategy.
- Unknown or unsupported values should fail validation clearly.

## Results

Previously produced result files should remain readable where the available data is
sufficient. A future loader should convert older schema versions into a common internal
model rather than silently rewriting old files.

## Comparison

Old and new results may only be directly compared when workload-relevant conditions are
demonstrably compatible. Missing historical metadata means `unknown/not comparable`, not
invented equivalence.

## API/abstraction migration

A new abstraction replaces an existing one only when:

1. all current text backends are covered,
2. regression tests protect existing behavior,
3. CLI and reports still work,
4. old configurations are tested,
5. cleanup and failure paths are tested.

## No big-bang rewrite

Multimodal support is introduced incrementally. Existing code may remain as an adapter or
compatibility layer during migration. Rewriting the working text path from scratch is not a
goal.

## Deprecation

If public CLI options or configuration fields eventually need removal, deprecation should
include at least:

- a replacement path,
- a clear warning,
- a documented transition window or target version,
- tests for the migration path.
