[Deutsch](DE-Roadmap) | [English](EN-Roadmap)

---

# Roadmap

The canonical roadmap lives in the repository:

[Open ROADMAP.en.md](https://github.com/Lautloserspieler/llm-server-benchmark/blob/main/ROADMAP.en.md)

## Already available

- llama.cpp, vLLM and Ollama
- NVIDIA, AMD and Intel telemetry providers (hardware evidence varies)
- CPU/GPU/hybrid execution
- long context
- TTFT/concurrency
- soak, OOM, multi-tenant, quantization tests
- HTML/PDF/CSV/JSON
- strict comparability validation
- Windows/Linux/macOS launchers

## Larger next steps

- 1.7.0: finish qualification of active text backends and document remaining hardware gaps
- 1.8.0: remove TGI, introduce SGLang beta, add calibrated load/SLO measurement
- 1.9.0: adaptive capacity and engine comparisons; complete SGLang integration and stability validation
- 2.0.0: multimodal task/runtime execution and reports

TGI is being discontinued under [#167](https://github.com/Lautloserspieler/llm-server-benchmark/issues/167).
SGLang is planned and has no adapter yet. See the
[qualification record](https://github.com/Lautloserspieler/llm-server-benchmark/blob/main/docs/validation/v1.7.0-qualification.md)
for completed measurements and open acceptance items; green CI is not hardware qualification.

This Wiki page intentionally stays short; planning changes belong in `ROADMAP.md` first.
