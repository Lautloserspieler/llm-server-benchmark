[Deutsch](DE-Troubleshooting) | [English](EN-Troubleshooting)

---

# Troubleshooting

## Model downloaded but was reported as failed

Current `huggingface_hub` versions can update the progress callback after the file itself has already completed. llmbench re-checks the local GGUF after late progress errors.

```bash
llmbench download --suite all --verify-only
```

## Model is not detected

Check:

- `.gguf` file extension
- complete shard set
- correct quantization
- `models/.llmbench-model-selection.json`
- correct model directory

## OOM / insufficient VRAM

Options include:

- smaller model
- stronger quantization
- hybrid profile
- deliberate `gpu_overload`

## CPU test takes extremely long

Large CPU-only models can take hours. CPU and GPU have separate timeouts, and the Long preset gives CPU runs substantially more time.

## GPU does not reach its power limit

A power limit is only an upper bound. Not every inference workload reaches it.

```bash
nvidia-smi
```

## Foreign load

Stop unrelated compute processes or document the warning. Foreign load can distort throughput and telemetry.

## Vulkan instead of CUDA on an NVIDIA card

On NVIDIA cards a Vulkan build of llama.cpp is, in practice, much slower than CUDA, so llmbench never lets it happen unnoticed:

- The "Test conditions" block shows the **GPU API** the binary really reports (`cuda`, `vulkan`, ...), taken from `--list-devices`, not just what was requested.
- With an NVIDIA GPU and a Vulkan/CPU build, the run prints a warning and stores it in the result; the numbers are then not comparable with CUDA measurements.
- If you **request CUDA**, a Vulkan or CPU build is an error: the run stops before any measurement instead of silently using Vulkan.

To get CUDA, install the CUDA Toolkit (`nvcc`) and build explicitly:

```bash
llmbench install-llama-cpp --backend cuda --force
```

`--backend` accepts `auto`, `cuda`, `vulkan` and `cpu`. The same choice can be set with `LLMBENCH_LLAMACPP_BUILD_BACKEND`. The installer stores what was requested next to what was installed (`.llama-build.json`).

## llama-server does not start

Run `llmbench doctor` and inspect the server log.

## Old selection contains Qwen3.5-35B-A3B

The standard slot is migrated automatically to `GLM-4.7-Flash`. The old GGUF file is not deleted.
