# Modell-Suite

Die Standardsuite soll nicht nur verschiedene Größen, sondern auch mehrere Modellfamilien und Architekturen abdecken.

## Standard-Suite 2026

| Suite | Modell | Familie | Referenz-Quantisierung |
| --- | --- | --- | --- |
| small | Qwen3.5-9B | Qwen | Q4_K_M |
| mid | Gemma-4-12B-IT | Gemma | Q4_K_M |
| mid | Qwen3.8-27B | Qwen | Q4_K_M |
| mid | GLM-4.7-Flash | GLM / MoE | Q4_K_M |
| heavy | Qwen3.5-122B-A10B | Qwen / MoE | Q4_K_M |
| heavy | Mistral-Small-4-119B-2603 | Mistral / MoE | UD-Q4_K_M |
| extreme | DeepSeek-V4-Flash-0731 | DeepSeek | UD-Q4_K_XL |

## Warum mehrere Familien?

Ein Hardwarebenchmark mit fast ausschließlich einer Modellfamilie kann architekturspezifische Optimierungen übergewichten. Die Rohwerte wären weiterhin korrekt, aber ein daraus abgeleitetes allgemeines Hardwareurteil wäre weniger robust.

Deshalb enthält die Suite Qwen, Gemma, GLM, Mistral und optional DeepSeek.

## Warum Q4?

4-Bit-Quantisierungen sind für lokale Inferenz sehr relevant und erlauben eine breite Größenstaffelung.

## Suites

```bash
llmbench download --suite small
llmbench download --suite mid
llmbench download --suite heavy
llmbench download --suite all
llmbench download --suite extreme
```

`all` enthält **small + mid + heavy**, aber absichtlich **nicht extreme**.

## Extreme

DeepSeek V4 Flash ist separat, weil Download und Laufzeit deutlich größer sind. Der Extreme-Test soll bewusst gestartet werden.

## Gespeicherte Auswahl

```text
models/.llmbench-model-selection.json
```

Alte Auswahlen mit `Qwen3.5-35B-A3B` werden als Standardslot auf `GLM-4.7-Flash` migriert. Alte GGUF-Dateien werden nicht gelöscht.
