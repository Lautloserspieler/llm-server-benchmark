# Local community export

Deutsch: [community-export.de.md](community-export.de.md)

`community-export` creates one inspectable JSON document per existing suite
summary. It is local-only: it does not upload, authenticate, contact a server,
or replace the private `llmbench export` ZIP.

```sh
llmbench community-settings --nickname bench-user
llmbench community-export results/run --out community-exports
llmbench community-export results/run --preview
llmbench community-export results/run --exclude hardware,energy
llmbench community-validate community-exports/community-run-0001.json
```

Preview writes the exact candidate JSON to stdout and writes no file. Batch
export continues after an invalid input and reports a per-input safe error.
The default includes approved technical fields. `hardware`, `energy`,
`capabilities`, and `telemetry` can be excluded; omissions are recorded in the
payload. Nicknames are optional, local, and self-declared. They are never read
from the operating-system account.

The contract accepts suite `summary.json` and `summary.partial.json` artifacts
with result schemas 1–3. It intentionally does not consume standalone stress
JSON artifacts. The shipped offline schema is
`llmbench/community/schemas/community-export-v1.schema.json` and the checked-in
copy is `docs/schemas/community-export-v1.schema.json`.

## Inputs, output and exit codes

Supply explicit run directories or summary files, with no recursive discovery.
A directory uses `summary.json`; only when it does not exist does it use
`summary.partial.json`. A corrupt final summary is an error, even if a partial
summary exists. The native result validator runs before the allowlist projection.
Unknown input fields are ignored; malformed approved values fail safely.

```sh
llmbench community-export results/run-a results/run-b --out public-results --non-interactive
llmbench community-export old-summary.json --model-label '1=Historic model' --preview
llmbench community-export results/run --model-identity 1=fingerprint --preview
llmbench community-export results/run --rehash-models --out public-results
llmbench community-validate --schema
```

Each run becomes `community-run-0001.json`, `community-run-0002.json`, etc.
Files are created exclusively and existing exports are never overwritten.
Default output is `community-exports`. `--preview` cannot be combined with
`--out`. Its UTF-8, sorted-key, compact JSON plus one newline is byte-for-byte
the saved candidate. Batch preview prints one JSON document per line. Prompts,
per-run diagnostics and final counts use stderr; preview stdout contains only JSON.
Source summaries are never rewritten. Exit codes: 0 all runs succeeded; 1 at
least one run failed, with valid runs retained; 2 invalid invocation/settings.

## Attribution and model choices

`community-settings --nickname NAME`, `--clear-nickname` and `--show` manage
only an optional public nickname. `--settings-file FILE` overrides the settings
location for both settings and export commands. Defaults use macOS
`Library/Application Support/llmbench`, Windows `LOCALAPPDATA/llmbench`, or
Linux `XDG_CONFIG_HOME/llmbench` (falling back to `.config/llmbench`). A malformed
settings file is an error. Export and preview never persist settings or caches.
Nickname precedence is `--no-nickname`, explicit `--nickname`, saved nickname,
then absent. Nicknames are trimmed, bounded to 64 characters and reject controls
and path separators. Attribution is self-declared, not authenticated ownership.

An interactive TTY asks for each unresolved local model: approve a filename-only
label, enter a custom label, or use its fingerprint. Without a TTY, or with
`--non-interactive`, a valid recorded single-file fingerprint is the default.
Otherwise supply an approved label or explicitly request current-file hashing.
Labels are trimmed, limited to 128 characters and reject controls, paths and URLs.
`--model-label N=TEXT` and `--model-identity N=fingerprint` select 1-based model
positions flattened across supplied readable inputs in order; indexes never
enter the payload. Duplicate/conflicting/out-of-range selectors are errors.
Fingerprint selection does not authorize file reads: only `--rehash-models` does.
Choices are reused by proven content hash, including explicit choices on a later
run; matching labels never establish equivalence. The same resolved file path
may reuse an approved display label, without proving historic content identity.

Recorded single-file SHA-256 uses `recorded_single_file_content`. Explicit
rehashing retains that identity only when the recorded digest matches. Otherwise
`current_artifact_unverified` identifies current bytes and the historical run
remains unverified. Split GGUF files use `sha256-shards-v1`: a domain separator,
shard count, then ordered content lengths and SHA-256 digests. Complete GGUF
sequence is required; names do not enter the digest. Historical name-dependent
split hashes are never relabeled as content-only. Missing model files remain
exportable with an approved label and unavailable fingerprint. Structured public
registry IDs/revisions are accepted only when recorded, never inferred from names.

## Version 1 field policy

