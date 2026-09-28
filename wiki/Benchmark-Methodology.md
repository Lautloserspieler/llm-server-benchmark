# Benchmark-Methodik

## Prompt Processing

Misst, wie schnell bereits vorhandene Eingabetokens verarbeitet werden. Relevant für lange Systemprompts, RAG-Kontext und Dokumente.

## Text Generation

Misst die Geschwindigkeit der neu erzeugten Tokens. Typische Tests verwenden feste Generationstiefen wie 128, 512 oder 1024 Tokens.

## Wiederholungen

Ein Referenzwert sollte nicht aus einem einzelnen Lauf bestehen. llmbench speichert Mittelwert und Streuung.

Wichtige Größen:

- Durchschnitt
- Standardabweichung
- Variationskoeffizient
- Ausreißer

## Long Context

Long-Context-Tests füllen den Kontext/KV-Cache vor der Messung. Dadurch wird sichtbar, wie stark Leistung und Speicherbedarf bei 8K, 32K, 65K oder mehr Kontext steigen bzw. fallen.

## TTFT

**Time to First Token** misst die Wartezeit bis zum ersten sichtbaren Token.

Wichtig sind insbesondere:

- P50
- P95

## Concurrency

Mehrere parallele Requests zeigen Server-Skalierung:

- Gesamtdurchsatz
- Durchsatz pro Request
- TTFT
- Erfolgsrate

## Soak-Test

Der Soak-Test belastet CPU- und GPU-Pfad über längere Zeit, um thermische Stabilität, Fehler und Leistungseinbruch über Zeit sichtbar zu machen.

## OOM / Capacity

Diese Tests suchen Speicher- und Kontextgrenzen. `skipped_capacity` ist kein Benchmarkfehler, sondern eine erkannte Kapazitätsgrenze.

## Multi-Tenant

Startet mehrere Server/Modelle gleichzeitig und misst, wie gut sich die Hardware Ressourcen teilt.

## Vergleichbarkeit

Für belastbare Vergleiche sollten Modell, Quantisierung, Backend, Build, Profile und relevante Konfiguration übereinstimmen.
