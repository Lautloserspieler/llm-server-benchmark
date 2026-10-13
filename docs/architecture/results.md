# Ergebnisvertrag

[🇬🇧 English](results.en.md) | [Übersicht](README.md)

## Ziel

Ein Resultat ist mehr als eine Performancezahl. Es muss die Bedingungen enthalten, unter
denen diese Zahl entstanden ist.

Mindestens relevant sind:

- Schema-/llmbench-Version.
- Task und Workload.
- Runtime-/Backend-Identität.
- Modellidentität und Konfiguration.
- Hardware und Ausführungsumgebung.
- Benchmarkparameter.
- Performance- und Qualitätsmetriken.
- Telemetrie und Energie-Scope.
- Status, Warnungen und Fehler.
- Provenienz abgeleiteter Werte.

## Aktueller Stand

Der heutige Textpfad erzeugt intern weiterhin Resultatdaten mit bestehender Struktur und
schreibt über `encode_v3(...)` ein versioniertes Artefakt. Phase 0 ändert dieses Verhalten
nicht.

## Zukünftige Normalisierung

Neue Task-Typen sollen nicht durch beliebige neue Top-Level-Felder in `runner.py`
entstehen. Langfristig soll ein normalisiertes Modell mindestens unterscheiden:

```text
Run
  Hardware
  Runtime
  Model
  Workload[]
    Metrics
    Telemetry
    Artifacts
    Status
```

## Fehlende Werte

Fehlende, nicht unterstützte und fehlgeschlagene Messungen sind unterschiedliche Zustände.
Sie dürfen nicht in dieselbe numerische Darstellung kollabieren.

Beispiele:

```text
null / not_measured
unsupported
skipped
failed
timeout
success
```

## Vergleichbarkeit

`compare` darf nur Werte ranken, wenn Task, Workload, relevante Konfiguration und
Messumfang kompatibel sind. Ein STT-RTF darf niemals gegen Text-Tokens/s oder
Bild-Sekunden/Bild gerankt werden.

## Artefakte

Task-spezifische Dateien wie Audio, Bilder, Meshes oder Rohtraces gehören als referenzierte
Artefakte zum Workload-Resultat. Große Binärdaten sollen nicht ungeprüft in
`summary.json` eingebettet werden.