Every object is closed. The packaged Draft 2020-12 schema describes typed fields;
local validation additionally checks provenance consistency, counts, timestamps,
context curves, references, omissions and configuration-fingerprint consistency.
Schema versions 1–3 of the original result are supported independently of export
schema 1. Future export versions, extra fields, duplicate JSON keys, NaN/Infinity,
boolean counts and invalid unit/source/status combinations are rejected.
Errors contain catalog field paths/numeric indexes and reason codes, never raw
values, unapproved dictionary keys, backend exceptions or validation tracebacks.

| Source location | Public representation and provenance |
|---|---|
| `started_at`, `finished_at`, completion/target | Original UTC `Z` times and recorded/partial/unknown timestamp status; no export-time substitute or local-timezone inference |
| `backend`, `tools`, workload rows | Backend family; separate runtime/version envelopes and measurement-tool commit/build/binary digest; container content digest without private registry/tag |
| `models[].model` | Generated model ID; approved label/public reference/content fingerprint; size/shard count; explicit unverified/unavailable identity |
| `config.benchmark`, profile/endpoint/soak settings | Typed configured values, separately from effective runtime values; full SHA-256 over retained backend and all model settings, scope `exported_configuration_v1`, completeness `retained_configured_fields` |
| `profiles[].benchmarks` | Every approved prompt/generation/long-context row, ordering/repetition count, numeric workload-derived test name, throughput in tokens/s and structured outcome/failure code |
| `profiles[].context_capability` | Requested/completed depths, full pass/OOM/timeout/partial curve, true verified maximum and first failure boundary; no invented TTFT/TPOT |
| `profiles[].kv_cache` | Typed common cache fields plus closed native llama.cpp/vLLM detail catalog, original value/source/unit/status and approved evidence |
| `models[].endpoint`, `models[].soak` | Model-scoped endpoint concurrency/counts/latencies in seconds, warmup and settings; CPU/GPU soak duration/load/drop/throttling with resolvable generated profile references |
| `hardware` | CPU/GPU product facts, core/memory/capacity/driver fields, normalized OS family, recorded supported version/architecture, generated devices/domains and bandwidth envelopes; known NVIDIA MiB converts to bytes |
| Original workload/model/top-level telemetry | Explicit utilization/clock/temperature/memory aggregates, CPU/GPU energy and component/wall power envelopes, source/coverage and efficiency tokens/J, J/1k tokens, Wh/1k tokens; remapped bandwidth/device references |
| Approved evidence | Catalog method/provider/phase/scope/coverage and typed algorithm inputs; free-text reasons become `unknown_reason`; references/arbitrary metadata omitted |

V3 envelopes keep their actual origins, including measured versus calculated
energy. Legacy reference values retain numeric values with null source,
`unknown` status and `legacy_provenance_missing`; export never upgrades them
retroactively. Null envelope `value` and `source` remain explicit. Partial,
capacity-limited, failed, skipped and timeout outcomes are preserved. Completion
of a run does not claim every workload passed. Core validity needs a model
identity and measurement or structured failure; an empty run is rejected.

Automatically collected usernames, hostnames, filesystem paths/shard names,
network addresses/endpoints, credentials/environment, processes/PIDs/commands,
raw prompts/responses/request details, logs, exception text, serials/UUIDs/PCI,
disk/execution/power-scheme blobs and arbitrary future fields are omitted.
Prohibited values are not converted into hash-derived identifiers. Approved
product/model/configuration facts may still be identifying; this contract does
not promise anonymity. `foreign_gpu_load_detected` and structured
`baseline_busy` retain quality signals without process identities/raw baselines.

## Group exclusions and examples

All approved groups are enabled by default. `--exclude` accepts comma-separated
`hardware`, `energy`, `capabilities`, `telemetry`, recorded exactly once in
`omitted_groups`. Hardware hides static facts; remaining observations have
minimal nonidentifying domain references. Energy removes all power/energy and
efficiency across every scope. Telemetry hides utilization, thermal, clock and
memory aggregates while retaining independently selected energy/efficiency and
bandwidth. Capabilities hides KV/context capability and bandwidth fields;
core benchmark rows and their measured context depths remain. Missing values,
zero and excluded groups are distinct. References remain internally consistent.

Generated examples in [examples/community](examples/community/) include
`happy.llama_cpp.json`, `happy.vllm.json`, `partial.json`, `legacy.json`, and
`redacted.json`. They derive from native encoded suite fixtures and validate
locally. They illustrate the contract; they are not benchmark claims for a real
machine. Generation/validation do not invoke a backend, probe hardware, download,
authenticate, upload or contact the network. Future submission/visualization and
multi-turn conversation benchmarking require separate design and approval.
