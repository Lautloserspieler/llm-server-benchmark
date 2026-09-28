# Ergebnisse verstehen

## pp

`pp` steht für Prompt Processing.

Beispiel:

```text
pp4096 = Verarbeitung eines Prompts mit ungefähr 4096 Tokens
```

Je höher, desto schneller wird vorhandener Kontext verarbeitet.

## tg

`tg` steht für Text Generation.

Beispiel:

```text
tg128 = Generierung von 128 Tokens
```

## Durchschnitt und Standardabweichung

Ein hoher Mittelwert mit sehr hoher Streuung ist weniger belastbar als ein leicht niedrigerer, aber stabiler Wert. Für Referenztests sind mehrere Wiederholungen wichtig.

## TTFT

Time to First Token:

- P50: typische Antwortlatenz
- P95: schlechtere, aber realistische Randfälle

## System TPS

Gesamtdurchsatz aller parallelen Requests.

Ein Server kann bei 32 parallelen Nutzern deutlich mehr System-TPS liefern als bei einem Nutzer, während der Durchsatz pro Nutzer gleichzeitig sinkt.

## Tokens/s pro Request

Wichtig für die Nutzererfahrung unter Concurrency.

## Statuswerte

### ok
Test erfolgreich.

### skipped_capacity
Die Hardware-/Speicherkapazität reicht für den geplanten Pfad nicht oder ein absichtlich übergroßer Overload-Test ist an der erwarteten Kapazitätsgrenze gescheitert.

### timeout
Der Test hat das konfigurierte Zeitlimit überschritten.

### failed
Tatsächlicher Test-/Backendfehler.

## Effizienz

Tokens/s pro Watt sind nützlich, wenn die Leistungsaufnahme zuverlässig gemessen wurde. Ein höheres Power-Limit kann den Durchsatz erhöhen und gleichzeitig die Effizienz verschlechtern.

## Long-Context-Penalty

```text
Penalty = 1 - (tok/s bei langem Kontext / tok/s bei leerem Kontext)
```
