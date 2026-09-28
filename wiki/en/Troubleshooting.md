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

## llama-server does not start

Run `llmbench doctor` and inspect the server log.

## Old selection contains Qwen3.5-35B-A3B

The standard slot is migrated automatically to `GLM-4.7-Flash`. The old GGUF file is not deleted.
