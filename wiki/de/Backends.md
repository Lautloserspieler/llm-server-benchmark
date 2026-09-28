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

## Geplant

- TGI
- Ollama

## Build-Identität

Backend- und Buildinformationen werden im Ergebnis gespeichert. Für Referenzvergleiche sollte möglichst derselbe Build verwendet werden.
