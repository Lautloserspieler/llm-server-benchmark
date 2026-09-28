# Entwicklung

Die Wiki ist das Benutzerhandbuch. Die kanonische Entwicklerdokumentation bleibt im Repository.

## Wichtige Dateien

- [CONTRIBUTING.md](https://github.com/Lautloserspieler/llm-server-benchmark/blob/main/CONTRIBUTING.md)
- [ROADMAP.md](https://github.com/Lautloserspieler/llm-server-benchmark/blob/main/ROADMAP.md)
- [CHANGELOG.md](https://github.com/Lautloserspieler/llm-server-benchmark/blob/main/CHANGELOG.md)
- [SECURITY.md](https://github.com/Lautloserspieler/llm-server-benchmark/blob/main/SECURITY.md)

## Entwicklungssetup

```bash
git clone https://github.com/Lautloserspieler/llm-server-benchmark.git
cd llm-server-benchmark
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Lokale Checks

```bash
ruff check .
mypy llmbench
pytest -q
```

## Architektur

Zentrale Erweiterungspunkte:

- `BenchmarkBackend`
- `TelemetryProvider`

Wichtige Module:

- `runner.py`: Orchestrierung
- `hardware.py`: Hardware-Erkennung
- `telemetry.py`: Live-Telemetrie
- `endpoint.py`: Serverlast/TTFT
- `config.py`: Konfigurationsschema
- `compare.py`: Vergleichbarkeit
- `download.py`: Standardmodell-Katalog

## Pull Requests

Neue Funktionen sollten enthalten:

- Tests
- Changelog-Eintrag
- Dokumentation, wenn Verhalten oder CLI betroffen ist
- keine stillen Änderungen an der Vergleichssemantik

## Wiki-Quellen

Die Wiki-Seiten liegen versioniert unter `wiki/` im Hauptrepository. Änderungen werden nach Merge automatisch in die GitHub-Wiki synchronisiert.
