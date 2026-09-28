[Deutsch](DE-Benchmark-Methodology) | [English](EN-Benchmark-Methodology)

---

# Benchmark-Methodik

## Prompt Processing

Misst, wie schnell vorhandene Eingabetokens verarbeitet werden. Relevant für Systemprompts, RAG und lange Dokumente.

## Text Generation

Misst die Geschwindigkeit neu erzeugter Tokens. Typische Generationstiefen sind 128, 512 oder 1024 Tokens.

## Wiederholungen

Ein Referenzwert sollte nicht aus einem Einzelrun bestehen. llmbench speichert Mittelwert und Streuung.

## Long Context

Long-Context-Tests füllen Kontext und KV-Cache vor der Messung. Dadurch wird sichtbar, wie Performance und Speicherbedarf bei 8K, 32K, 65K oder mehr Kontext reagieren.

## TTFT

**Time to First Token** misst die Wartezeit bis zum ersten sichtbaren Token. Wichtig sind besonders P50 und P95.

## Concurrency

Mehrere parallele Requests zeigen:

- Gesamtdurchsatz
- Durchsatz pro Request
- TTFT
- Erfolgsrate

## Soak

Der Soak-Test belastet CPU- und GPU-Pfad länger, um thermische Stabilität, Fehler und Leistungseinbruch über Zeit sichtbar zu machen.

## OOM / Capacity

`skipped_capacity` bedeutet eine erkannte Kapazitätsgrenze, nicht automatisch einen Benchmarkfehler.

## Multi-Tenant

Mehrere Server/Modelle laufen gleichzeitig, um Ressourcenaufteilung zu messen.

## Vergleichbarkeit

Modell, Quantisierung, Backend, Build, Profile und relevante Konfiguration sollten übereinstimmen.
