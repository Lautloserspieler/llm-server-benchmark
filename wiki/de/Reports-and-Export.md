[Deutsch](DE-Reports-and-Export) | [English](EN-Reports-and-Export)

---

# Reports und Export

## Ergebnisordner

```text
results/
  SERVER_YYYYMMDD-HHMMSSZ/
    hardware.json
    summary.json
    summary.partial.json
    benchmarks.csv
    report.html
    report.pdf
```

Zusätzlich gibt es modell- und profilbezogene Rohdateien.

## report.html

Für die Sichtung im Browser mit Hardware, Testbedingungen, Leistungswerten, Telemetrie, Warnungen und Diagrammen.

## report.pdf

Portable Berichtsversion für Weitergabe und Archivierung.

## benchmarks.csv

Gut für Excel, pandas, eigene Diagramme und automatisierte Auswertungen.

## summary.json

Maschinenlesbare Zusammenfassung mit Hardware, Konfiguration, Backend, Build-/Fingerprintdaten, Modellen, Profilen, Benchmarkresultaten und Stress-/Soak-Ergebnissen.

## raw_*.json

Rohdaten einzelner Tests inklusive Telemetrie und Backendausgaben.

## ZIP-Export

Komplette Ergebnisordner lassen sich als Paket weitergeben. Für Analyse und Support ist ein vollständiger Export wesentlich hilfreicher als nur ein Screenshot.
