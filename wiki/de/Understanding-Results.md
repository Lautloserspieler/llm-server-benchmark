[Deutsch](DE-Understanding-Results) | [English](EN-Understanding-Results)

---

# Ergebnisse verstehen

## pp

`pp` steht für Prompt Processing. Beispiel:

```text
pp4096 = Verarbeitung eines Prompts mit ungefähr 4096 Tokens
```

Je höher, desto schneller wird vorhandener Kontext verarbeitet.

## tg

`tg` steht für Text Generation. Beispiel:

```text
tg128 = Generierung von 128 Tokens
```

## Durchschnitt und Streuung

Ein hoher Mittelwert mit sehr hoher Streuung ist weniger belastbar als ein leicht niedrigerer, stabiler Wert. Für Referenztests sind mehrere Wiederholungen wichtig.

## TTFT

Time to First Token:

- P50: typische Antwortlatenz
- P95: schlechtere, aber realistische Randfälle

## System TPS

Gesamtdurchsatz aller parallelen Requests. Mit mehr Parallelität kann System-TPS steigen, während der Durchsatz pro Nutzer sinkt und TTFT zunimmt.

## Statuswerte

- `ok`: vollständig erfolgreich
- `partial`: bereits abgeschlossene Teilmessungen sind gültig, eine spätere Stufe konnte aber nicht beendet werden
- `skipped_capacity`: erwartete Hardware-/Speichergrenze; kein allgemeiner Benchmarkfehler
- `skipped`: optionaler Stresstest ist nicht anwendbar, z. B. weil kein zweites Quant desselben Basismodells vorhanden ist
- `timeout`: Zeitlimit überschritten
- `failed`: tatsächlicher Test-/Backendfehler

### Teilweise Long-Context-Ergebnisse

Scheitert beispielsweise erst eine 262K-Kontextstufe, bleiben bereits vollständig gemessene 0K-, 8K-, 32K-, 65K- oder 131K-Stufen erhalten. Das gilt auch dann, wenn `llama-bench` erst durch das konfigurierte Zeitlimit beendet wird. Nur Kontextstufen mit vollständig abgeschlossener Prompt- **und** Generationsmessung werden übernommen; eine halb gemessene nächste Stufe wird verworfen. Der Bericht zeigt die gültigen Werte als `partial` und speichert zusätzlich die nicht erreichte Kontextstufe sowie den Grund (`timeout` oder Kapazitätsgrenze).

Der OOM-/Kapazitätstest verwendet für unveränderte Standardkonfigurationen jetzt eine Leiter bis **393.216 Tokens (384K)** und stoppt beim ersten echten Fehler. Eigene benutzerdefinierte `oom_contexts`-Listen werden nicht verändert.

## Effizienz

Tokens/s pro Watt sind sinnvoll, wenn die Leistungsaufnahme zuverlässig gemessen wurde.

## Long-Context-Penalty

```text
Penalty = 1 - (tok/s bei langem Kontext / tok/s bei leerem Kontext)
```
