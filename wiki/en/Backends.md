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

## Planned

- TGI
- Ollama

## Build identity

Backend and build information is stored in the result. Reference comparisons should use the same build where possible.
