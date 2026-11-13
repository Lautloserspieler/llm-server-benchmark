[Deutsch](DE-Roadmap) | [English](EN-Roadmap)

---

# Roadmap

Die kanonische Roadmap liegt im Repository:

[ROADMAP.md öffnen](https://github.com/Lautloserspieler/llm-server-benchmark/blob/main/ROADMAP.md)

## Bereits vorhanden

- llama.cpp, vLLM und Ollama
- NVIDIA-, AMD- und Intel-Telemetrieprovider (Hardware-Nachweise unterscheiden sich)
- CPU/GPU/Hybrid
- Long Context
- TTFT/Concurrency
- Soak, OOM, Multi-Tenant, Quantisierung
- HTML/PDF/CSV/JSON
- strikte Vergleichbarkeitsprüfung
- Windows/Linux/macOS-Launcher

## Nächste größere Themen

- 1.7.0: aktive Textbackends qualifizieren und verbleibende Hardwareluecken dokumentieren
- 1.8.0: TGI entfernen, SGLang-Beta einfuehren, kalibrierte Last-/SLO-Messungen ergaenzen
- 1.9.0: adaptive Kapazitaet und Engine-Vergleiche; SGLang-Integration und Stabilitaetsvalidierung vervollstaendigen
- 2.0.0: multimodale Task-/Runtime-Ausfuehrung und Reports

TGI wird gemaess [#167](https://github.com/Lautloserspieler/llm-server-benchmark/issues/167) eingestellt.
SGLang ist geplant und hat noch keinen Adapter. Das
[Qualifikationsprotokoll](https://github.com/Lautloserspieler/llm-server-benchmark/blob/main/docs/validation/v1.7.0-qualification.md)
enthaelt vorhandene Messungen und offene Abnahmen; gruene CI ist keine Hardwarequalifikation.

Diese Wiki-Seite bleibt bewusst kurz; Planänderungen gehören zuerst in `ROADMAP.md`.
