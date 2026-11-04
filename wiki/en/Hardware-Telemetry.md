[Deutsch](DE-Hardware-Telemetry) | [English](EN-Hardware-Telemetry)

---

# Hardware Telemetry

llmbench stores performance results together with telemetry.

## CPU

Typical data includes:

- CPU utilization
- physical/logical core counts
- RAM utilization
- power profile/governor where available

CPU package temperature and package power are not standardized across all supported platforms and are therefore not guaranteed core metrics everywhere.

## NVIDIA

Typical measurements include:

- GPU utilization
- VRAM usage
- temperature
- power draw
- power limit
- compute processes
- driver and GPU metadata

## AMD

AMD telemetry is collected through `rocm-smi` where available.

## Intel

Intel GPU telemetry is collected through `xpu-smi` (`xpu-smi discovery -j` for detection, `xpu-smi stats -d <id> -j` once per GPU) where available: utilization, VRAM, temperature and power. Values xpu-smi does not report stay empty rather than `0`; compute processes are not listed.

## Baseline and foreign load

Before load tests, llmbench attempts to capture an idle baseline. Foreign GPU processes are marked as potential interference.

## Measurement scope, units and sampling quality

- `power.coverage` lists exactly which components were measured (`cpu_package`, `gpu:<n>`). Component energy is the sum of those components only; it is **not** wall power. `wall_power_w` / `wall_energy_wh` stay empty unless a real wall-power source exists, and runs with different coverage are never ranked against each other.
- `summary.json` carries a `units` block (percent, bytes, celsius, watt, watt-hour, joule, megahertz, seconds), so values cannot be misread.
- Every GPU entry has `sample_completeness`: the share of samples in which each sensor delivered a value. A value below `1.0` means gaps; gaps are never filled with `0` and are not bridged when integrating energy.
- A device that fails in one sampling round keeps its position with all values empty; this also holds for mixed-vendor systems, where a failing vendor tool no longer shifts the GPUs of the other vendors.
- Power is integrated only between consecutive samples that are at most ten sampling intervals (at least 10 s) apart; a stalled sampler therefore never produces invented energy.
- The `sampling` block records the requested interval, the observed interval and jitter, and the sampler's own duration and overhead fraction.
- Vendor providers (NVML, `rocm-smi`, `xpu-smi`) are covered by deterministic mocked tests (normal, malformed, timeout and missing-sensor output). AMD and Intel mappings have not been verified on physical devices by the test suite; untested hardware is not claimed as validated.

## Raw data

Detailed samples are stored in `raw_*.json`; `summary.json` contains aggregated values.
