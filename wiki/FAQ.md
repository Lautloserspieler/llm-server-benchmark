# FAQ

## Warum nicht einfach ein Modell benchmarken?

Weil verschiedene Architekturen Hardware unterschiedlich belasten. Eine gemischte Suite liefert robustere Aussagen über allgemeine LLM-Inferenzleistung.

## Warum sind noch mehrere Qwen-Modelle enthalten?

Qwen ist im lokalen GGUF-Ökosystem sehr relevant und deckt unterschiedliche Größen und Architekturen ab. Die Suite enthält zusätzlich Gemma, GLM und Mistral; DeepSeek ist als Extreme-Test verfügbar.

## Warum Q4_K_M?

4-Bit-Quantisierung ist ein verbreiteter lokaler Betriebspunkt zwischen Qualität, Speicherbedarf und Geschwindigkeit.

## Warum ist DeepSeek V4 nicht in all?

Weil das Extreme-Modell sehr groß ist. Ein normales Setup soll nicht ungefragt weit über 100 GiB laden.

## Was ist der Unterschied zwischen pp und tg?

- `pp`: vorhandenen Prompt/Kontext verarbeiten
- `tg`: neue Tokens generieren

## Warum sinken tok/s bei großem Kontext?

KV-Cache und Attention-Aufwand wachsen. Speicherbedarf und Rechenaufwand steigen.

## Warum ist 600 W nicht automatisch schneller als 450 W?

Nur wenn der Workload tatsächlich am Power-Limit hängt. Speicherbandbreite, Kernel, Parallelität und andere Engpässe können dominieren.

## Warum kann System-TPS bei mehr Nutzern steigen?

Mehr parallele Requests erlauben bessere Auslastung. Gleichzeitig sinkt meist der Durchsatz pro Nutzer und TTFT steigt.

## Ist skipped_capacity ein Fehler?

Nein. Es bedeutet, dass eine erwartete Hardware-/Speichergrenze erkannt wurde.

## Kann ich eigene Modelle verwenden?

Ja. Die Standardsuite dient als reproduzierbare Referenz; eigene GGUFs sind möglich.

## Short, Medium oder Long?

- Short: Funktioniert alles?
- Medium: brauchbarer Vergleich
- Long: Referenz-/Stabilitätslauf
