# GitHub-Issue-Labels

Deutsch | 🇬🇧 [English](ISSUE_LABELS.md)

**Verbindliche Konfiguration:** [`.github/issue-labels.json`](../.github/issue-labels.json).

Die Labels geben Mitwirkenden vier Informationen: **Was für eine Aufgabe ist das? Welcher Projektbereich ist betroffen? Wie dringend ist sie? Für welches Release ist sie vorgesehen?** Das allgemeine Label `enhancement` wird nur bei den verwalteten Roadmap-Issues entfernt. Historische und andere Issues bleiben unverändert.

## Label-Gruppen

| Präfix | Bedeutung | Farbfamilie |
| --- | --- | --- |
| `kind:` | Aufgabenart: tracking, feature, bug, validation, maintenance, refactor, documentation | Schiefergrau, Blau, Rot, Cyan, Grau, Violett, Türkis |
| `area:` | Bereich: backends, telemetry, benchmark, reporting, platform, multimodal, datasets | Verschiedene Modulfarben |
| `priority:` | Priorität: p0 (Release-Blocker), p1 (hoch), p2 (normal) | Rot, Orange, Gelb |
| `release:` | Zielversion: 1.7.0, 1.8.0, 1.9.0, 2.0.0 | Hellblau, Grün, Orange, Violett |

**Regel:** Technische Issues erhalten möglichst je ein `kind:`-, `area:`-, `release:`- und `priority:`-Label. Für modulübergreifende Aufgaben sind mehrere `area:`-Labels erlaubt. Übergeordnete Tracking-Issues benötigen normalerweise keine Priorität. Der Status einer Aufgabe wird über Issues, PRs und gegebenenfalls das Projektboard verwaltet, nicht über statische Label-Statusangaben.

## Zuordnung der Roadmap

- **v1.7.0:** #116 und #120–#124
- **v1.8.0:** #117 und #125–#128
- **v1.9.0:** #118 und #129–#132
- **v2.0.0:** #119 und #133–#139
- **Versionsübergreifende Übersicht:** #140 (`kind:tracking`)

Issue #71 und alle anderen älteren Issues werden durch diese Umstellung nicht verändert.

## Automatische Synchronisierung

Der Workflow [`sync-issue-labels.yml`](../.github/workflows/sync-issue-labels.yml) läuft nach Änderungen an der Label-Konfiguration auf `main` und kann bei Bedarf über GitHub Actions manuell gestartet werden. Mit der Option **dry-run** lassen sich Änderungen zunächst nur anzeigen.

Das Skript legt fehlende Labels an, aktualisiert Beschreibungen und Farben und aktualisiert ausschließlich die ausdrücklich in `issue_assignments` aufgeführten Issues. **Es löscht keine Labels aus dem Repository** und erhält nicht verwaltete Labels. Nur bei den verwalteten Issues wird das bisherige `enhancement`-Label entfernt.

Änderungen ohne Schreibzugriff testen:

```bash
GITHUB_TOKEN=... python scripts/sync_issue_labels.py --repo Lautloserspieler/llm-server-benchmark --dry-run
```

Änderungen mit einem entsprechend berechtigten GitHub-Token anwenden:

```bash
GITHUB_TOKEN=... python scripts/sync_issue_labels.py --repo Lautloserspieler/llm-server-benchmark
```

Token gehören niemals in Git-Commits, Issue-Texte oder Protokolle.

## Regeln für Mitwirkende

1. Auf #140 oder im passenden Release-Tracker beginnen.
2. Ein kleines technisches Issue auswählen und vor Arbeitsbeginn die geplante Umsetzung kommentieren.
3. `priority:p0` ausschließlich für Release-Blocker oder gravierende Korrektheitsprobleme verwenden.
4. `kind:validation` für Tests/Nachweise, `kind:bug` für Fehler, `kind:feature` nur für tatsächliche Funktionserweiterungen.
5. Dauerhafte Änderungen an Farben oder Kategorien über `.github/issue-labels.json` als PR vorschlagen.
6. Dokumentation, Benutzeroberfläche und Fehlermeldungen auf Deutsch und Englisch pflegen.
