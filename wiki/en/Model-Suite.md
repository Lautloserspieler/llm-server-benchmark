[Deutsch](DE-Model-Suite) | [English](EN-Model-Suite)

---

# Model Suite

The reference suite covers multiple sizes, model families, and architectures.

| Class | Model | Family | Reference quantization |
| --- | --- | --- | --- |
| small | Qwen3.5-9B | Qwen | Q4_K_M |
| mid | Gemma-4-12B-IT | Gemma | Q4_K_M |
| mid | Qwen3.8-27B | Qwen | Q4_K_M |
| mid | GLM-4.7-Flash | GLM / MoE | Q4_K_M |
| heavy | Qwen3.5-122B-A10B | Qwen / MoE | Q4_K_M |
| heavy | Mistral-Small-4-119B-2603 | Mistral / MoE | UD-Q4_K_M |
| extreme | DeepSeek-V4-Flash-0731 | DeepSeek | UD-Q4_K_XL |

## Model selection uses the terminal UI

During normal setup:

### Windows

```powershell
.\setup.bat
```

### Linux

```bash
./setup.sh
```

llmbench opens an interactive model-selection screen. **All seven reference models** are shown there.

DeepSeek V4 Flash is explicitly marked as:

```text
DeepSeek-V4-Flash-0731 [EXTREME]
```

The Extreme model can be selected by its model number like any other entry.

## What does “A” mean?

**A = All standard models** intentionally selects only:

- Qwen3.5-9B
- Gemma-4-12B-IT
- Qwen3.8-27B
- GLM-4.7-Flash
- Qwen3.5-122B-A10B
- Mistral-Small-4-119B-2603

**DeepSeek-V4-Flash-0731 is not downloaded automatically when A is selected.**

To include Extreme, select DeepSeek separately by its model number. This prevents accidental very large downloads.

## Why multiple families?

A hardware benchmark dominated by one model family can overweight architecture-specific optimizations. Raw measurements remain valid, but broad hardware conclusions become less representative.

The suite therefore contains Qwen, Gemma, GLM, Mistral, and optional DeepSeek.

## Why is Extreme separate?

DeepSeek V4 Flash is substantially larger than the normal reference suite. It is useful for:

- very large RAM/hybrid tests
- unified-memory scenarios
- capacity and server stress testing

It should therefore be **selected deliberately** and never silently included by “All standard models.”

## Saved selection

The terminal UI stores the selected models in:

```text
models/.llmbench-model-selection.json
```

The next run through `START_BENCHMARK.bat` or `START_BENCHMARK.sh` checks exactly that selection and completes missing downloads when required.

Older selections containing `Qwen3.5-35B-A3B` are migrated automatically to `GLM-4.7-Flash`. Existing GGUF files are not deleted automatically.

## Advanced use

The underlying CLI remains available for direct use, but it is **not the normal user workflow**. Setup and regular benchmark runs are intended to use the terminal UI.
