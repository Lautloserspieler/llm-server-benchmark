[Deutsch](DE-Model-Suite) | [English](EN-Model-Suite)

---

# Model Suite

**The same models are offered on every backend** (llama.cpp, Ollama, vLLM, TGI). Results of different backends are only comparable when the same model was measured, so there is one shared catalog. Each model has the reference that fits the backend:

| Class | Model | Ollama | llama.cpp (GGUF) | vLLM / TGI (Hugging Face) |
| --- | --- | --- | --- | --- |
| small | Gemma 3 1B | `gemma3:1b` · Q4_K_M | `ggml-org/gemma-3-1b-it-GGUF` · Q4_K_M | `google/gemma-3-1b-it` · bf16 |
| small | Granite 4.2 3B | `granite4.2:3b` · Q4_K_M | `ibm-granite/granite-4.2-3b-GGUF` · Q4_K_M | `ibm-granite/granite-4.2-3b` · bf16 |
| small | Qwen3 8B | `qwen3:8b` · Q4_K_M | `Qwen/Qwen3-8B-GGUF` · Q4_K_M | `Qwen/Qwen3-8B` · bf16 |
| mid | DeepSeek-R1 14B | `deepseek-r1:14b` · Q4_K_M | `bartowski/DeepSeek-R1-Distill-Qwen-14B-GGUF` · Q4_K_M | `deepseek-ai/DeepSeek-R1-Distill-Qwen-14B` · bf16 |
| mid | GPT-OSS 20B | `gpt-oss:20b` · MXFP4 | `ggml-org/gpt-oss-20b-GGUF` · MXFP4 | `openai/gpt-oss-20b` · MXFP4 |
| mid | Mistral Small 3.2 24B | `mistral-small3.2:24b` · Q4_K_M | `bartowski/mistralai_Mistral-Small-3.2-24B-Instruct-2506-GGUF` · Q4_K_M | `mistralai/Mistral-Small-3.2-24B-Instruct-2506` · bf16 |
| heavy | Qwen3.8 27B | `qwen3.8:27b` · Q4_K_M | `bartowski/Qwen3.8-27B-GGUF` · Q4_K_M | `Qwen/Qwen3.8-27B` · bf16 |
| heavy | DeepSeek-R1 70B | `deepseek-r1:70b` · Q4_K_M | `bartowski/DeepSeek-R1-Distill-Llama-70B-GGUF` · Q4_K_M | `deepseek-ai/DeepSeek-R1-Distill-Llama-70B` · bf16 |
| heavy | GPT-OSS 120B | `gpt-oss:120b` · MXFP4 | `ggml-org/gpt-oss-120b-GGUF` · MXFP4 | `openai/gpt-oss-120b` · MXFP4 |
| extreme | Qwen3 235B | `qwen3:235b` · Q4_K_M | `unsloth/Qwen3-235B-A22B-GGUF` · Q4_K_M | `Qwen/Qwen3-235B-A22B` · bf16 |

The model keeps the **same display name on every backend**, so `llmbench compare` lines the runs up. The weights are not byte-identical across backends (GGUF and Ollama are quantized, vLLM loads the original weights); `doctor` and `compare` warn about that. Models outside the catalog still work, with a warning that they cannot be compared across backends. The older llama.cpp-only models (Qwen3.5-9B, Gemma-4-12B-IT, GLM-4.7-Flash, Qwen3.5-122B-A10B, Mistral-Small-4-119B-2603, DeepSeek-V4-Flash-0731) stay selectable as "legacy" but are not part of the standard selection.

The Hugging Face repositories and GGUF file names were checked against the Hub (2026-11-04). A reference that is not checked is marked "(unverified)" in the menus. Re-check everything with `python scripts/verify_model_catalog.py` (needs network access).

## Model selection uses the terminal UI

During normal setup:

### Windows

```powershell
.\setup.bat
```

### Linux

```bash
bash setup.sh
```

llmbench opens an interactive model-selection screen with the shared catalog, the same list on every backend. The Extreme model is explicitly marked as:

```text
Qwen3 235B [EXTREME]
```

## What does "A" mean?

**A = All standard models** selects every catalog model except the Extreme one:

- Gemma 3 1B
- Granite 4.2 3B
- Qwen3 8B
- DeepSeek-R1 14B
- GPT-OSS 20B
- Mistral Small 3.2 24B
- Qwen3.8 27B
- DeepSeek-R1 70B
- GPT-OSS 120B

**Qwen3 235B is not downloaded automatically when A is selected.** Select it separately by its model number. This prevents accidental very large downloads.

## Why multiple families?

A hardware benchmark dominated by one model family can overweight architecture-specific optimizations. Raw measurements remain valid, but broad hardware conclusions become less representative. The catalog therefore contains Gemma, Granite, Qwen, DeepSeek, GPT-OSS and Mistral.

## Why is Extreme separate?

The Extreme model is substantially larger than the normal suite. It is useful for:

- very large RAM/hybrid tests
- unified-memory scenarios
- capacity and server stress testing

It should therefore be **selected deliberately** and never silently included by "All standard models."

## Saved selection

The terminal UI stores the selected models in:

```text
models/.llmbench-model-selection.json
```

The next run through `START_BENCHMARK.bat` or `START_BENCHMARK.sh` checks exactly that selection and completes missing downloads when required.

Older selections are migrated automatically (`Qwen3.5-35B-A3B` to `GLM-4.7-Flash`, `Qwen3.8-27B` to `Qwen3.8 27B`). Existing GGUF files are not deleted automatically.

## Advanced use

The underlying CLI remains available for direct use, but it is **not the normal user workflow**. Setup and regular benchmark runs are intended to use the terminal UI.
