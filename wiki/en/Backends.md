[Deutsch](DE-Backends) | [English](EN-Backends)

---

# Backends

## llama.cpp

The reference backend uses:

- `llama-bench` for core measurements
- `llama-server` for endpoint, soak, and stress tests

Strengths:

- broad GGUF support
- CPU/GPU/hybrid execution
- reproducible local binaries
- well suited to hardware and quantization comparisons

## vLLM

vLLM runs in containers and is especially useful for OpenAI-compatible serving scenarios and high concurrency.

vLLM and llama.cpp results are not automatically directly comparable because schedulers, kernels, caches, and serving strategies differ.

## Ollama

Ollama is supported since 1.6.5 through Docker and its native `/api/generate` API.
CPU and GPU profiles are implemented. Hardware qualification is tracked separately
in the [v1.7.0 record](https://github.com/Lautloserspieler/llm-server-benchmark/blob/main/docs/validation/v1.7.0-qualification.md).

## TGI and SGLang

[Decision #167](https://github.com/Lautloserspieler/llm-server-benchmark/issues/167)
discontinues TGI, including legacy maintenance. Its unvalidated adapter is still
present pending removal, planned for 1.8.0. SGLang beta is planned for 1.8.0 and
full integration/stability validation for 1.9.0; no SGLang adapter is available yet.

## Build identity

Backend and build information is stored in the result. Reference comparisons should use the same build where possible.
