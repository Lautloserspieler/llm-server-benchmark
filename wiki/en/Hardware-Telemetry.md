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

## Baseline and foreign load

Before load tests, llmbench attempts to capture an idle baseline. Foreign GPU processes are marked as potential interference.

## Raw data

Detailed samples are stored in `raw_*.json`; `summary.json` contains aggregated values.
