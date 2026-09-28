[Deutsch](DE-Development) | [English](EN-Development)

---

# Development

The Wiki is the user guide. Canonical developer documentation remains versioned in the repository.

## Important files

- [CONTRIBUTING.md](https://github.com/Lautloserspieler/llm-server-benchmark/blob/main/CONTRIBUTING.md)
- [ROADMAP.md](https://github.com/Lautloserspieler/llm-server-benchmark/blob/main/ROADMAP.md)
- [CHANGELOG.md](https://github.com/Lautloserspieler/llm-server-benchmark/blob/main/CHANGELOG.md)
- [SECURITY.md](https://github.com/Lautloserspieler/llm-server-benchmark/blob/main/SECURITY.md)

## Development setup

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

## Main extension points

- `BenchmarkBackend`
- `TelemetryProvider`

Important modules include `runner.py`, `hardware.py`, `telemetry.py`, `endpoint.py`, `config.py`, `compare.py`, and `download.py`.

## Wiki sources

German sources live under `wiki/de/`, English sources under `wiki/en/`. The publish workflow flattens them into `DE-*` and `EN-*` Wiki pages.
