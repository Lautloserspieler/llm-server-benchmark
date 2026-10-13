# Architekturverträge

[🇬🇧 English](README.en.md)

Dieser Ordner beschreibt die stabilen Architekturbegriffe und Kompatibilitätsregeln für die
Weiterentwicklung von `llmbench`. Die Dokumente sind bewusst von konkreten Release-Terminen
getrennt: Sie definieren, **welche Verantwortung zu welcher Schicht gehört**, bevor neue
Backends und später multimodale Workloads implementiert werden.

## Phase 0: Zweck

Phase 0 verändert noch keine Benchmark-Messmethodik. Sie friert die Begriffe und Grenzen ein,
auf denen v1.7+ aufbauen:

- [Core](core.md) — Orchestrierung und Schichtgrenzen
- [Backends und Runtimes](backends.md) — wie Software ein Modell ausführt
- [Tasks und Workloads](workloads.md) — was ein Modell tut und wie es getestet wird
- [Telemetrie](telemetry.md) — gemeinsame Hardware-/Ressourcenbeobachtung
- [Ergebnisse](results.md) — Resultatmodell, Provenienz und Messwertregeln
- [Kompatibilität](compatibility.md) — Regeln für alte Konfigurationen und Resultate

## Zentrale Begriffe

| Begriff | Bedeutung | Beispiele |
| --- | --- | --- |
| **Task** | Was ein Modell fachlich tut | Textgenerierung, STT, TTS, OCR |
| **Runtime/Backend** | Welche Software das Modell ausführt | llama.cpp, vLLM, TGI, Ollama |
| **Workload** | Wie eine Task reproduzierbar belastet wird | Long Context, Concurrency, 10 h STT |
| **Metric** | Was innerhalb eines Workloads gemessen wird | Tokens/s, TTFT, WER, RTF |
| **Telemetry** | Hardware-/Systemzustand parallel zur Messung | VRAM, Power, Temperatur |
| **Result** | Normalisiertes Resultat inklusive Provenienz | Benchmarkwerte + Konfiguration + Hardware |

## Nicht-Ziele von Phase 0

Phase 0 führt **keine** neuen multimodalen Backends ein, ersetzt nicht den bestehenden
`BenchmarkBackend` und schreibt den Runner nicht neu. Bestehende Text-Benchmarks bleiben der
Referenzpfad. Neue Abstraktionen werden erst implementiert, wenn eine konkrete Phase sie
benötigt.
