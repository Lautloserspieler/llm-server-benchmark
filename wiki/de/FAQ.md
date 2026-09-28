[Deutsch](DE-FAQ) | [English](EN-FAQ)

---

# FAQ

## Warum nicht nur ein Modell?

Verschiedene Architekturen belasten Hardware unterschiedlich. Eine gemischte Suite liefert robustere Aussagen über allgemeine LLM-Inferenzleistung.

## Warum sind noch mehrere Qwen-Modelle enthalten?

Qwen ist im lokalen GGUF-Ökosystem relevant und deckt unterschiedliche Größen ab. Die Suite enthält zusätzlich Gemma, GLM und Mistral; DeepSeek ist als Extreme-Test verfügbar.

## Warum Q4_K_M?

4-Bit-Quantisierung ist ein verbreiteter lokaler Betriebspunkt zwischen Qualität, Speicherbedarf und Geschwindigkeit.

## Warum ist DeepSeek V4 nicht in all?

Weil das Extreme-Modell sehr groß ist. Ein normales Setup soll nicht ungefragt weit über 100 GiB laden.

## pp vs tg?

- `pp`: vorhandenen Prompt/Kontext verarbeiten
- `tg`: neue Tokens generieren

## Warum sinken tok/s bei großem Kontext?

KV-Cache und Attention-Aufwand wachsen. Speicherbedarf und Rechenaufwand steigen.

## Ist skipped_capacity ein Fehler?

Nein. Es bedeutet, dass eine erwartete Hardware-/Speichergrenze erkannt wurde.

## Kann ich eigene Modelle verwenden?

Ja. Die Standardsuite dient als reproduzierbare Referenz.

## Short, Medium oder Long?

- Short: Smoke-Test
- Medium: brauchbarer Vergleich
- Long: Referenz-/Stabilitätslauf
