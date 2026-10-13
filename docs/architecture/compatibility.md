# Kompatibilitätsvertrag

[🇬🇧 English](compatibility.en.md) | [Übersicht](README.md)

## Grundsatz

Neue Architekturphasen dürfen bestehende reproduzierbare Text-Benchmarks nicht unnötig
ungültig machen. Migrationen müssen explizit, testbar und dokumentiert sein.

## Konfiguration

- Fehlt ein neuer optionaler Schlüssel, gilt ein dokumentierter Standard.
- Bestehende `tools.backend`-Konfigurationen für llama.cpp/vLLM bleiben gültig.
- Ein neues Pflichtfeld erfordert eine klare Migrationsstrategie.
- Unbekannte oder nicht unterstützte Werte sollen verständlich validiert werden.

## Resultate

Bestehende veröffentlichte Resultate sollen weiterhin lesbar bleiben, soweit die Daten
ausreichen. Ein zukünftiger Loader soll alte Schema-Versionen in ein gemeinsames internes
Modell überführen, statt alte Dateien stillschweigend umzuschreiben.

## Vergleich

Alte und neue Resultate dürfen nur dann direkt verglichen werden, wenn die für den
Workload relevanten Messbedingungen nachweislich kompatibel sind. Fehlende historische
Metadaten führen zu `unknown/not comparable`, nicht zu erfundener Gleichheit.

## API-/Abstraktionsmigration

Eine neue Abstraktion ersetzt eine bestehende erst, wenn:

1. alle heutigen Text-Backends abgedeckt sind,
2. Regressionstests für bestehendes Verhalten vorhanden sind,
3. CLI und Reports weiterhin funktionieren,
4. alte Konfigurationen getestet sind,
5. Cleanup-/Fehlerpfade getestet sind.

## Kein Big-Bang-Rewrite

Multimodal wird schrittweise eingeführt. Bestehender Code darf zunächst als Adapter oder
Kompatibilitätsschicht weiterleben. Ein vollständiges Umschreiben des funktionierenden
Textpfads ist kein Ziel.

## Deprecation

Wenn später öffentliche CLI-Optionen oder Konfigurationsfelder entfallen müssen, soll eine
Deprecation mindestens enthalten:

- Hinweis auf Ersatz.
- nachvollziehbare Warnung.
- dokumentierte Übergangsfrist bzw. Zielversion.
- Tests für den Migrationspfad.
