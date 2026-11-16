[Deutsch](DE-Model-Suite) | [English](EN-Model-Suite)

---

# Modell-Suite

**Auf allen Backends gibt es dieselben Modelle** (llama.cpp, Ollama, vLLM, TGI). Ergebnisse verschiedener Backends sind nur vergleichbar, wenn dasselbe Modell gemessen wurde; deshalb gibt es einen gemeinsamen Katalog. Jedes Modell hat die zum Backend passende Referenz:

| Klasse | Modell | Ollama | llama.cpp (GGUF) | vLLM / TGI (Hugging Face) |
| --- | --- | --- | --- | --- |
| small | Gemma 3 1B | `gemma3:1b` · Q4_K_M | `ggml-org/gemma-3-1b-it-GGUF` · Q4_K_M | `google/gemma-3-1b-it` · bf16 |
| small | Granite 4.2 3B | `granite4.2:3b` · Q4_K_M | `ibm-granite/granite-4.2-3b-GGUF` · Q4_K_M | `ibm-granite/granite-4.2-3b` · bf16 |
| small | Qwen3 8B | `qwen3:8b` · Q4_K_M | `Qwen/Qwen3-8B-GGUF` · Q4_K_M | `Qwen/Qwen3-8B` · bf16 |
| mid | DeepSeek-R1 14B | `deepseek-r1:14b` · Q4_K_M | `bartowski/DeepSeek-R1-Distill-Qwen-14B-GGUF` · Q4_K_M | `deepseek-ai/DeepSeek-R1-Distill-Qwen-14B` · bf16 |
| mid | GPT-OSS 20B | `gpt-oss:20b` · MXFP4 | `ggml-org/gpt-oss-20b-GGUF` · MXFP4 | `openai/gpt-oss-20b` · MXFP4 |
| mid | Mistral Small 3.2 24B | `mistral-small3.2:24b` · Q4_K_M | `bartowski/mistralai_Mistral-Small-3.2-24B-Instruct-2506-GGUF` · Q4_K_M | `mistralai/Mistral-Small-3.2-24B-Instruct-2506` · bf16 |
| heavy | Qwen3.8 27B | `qwen3.8:27b` · Q4_K_M | `bartowski/Qwen3.8-27B-GGUF` · Q4_K_M | `Qwen/Qwen3.8-27B` · bf16 |
| heavy | DeepSeek-R1 70B | `deepseek-r1:70b` · Q4_K_M | `bartowski/DeepSeek-R1-Distill-Llama-70B-GGUF` · Q4_K_M | `deepseek-ai/DeepSeek-R1-Distill-Llama-70B` · bf16 |
| heavy | GPT-OSS 120B | `gpt-oss:120b` · MXFP4 | `ggml-org/gpt-oss-120b-GGUF` · MXFP4 | `openai/gpt-oss-120b` · MXFP4 |
| extreme | Qwen3 235B | `qwen3:235b` · Q4_K_M | `unsloth/Qwen3-235B-A22B-GGUF` · Q4_K_M | `Qwen/Qwen3-235B-A22B` · bf16 |

Das Modell trägt auf **jedem Backend denselben Anzeigenamen**, damit `llmbench compare` die Läufe zuordnen kann. Die Gewichte sind zwischen den Backends nicht byte-identisch (GGUF und Ollama sind quantisiert, vLLM lädt die Originalgewichte); `doctor` und `compare` warnen davor. Modelle außerhalb des Katalogs funktionieren weiter, mit dem Hinweis, dass sie sich nicht backendübergreifend vergleichen lassen. Die älteren reinen llama.cpp-Modelle (Qwen3.5-9B, Gemma-4-12B-IT, GLM-4.7-Flash, Qwen3.5-122B-A10B, Mistral-Small-4-119B-2603, DeepSeek-V4-Flash-0731) bleiben als „legacy“ wählbar, gehören aber nicht zur Standardauswahl.

Die Hugging-Face-Repositories und GGUF-Dateinamen wurden gegen den Hub geprüft (04.11.2026). Eine ungeprüfte Referenz erscheint in den Menüs als „(ungeprüft)“. Alles lässt sich mit `python scripts/verify_model_catalog.py` erneut prüfen (braucht Netzwerkzugriff).

## Modellauswahl erfolgt über die Terminal-UI

Beim normalen Setup:

### Windows

```powershell
.\setup.bat
```

### Linux

```bash
bash setup.sh
```

öffnet llmbench eine interaktive Modellauswahl mit dem gemeinsamen Katalog, auf jedem Backend dieselbe Liste. Das Extreme-Modell erscheint ausdrücklich als:

```text
Qwen3 235B [EXTREME]
```

## Was bedeutet „A“?

Die Auswahl **A = Alle Standardmodelle** umfasst alle Katalogmodelle außer dem Extreme-Modell:

- Gemma 3 1B
- Granite 4.2 3B
- Qwen3 8B
- DeepSeek-R1 14B
- GPT-OSS 20B
- Mistral Small 3.2 24B
- Qwen3.8 27B
- DeepSeek-R1 70B
- GPT-OSS 120B

**Qwen3 235B wird bei A nicht automatisch mitgeladen.** Wer Extreme testen möchte, wählt es zusätzlich über seine Modellnummer aus. Dadurch kann niemand versehentlich einen sehr großen Download starten.

## Warum mehrere Familien?

Ein Hardwarebenchmark mit fast ausschließlich einer Modellfamilie kann architekturspezifische Optimierungen übergewichten. Die Rohwerte bleiben korrekt, aber allgemeine Aussagen über die Hardware werden weniger robust. Deshalb enthält der Katalog Gemma, Granite, Qwen, DeepSeek, GPT-OSS und Mistral.

## Warum ist Extreme separat?

Das Extreme-Modell ist wesentlich größer als die normale Standardsuite. Es eignet sich für:

- sehr große RAM-/Hybrid-Tests
- Unified-Memory-Szenarien
- Kapazitäts- und Server-Stresstests

Es soll deshalb **bewusst ausgewählt** und niemals still über „Alle Standardmodelle“ heruntergeladen werden.

## Gespeicherte Auswahl

Die Terminal-UI speichert die Auswahl in:

```text
models/.llmbench-model-selection.json
```

Beim nächsten Start über `START_BENCHMARK.bat` oder `START_BENCHMARK.sh` wird genau diese Auswahl geprüft und bei Bedarf vervollständigt.

Alte Auswahlen werden automatisch migriert (`Qwen3.5-35B-A3B` auf `GLM-4.7-Flash`, `Qwen3.8-27B` auf `Qwen3.8 27B`). Alte GGUF-Dateien werden nicht automatisch gelöscht.

## Fortgeschrittene Nutzung

Die darunterliegende CLI kann weiterhin direkt verwendet werden, ist aber **nicht der normale Benutzerweg**. Für Installation und normale Benchmarkläufe sind Setup- und Start-Terminal-UI vorgesehen.
