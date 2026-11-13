[Deutsch](DE-Backends) | [English](EN-Backends)

---

# Backends

## llama.cpp

Referenzbackend mit:

- `llama-bench` für Kernmessungen
- `llama-server` für Endpoint-, Soak- und Stresstests

Stärken:

- breite GGUF-Unterstützung
- CPU/GPU/Hybrid
- reproduzierbare lokale Binaries
- gute Eignung für Hardware- und Quantisierungsvergleiche

## vLLM

vLLM läuft containerisiert und eignet sich besonders für OpenAI-kompatible Serving-Szenarien und hohe Parallelität.

vLLM- und llama.cpp-Werte sind nicht automatisch direkt vergleichbar, da Scheduler, Kernel, Caches und Serving-Strategien unterschiedlich sind.

## Ollama

Ollama wird seit 1.6.5 ueber Docker und die native `/api/generate`-API unterstuetzt.
CPU- und GPU-Profile sind implementiert. Die Hardwarequalifikation wird getrennt
im [v1.7.0-Protokoll](https://github.com/Lautloserspieler/llm-server-benchmark/blob/main/docs/validation/v1.7.0-qualification.md) verfolgt.

## TGI und SGLang

[Entscheidung #167](https://github.com/Lautloserspieler/llm-server-benchmark/issues/167)
stellt TGI einschliesslich Legacy-Wartung ein. Der nicht validierte Adapter ist
bis zur geplanten Entfernung in 1.8.0 noch vorhanden. SGLang-Beta ist fuer 1.8.0,
vollstaendige Integration/Stabilitaetsvalidierung fuer 1.9.0 geplant; noch ist kein
SGLang-Adapter verfuegbar.

## Build-Identität

Backend- und Buildinformationen werden im Ergebnis gespeichert. Für Referenzvergleiche sollte möglichst derselbe Build verwendet werden.
