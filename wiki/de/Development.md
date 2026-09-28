[Deutsch](DE-Development) | [English](EN-Development)

---

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

## Checks

```bash
ruff check .
mypy llmbench
pytest -q
```

## Zentrale Erweiterungspunkte

- `BenchmarkBackend`
- `TelemetryProvider`

Wichtige Module: `runner.py`, `hardware.py`, `telemetry.py`, `endpoint.py`, `config.py`, `compare.py`, `download.py`.

## Wiki-Quellen

Deutsch liegt unter `wiki/de/`, Englisch unter `wiki/en/`. Der Publish-Workflow veröffentlicht daraus flache `DE-*`- und `EN-*`-Seiten.
