# Manual release and CI reports

[Deutsch](release-automation.md) | [English](release-automation.en.md)

## Release vorbereiten

Unter **Actions → Manual release → Run workflow** immer `main` waehlen.
Mit `mode=prepare` entweder `version` (ohne `v`) oder `bump=patch/minor/major`
angeben. `dry_run=true` ist der Standard und zeigt die geplanten Release-Notizen
in der Run-Summary; weder Quelldateien noch Branches/Tags/Releases werden geschrieben.

Mit `dry_run=false` aktualisiert der Bot `VERSION`, `pyproject.toml` und
`llmbench/__init__.py`, verschiebt beide Unreleased-Abschnitte in die neue Version
und ergaenzt Commit-Titel seit dem naechsten erreichbaren stabilen Release-Tag.
Ohne Tag wird die gesamte Historie verwendet. Originaltitel werden nicht automatisch
uebersetzt. Der Bot prueft Tests, Ruff, mypy, Abhaengigkeiten und Paketbau und oeffnet
einen Draft-PR. Vorhandene Release-Branches werden niemals ueberschrieben.
Tests und Security werden fuer den Branch ausdruecklich gestartet.

Beide Changelogs redigieren, insbesondere doppelte Commit-Eintraege entfernen,
Uebersetzungen pruefen, PR bereitstellen, Checks pruefen und mergen.
Automatisch ausgeloeste PR-Checks koennen eine GitHub-Freigabe erfordern.
Die Repository-Einstellung muss GitHub Actions das Erstellen von PRs erlauben.

## Release veroeffentlichen

Den Workflow erneut auf `main` mit `mode=publish`, exakter `version`, `bump=none`
und zunaechst `dry_run=true` starten. Nach Pruefung mit `dry_run=false` ausfuehren.
Es muessen synchronisierte Versionsquellen und nichtleere Release-Abschnitte in
beiden Sprachen vorliegen. Alle Qualitaetspruefungen laufen erneut. Der Bot
verweigert das Taggen, wenn `main` waehrenddessen weitergelaufen ist.

Der Bot setzt den annotierten Tag `vX.Y.Z` und erstellt ein GitHub Release.
Ein vorhandener Tag wird nur akzeptiert, wenn er auf denselben Commit zeigt;
ein vorhandenes Release wird nicht ueberschrieben. Ein erneuter Lauf kann eine
unterbrochene Veroeffentlichung fortsetzen. Docker- und Test-Workflows werden
explizit auf dem Tag gestartet, da mit `GITHUB_TOKEN` gepushte Tags keine
Push-Workflows starten. Es wird kein zusaetzliches PAT benoetigt.
Das GitHub Release kann bereits sichtbar sein, waehrend Docker noch baut.
GHCR wird erst nach erfolgreichem Image-Scan und Release-Qualitaetsgate publiziert.
Docker-Dispatches auf Branches validieren nur; auf Tags publizieren sie zusaetzlich.

## Watcher und Berichte

Backend release watch erlaubt `backend=all/llama_cpp/vllm`. Beide Watcher bieten
`force`: Damit kann nach einem geschlossenen PR erneut vorgeschlagen werden;
offene und gemergte PRs bleiben gesperrt. Bestehende Kandidaten-Branches werden
wiederverwendet und nie erzwungen ueberschrieben.

Coverage, CodeQL, Trivy und Scorecard werden 14 Tage als Run-Artefakte gespeichert.
Der SBOM-Export des publizierten Images wird ueber den unveraenderlichen Digest
bezogen und 90 Tage gespeichert. Der Export enthaelt die plattformbezogenen
BuildKit-SBOM-Dokumente. Trivy bleibt ein HIGH/CRITICAL-Gate und liefert zusaetzlich
SARIF an Code Scanning; Fork-PRs speichern nur das Artefakt. CodeQL-Summaries
zaehlen alle SARIF-Ergebnisse nach SARIF-Level, nicht nur neue PR-Alerts.
Der bestehende Wiki-Sync mit DE/EN-Paritaetspruefung bleibt erhalten.
