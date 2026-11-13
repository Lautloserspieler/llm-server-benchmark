[Deutsch](DE-Home) | [English](EN-Home)

---

# LLM Server Benchmark Wiki

Willkommen im Benutzerhandbuch von **LLM Server Benchmark (llmbench)**.

llmbench misst nicht nur Tokens pro Sekunde, sondern speichert auch Testbedingungen wie Hardware, Treiber, Backend, Modell-Hash, Quantisierung, Konfiguration und Telemetrie. Dadurch lassen sich lokale LLM-Systeme reproduzierbar vergleichen.

## Schnellzugriff

- [Installation](DE-Installation)
- [Quick Start](DE-Quick-Start)
- [Modell-Suite](DE-Model-Suite)
- [Benchmark-Methodik](DE-Benchmark-Methodology)
- [Hardware-Telemetrie](DE-Hardware-Telemetry)
- [Benchmark-Profile](DE-Benchmark-Profiles)
- [Backends](DE-Backends)
- [Ergebnisse verstehen](DE-Understanding-Results)
- [Reports und Export](DE-Reports-and-Export)
- [Systeme vergleichen](DE-Comparing-Systems)
- [Troubleshooting](DE-Troubleshooting)
- [FAQ](DE-FAQ)
- [Entwicklung](DE-Development)
- [Roadmap](DE-Roadmap)

## Was llmbench misst

- Prompt Processing und Text Generation
- Long-Context-Leistung
- CPU-, GPU- und Hybrid-Profile
- TTFT, Concurrency und Systemdurchsatz
- Soak-, OOM-, Multi-Tenant- und Quantisierungstests
- CPU-, RAM-, GPU-, VRAM-, Temperatur- und Power-Telemetrie

## Backend-Status

| Backend | Status | Ausführung |
| --- | --- | --- |
| llama.cpp | unterstützt | nativ |
| vLLM | unterstützt | Docker |
| Ollama | unterstuetzt (1.6.5) | Docker |
| TGI | wird eingestellt; Adapter noch vorhanden, nicht validiert | Docker |
| SGLang | geplanter TGI-Ersatz; noch kein Adapter | Docker (geplant) |

Die [Qualifikationsnachweise](https://github.com/Lautloserspieler/llm-server-benchmark/blob/main/docs/validation/v1.7.0-qualification.md)
zeigen echte Hardwaretests und noch offene Release-Abnahmen.

## Grundprinzip

Ein einzelner Wert wie **84 tok/s** ist ohne Kontext nur begrenzt aussagekräftig. Ein belastbarer Vergleich braucht mindestens dasselbe Modell, dieselbe Quantisierung, möglichst denselben Backend-Build und dieselbe Benchmark-Konfiguration.

```bash
llmbench compare results/run-a results/run-b --strict
```
