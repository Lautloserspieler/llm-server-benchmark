[Deutsch](DE-FAQ) | [English](EN-FAQ)

---

# FAQ

## Why not benchmark only one model?

Different architectures stress hardware differently. A mixed suite produces more representative conclusions about general LLM inference performance.

## Why are multiple Qwen models still included?

Qwen is important in the local GGUF ecosystem and covers several size classes. The suite also includes Gemma, GLM, and Mistral, with DeepSeek available as an Extreme test.

## Why Q4_K_M?

4-bit quantization is a common local operating point balancing quality, memory use, and speed.

## Why is DeepSeek V4 not part of all?

The Extreme model is very large. A normal setup should not silently download well over 100 GiB.

## pp vs tg?

- `pp`: process existing prompt/context
- `tg`: generate new tokens

## Why do tok/s fall at large context sizes?

KV cache and attention cost grow, increasing both memory pressure and compute work.

## Is skipped_capacity an error?

No. It means an expected hardware or memory boundary was detected.

## Can I use custom models?

Yes. The standard suite is only the reproducible reference set.

## Short, Medium, or Long?

- Short: smoke testing
- Medium: practical comparison
- Long: reference/stability run
