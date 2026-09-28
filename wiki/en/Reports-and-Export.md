[Deutsch](DE-Reports-and-Export) | [English](EN-Reports-and-Export)

---

# Reports and Export

## Result directory

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

Model- and profile-specific raw files are stored alongside these outputs.

## report.html

Browser-oriented report containing hardware, test conditions, performance results, telemetry, warnings, and charts.

## report.pdf

Portable report for sharing and archiving.

## benchmarks.csv

Useful for Excel, pandas, custom charts, and automated analysis.

## summary.json

Machine-readable summary containing hardware, configuration, backend, build/fingerprint data, models, profiles, benchmark results, and stress/soak results.

## raw_*.json

Per-test raw data including telemetry and backend output.

## ZIP export

Complete result directories can be packaged and shared. For debugging or analysis, a complete export is much more useful than a screenshot of token rates.
