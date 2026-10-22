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

## Task-/Workload-/Dataset-Felder (additiv in Schema v3)

Entscheidung: **kein v4**, sondern optionale, additive Felder in `schema_version: 3`.
Begründung: Die neuen Angaben ändern keine bestehende Feldbedeutung; ein Version-Bump würde
alle alten Leser (`validate_summary` lehnt `> 3` ab) ohne Not aussperren und eine
Migration erzwingen. Ein v4 ist erst nötig, wenn bestehende Felder umgedeutet oder
Pflichtfelder eingeführt werden (z. B. beim normalisierten `Run/Workload[]`-Modell).

| Feld | Ort | Regel |
| --- | --- | --- |
| `task` | Top-Level | optional; wenn vorhanden, eine bekannte `TaskId` |
| `workload` | je `benchmarks.<kind>` | optional; Form `<gruppe>.<name>`; unbekannte, aber wohlgeformte IDs bleiben lesbar (Vorwärtskompatibilität) |
| `dataset` | Top-Level | optional; Objekt mit `id`, `version`, `sha256` (64 Hex), optional `selection` |

Fehlen die Felder (alle bisherigen Resultate), ist das **nicht** fehlerhaft und wird nicht
in die Datei zurückgeschrieben. Der Textpfad (`runner.py`, `encode_v3`) schreibt sie
vorerst nicht; `llmbench.tasks.infer_task_view()` liefert für alte Resultate eine
als `task_inferred: true` markierte Sicht (Task `text_generation`, Workload aus der
Benchmark-Art). Fehlende Messwerte bleiben `null` mit `status`/`reason`, nie `0`.

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
