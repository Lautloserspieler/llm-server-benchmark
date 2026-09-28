[Deutsch](DE-Model-Suite) | [English](EN-Model-Suite)

---

# Model Suite

The reference suite spans multiple sizes, model families, and architectures.

| Suite | Model | Family | Reference quantization |
| --- | --- | --- | --- |
| small | Qwen3.5-9B | Qwen | Q4_K_M |
| mid | Gemma-4-12B-IT | Gemma | Q4_K_M |
| mid | Qwen3.8-27B | Qwen | Q4_K_M |
| mid | GLM-4.7-Flash | GLM / MoE | Q4_K_M |
| heavy | Qwen3.5-122B-A10B | Qwen / MoE | Q4_K_M |
| heavy | Mistral-Small-4-119B-2603 | Mistral / MoE | UD-Q4_K_M |
| extreme | DeepSeek-V4-Flash-0731 | DeepSeek | UD-Q4_K_XL |

## Why multiple families?

A benchmark dominated by one model family can overweight architecture-specific optimizations. The raw measurements remain valid, but broad hardware conclusions become less representative.

The suite therefore includes Qwen, Gemma, GLM, Mistral, and optional DeepSeek.

## Suites

```bash
llmbench download --suite small
llmbench download --suite mid
llmbench download --suite heavy
llmbench download --suite all
llmbench download --suite extreme
```

`all` contains small + mid + heavy, but intentionally excludes extreme.

## Saved selection

The setup stores the selected models in:

```text
models/.llmbench-model-selection.json
```

Older selections containing `Qwen3.5-35B-A3B` are migrated to `GLM-4.7-Flash`. Existing GGUF files are not deleted.
