# Backends

## llama.cpp

Der Referenzbackend.

Verwendet:

- `llama-bench` für Kernmessungen
- `llama-server` für Endpoint-, Soak- und Stresstests

Vorteile:

- breite GGUF-Unterstützung
- CPU/GPU/Hybrid
- reproduzierbare lokale Binaries
- gute Eignung für Quantisierungs- und Hardwaretests

## vLLM

vLLM wird containerisiert betrieben.

Geeignet für:

- OpenAI-kompatible Servertests
- Serving-Szenarien
- hohe Parallelität

vLLM- und llama.cpp-Werte sind nicht automatisch direkt vergleichbar. Unterschiedliche Backends besitzen unterschiedliche Scheduler, Kernel, Caches und Serving-Strategien.

## Geplante Backends

Laut Roadmap:

- TGI
- Ollama

## Backend-Build

llmbench speichert Backend-/Buildinformationen im Ergebnis. Für Referenzvergleiche sollte möglichst derselbe Build verwendet werden.

## Stress-Suite

Nicht jeder Stresspfad ist bereits für jeden Backendtyp gleich weit abstrahiert. Nicht unterstützte Tests sollten begründet übersprungen statt künstlich nachgebildet werden.
