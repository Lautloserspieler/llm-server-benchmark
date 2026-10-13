# Telemetrievertrag

[🇬🇧 English](telemetry.en.md) | [Übersicht](README.md)

## Zweck

Telemetrie beschreibt den Systemzustand parallel zu einem Workload. Sie ist task-unabhängig
und darf daher von Text-, Speech-, Image- und Enterprise-Workloads gemeinsam genutzt werden.

## Aktueller Stand

Heute existiert `TelemetryProvider` mit NVIDIA-, AMD- und Fallback-Pfaden sowie
`CompositeProvider` für mehrere Quellen. Bestehende Felder und Provider bleiben
kompatibel.

## Grundregeln

- Ein nicht verfügbares Feld ist `null`/nicht gemessen, nicht automatisch `0`.
- Quelle und Messumfang müssen nachvollziehbar sein.
- Komponentenenergie darf nur verglichen werden, wenn Scope und Komponentenabdeckung
  kompatibel sind.
- Rohsamples und aggregierte Werte müssen unterscheidbar bleiben.
- Telemetriefehler sollen einen Benchmark nur dann abbrechen, wenn die konkrete Messung als
  verpflichtend konfiguriert wurde.

## Gemeinsame Zielbereiche

Langfristig soll die gemeinsame Telemetrieschicht Werte aus folgenden Bereichen tragen
können:

```text
CPU utilization / temperature / package power
RAM usage
GPU utilization / VRAM / temperature / power
memory-bandwidth observations
disk I/O
network I/O
process ownership / foreign load
thermal/throttling indicators
```

Nicht jede Plattform muss jedes Feld liefern.

## Provenienz

Zu jedem abgeleiteten Effizienz- oder Telemetriewert muss nachvollziehbar bleiben:

- welcher Provider gemessen hat,
- welche Komponente gemessen wurde,
- welcher Zeitraum verwendet wurde,
- ob der Wert direkt beobachtet oder berechnet wurde.

Diese Metadaten sind Teil der Vergleichbarkeit und dürfen im Reporting nicht verloren
gehen.
