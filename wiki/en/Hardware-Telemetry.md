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

## Raw data

Detailed samples are stored in `raw_*.json`; `summary.json` contains aggregated values.
