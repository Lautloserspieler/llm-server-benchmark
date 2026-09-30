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
- `timeout`: Zeitlimit überschritten
- `failed`: tatsächlicher Test-/Backendfehler

### Teilweise Long-Context-Ergebnisse

Scheitert beispielsweise erst eine 262K-Kontextstufe, bleiben bereits vollständig gemessene 0K-, 8K-, 32K-, 65K- oder 131K-Stufen erhalten. Der Bericht zeigt diese Werte als `partial` und speichert zusätzlich die nicht erreichte Kontextstufe. Bei einer erkannten Speicher-/Kontextgrenze wird sie als Kapazitätsgrenze dokumentiert.

## Effizienz

Tokens/s pro Watt sind sinnvoll, wenn die Leistungsaufnahme zuverlässig gemessen wurde.

## Long-Context-Penalty

```text
Penalty = 1 - (tok/s bei langem Kontext / tok/s bei leerem Kontext)
```
