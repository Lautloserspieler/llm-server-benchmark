# LLM Server Benchmark Wiki

Willkommen im Benutzerhandbuch von **LLM Server Benchmark (llmbench)**.

llmbench misst nicht nur Tokens pro Sekunde, sondern speichert auch die Testbedingungen: Hardware, Treiber, Backend, Modell-Hash, Quantisierung, Konfiguration, Telemetrie und Laufzeitbedingungen. Dadurch lassen sich lokale LLM-Systeme reproduzierbar vergleichen.

## Schnellzugriff

- [Installation](Installation)
- [Quick Start](Quick-Start)
- [Modell-Suite](Model-Suite)
- [Benchmark-Methodik](Benchmark-Methodology)
- [Hardware-Telemetrie](Hardware-Telemetry)
- [Benchmark-Profile](Benchmark-Profiles)
- [Backends](Backends)
- [Ergebnisse verstehen](Understanding-Results)
- [Reports und Export](Reports-and-Export)
- [Systeme vergleichen](Comparing-Systems)
- [Troubleshooting](Troubleshooting)
- [FAQ](FAQ)
- [Entwicklung](Development)
- [Roadmap](Roadmap)

## Was llmbench misst

### Kernleistung
- Prompt Processing / Input Tokens pro Sekunde
- Text Generation / Output Tokens pro Sekunde
- Long-Context-Leistung
- CPU-, GPU- und Hybrid-Profile
- Wiederholungen und Streuung

### Serverbetrieb
- TTFT (Time to First Token)
- Systemdurchsatz
- Tokens/s pro Request
- Concurrency
- Erfolgsrate

### Stress und Kapazität
- Soak-/Dauerlasttests
- Multi-Tenant-Tests
- OOM-/Kontextgrenzen
- Quantisierungsvergleich
- GPU-Overload/Unified-Memory-Tests

### Telemetrie
- CPU-Auslastung
- RAM-Auslastung
- GPU-Auslastung
- VRAM
- GPU-Temperatur
- GPU-Leistungsaufnahme
- Power-Limits
- fremde GPU-Prozesse

## Unterstützte Backends

| Backend | Status | Ausführung |
| --- | --- | --- |
| llama.cpp | unterstützt | nativ |
| vLLM | unterstützt | Docker |
| TGI | geplant | Docker |
| Ollama | geplant | Docker |

## Grundprinzip

Ein einzelner Wert wie **84 tok/s** ist ohne Kontext nur begrenzt aussagekräftig. Ein belastbarer Vergleich braucht mindestens dasselbe Modell, dieselbe Quantisierung, möglichst denselben Backend-Build und dieselbe Benchmark-Konfiguration.

Für strikte Vergleiche:

```bash
llmbench compare results/run-a results/run-b --strict
```

Die README bleibt der schnelle Einstieg. Diese Wiki ist das ausführliche Benutzerhandbuch. Entwicklerdetails bleiben versioniert in `CONTRIBUTING.md` und `ROADMAP.md`.
