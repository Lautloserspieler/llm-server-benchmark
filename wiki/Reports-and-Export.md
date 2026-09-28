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

Zusätzlich gibt es modell-/profilbezogene Rohdateien.

## report.html

Für die Sichtung im Browser. Enthält Hardware, Testbedingungen, Leistungswerte, Telemetrie, Warnungen und Diagramme.

## report.pdf

Portable Berichtsversion für Weitergabe und Archivierung.

## benchmarks.csv

Gut für:

- Excel
- pandas
- eigene Diagramme
- automatisierte Vergleiche

## summary.json

Maschinenlesbare zentrale Zusammenfassung mit Hardware, Konfiguration, Backend, Build-/Fingerprintdaten, Modellen, Profilen, Benchmarkresultaten, Stress-/Soak-Ergebnissen und Warnungen.

## raw_*.json

Rohdaten einzelner Tests inklusive detaillierter Telemetrie und Backendausgaben.

## ZIP-Export

Ergebnisordner können als Paket exportiert und auf einem anderen System ausgewertet werden.

Bei Support-/Analysefragen ist ein kompletter Export wesentlich hilfreicher als nur ein Screenshot der tok/s-Werte.
