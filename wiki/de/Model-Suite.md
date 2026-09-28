[Deutsch](DE-Model-Suite) | [English](EN-Model-Suite)

---

# Modell-Suite

Die Standardsuite deckt mehrere Größen, Modellfamilien und Architekturen ab.

| Klasse | Modell | Familie | Referenz-Quantisierung |
| --- | --- | --- | --- |
| small | Qwen3.5-9B | Qwen | Q4_K_M |
| mid | Gemma-4-12B-IT | Gemma | Q4_K_M |
| mid | Qwen3.8-27B | Qwen | Q4_K_M |
| mid | GLM-4.7-Flash | GLM / MoE | Q4_K_M |
| heavy | Qwen3.5-122B-A10B | Qwen / MoE | Q4_K_M |
| heavy | Mistral-Small-4-119B-2603 | Mistral / MoE | UD-Q4_K_M |
| extreme | DeepSeek-V4-Flash-0731 | DeepSeek | UD-Q4_K_XL |

## Modellauswahl erfolgt über die Terminal-UI

Beim normalen Setup:

### Windows

```powershell
.\setup.bat
```

### Linux

```bash
./setup.sh
```

öffnet llmbench eine interaktive Modellauswahl. Dort werden **alle sieben Referenzmodelle** angezeigt.

DeepSeek V4 Flash erscheint dabei ausdrücklich als:

```text
DeepSeek-V4-Flash-0731 [EXTREME]
```

Das Extreme-Modell kann wie jedes andere Modell über seine Nummer ausgewählt werden.

## Was bedeutet „A“?

Die Auswahl **A = Alle Standardmodelle** umfasst bewusst nur:

- Qwen3.5-9B
- Gemma-4-12B-IT
- Qwen3.8-27B
- GLM-4.7-Flash
- Qwen3.5-122B-A10B
- Mistral-Small-4-119B-2603

**DeepSeek-V4-Flash-0731 wird bei A nicht automatisch mitgeladen.**

Wer Extreme testen möchte, wählt DeepSeek zusätzlich über seine Modellnummer aus. Dadurch kann niemand versehentlich einen sehr großen Download starten.

## Warum mehrere Familien?

Ein Hardwarebenchmark mit fast ausschließlich einer Modellfamilie kann architekturspezifische Optimierungen übergewichten. Die Rohwerte bleiben korrekt, aber allgemeine Aussagen über die Hardware werden weniger robust.

Deshalb enthält die Suite Qwen, Gemma, GLM, Mistral und optional DeepSeek.

## Warum ist Extreme separat?

DeepSeek V4 Flash ist wesentlich größer als die normale Standardsuite. Es eignet sich für:

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

Alte Auswahlen mit `Qwen3.5-35B-A3B` werden automatisch auf `GLM-4.7-Flash` migriert. Alte GGUF-Dateien werden nicht automatisch gelöscht.

## Fortgeschrittene Nutzung

Die darunterliegende CLI kann weiterhin direkt verwendet werden, ist aber **nicht der normale Benutzerweg**. Für Installation und normale Benchmarkläufe sind Setup- und Start-Terminal-UI vorgesehen.
