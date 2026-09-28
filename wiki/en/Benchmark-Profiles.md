[Deutsch](DE-Benchmark-Profiles) | [English](EN-Benchmark-Profiles)

---

# Benchmark Profiles

## CPU-only

```yaml
gpu_layers: 0
```

Useful for CPU comparisons, RAM bandwidth testing, and large models that do not fit in VRAM.

## Full-GPU

```yaml
gpu_layers: -1
```

In normal `gpu` mode, llmbench performs a conservative preflight against detected VRAM capacity.

## Hybrid

Partial offload is useful when a model does not fit entirely in VRAM.

## GPU overload

```bash
llmbench run --hardware gpu_overload
```

A deliberate boundary test for unified memory and oversized models. Do not compare it directly with normal `gpu` runs.

## Soak thread partitioning

During combined CPU/GPU soak testing, CPU and GPU servers share the CPU thread budget at roughly 75/25 by default.

Example on a 32-thread system:

```text
CPU server: 24
GPU server: 8
```

CPU and GPU use separate concurrency and timeout settings.
