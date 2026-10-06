# Sicherheitsrichtlinie

🇩🇪 Deutsch | [🇬🇧 English](SECURITY.md)

## Unterstützte Versionen

Sicherheitskorrekturen werden auf den aktuellen `main`-Branch und die neueste veröffentlichte Version angewendet.

## Eine Schwachstelle melden

Bitte **kein öffentliches GitHub-Issue** für eine vermutete Sicherheitslücke erstellen.

Verwende nach Möglichkeit GitHubs Funktion **Private vulnerability reporting** im Bereich
**Security** des Repositories. Die Meldung sollte enthalten:

- betroffene Version oder Commit,
- Schritte zur Reproduktion,
- erwartetes und beobachtetes Verhalten,
- mögliche Auswirkungen,
- Logs oder Proof-of-Concept-Details ohne Secrets.

Bitte veröffentliche keine Exploit-Details, bevor eine Korrektur oder Gegenmaßnahme verfügbar ist.

## Geltungsbereich

Relevante Meldungen umfassen unter anderem:

- Command-/Argument-Injection,
- unsichere Archiv- oder Dateiverarbeitung,
- Offenlegung von Zugangsdaten oder Tokens,
- unsichere Download- oder Update-Pfade,
- unsicheres Docker-/Container-Verhalten,
- Abhängigkeitsschwachstellen mit praktischer Auswirkung auf llmbench,
- Fehler in Berichtserzeugung oder Parsing, die unbeabsichtigte Code-Ausführung ermöglichen.

Allgemeine Fehler und Feature-Wünsche sollten weiterhin über die normalen Issue-Templates gemeldet werden.
