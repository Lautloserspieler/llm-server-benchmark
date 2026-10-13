# Telemetry contract

[🇩🇪 Deutsch](telemetry.md) | [Overview](README.en.md)

## Purpose

Telemetry describes system state while a workload runs. It is task-independent and should
therefore be shared across text, speech, image, and enterprise workloads.

## Current state

`TelemetryProvider` already exists with NVIDIA, AMD, and fallback paths, plus
`CompositeProvider` for multiple sources. Existing fields and providers remain compatible.

## Core rules

- An unavailable field is `null`/not measured, not automatically `0`.
- Measurement source and scope must remain traceable.
- Component energy may only be compared when scope and component coverage are compatible.
- Raw samples and aggregated values must remain distinguishable.
- Telemetry failure should only abort a benchmark when that measurement was explicitly
  configured as mandatory.

## Shared target domains

Long term, the common telemetry layer should be able to carry values from:

```text
CPU utilization / temperature / package power
RAM usage
GPU utilization / VRAM / temperature / power
memory-bandwidth observations
disk I/O
network I/O
process ownership / foreign load
thermal/throttling indicators
```

Not every platform is required to provide every field.

## Provenance

Every derived efficiency or telemetry value must retain enough metadata to identify:

- which provider measured it,
- which component was measured,
- which interval was used,
- whether the value was directly observed or calculated.

This provenance is part of comparability and must not be lost in reporting.
