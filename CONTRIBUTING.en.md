# Contributing to llmbench

[🇩🇪 Deutsch](CONTRIBUTING.md) | 🇬🇧 English

Thank you for your interest in contributing to `llmbench`. This document describes the architecture,
development setup, code conventions, and pull-request workflow.

## Project purpose

`llmbench` is a Python CLI tool for **reproducible** benchmarking of local LLM-server inference.
Instead of recording only a tokens/s number, it captures the complete environment
(GPU, driver, backend build, model hashes, benchmark configuration, power state) so that
two systems can be compared under demonstrably equivalent conditions.

Despite the generic name "LLM **Server** Benchmark", the project was originally built around
**llama.cpp** and **NVIDIA/NVML**. The architecture is intentionally extensible; see
[ROADMAP.en.md](ROADMAP.en.md) for the current backend and telemetry roadmap. Both areas use
explicit extension points so new backends and telemetry sources can be added without
rewriting the core.

## Architecture overview

Two abstract base classes provide the main extension points:

| Abstraction | File | Purpose |
| --- | --- | --- |
| `BenchmarkBackend` | `llmbench/backends/base.py` | Encapsulates *how* an inference server is started, benchmarked, and stopped |
| `TelemetryProvider` | `llmbench/telemetry.py` | Encapsulates *where* GPU utilization/VRAM/temperature/power data comes from |

Important modules include:

- `runner.py` — orchestrates a complete run (profiles, models, stress suites)
- `hardware.py` — one-time hardware detection (CPU/GPU/driver), independent of the continuous sampling in `telemetry.py`
- `endpoint.py` — HTTP load testing against a running server (TTFT, TPS, concurrency)
- `config.py` — Pydantic configuration model including `FINGERPRINT_KEYS` for comparability
- `compare.py` — comparison of two results, including `--strict` consistency checks
- `i18n.py` / `locales/en.json` — translation layer (see "Language & i18n" below)

## Development setup

```bash
git clone https://github.com/Lautloserspieler/llm-server-benchmark.git
cd llm-server-benchmark
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Run tests and the linter before every commit/PR:

```bash
pytest -q
ruff check .
```

Both must pass. CI runs the corresponding checks across the supported Windows/Linux and
Python versions.

## Code conventions

- **`from __future__ import annotations`** belongs at the top of every Python file; new
  modules should use it as well.
- **Type annotations** are required for public function signatures (parameters and return
  values), following the existing code in `backends/base.py` and `telemetry.py`.
- **Plugin interfaces** are modeled as `abc.ABC` with `@abc.abstractmethod`
  (see `BenchmarkBackend`, `TelemetryProvider`) rather than as an undocumented
  duck-typing convention.
- **User-interface language:** German is the source language for user-visible strings
  (terminal output, reports, warnings). English translations live in
  `llmbench/locales/en.json`. New user-visible strings must go through
  `llmbench/i18n.py::_()`:

  ```python
  from llmbench.i18n import _

  print(_("Server nicht erreichbar"))
  ```

  `_()` returns the German text unchanged when `_current_lang == "de"` (default);
  otherwise it looks up the matching entry in `en.json` (falling back to German if no
  entry exists). Internal log/debug output without user-facing meaning does not need to
  use `_()`. Values should be inserted with placeholders after translation;
  `_(f"...")` is not translatable:

  ```python
  print(_("Modell: {name}").format(name=model["name"]))
  ```

  The language is selected **once at the very beginning** of `setup.bat`/`setup.sh`
  (or the launcher scripts), stored in `.runtime/language`, and passed to Python and
  the Docker container as `LLMBENCH_LANG`. An explicit `project.language` in
  `benchmark.yaml` takes precedence.
- **Installer scripts** (PowerShell/Bash) do not hard-code user-facing text. They retrieve
  strings by key: `T 'docker.check'` (PowerShell, strings in
  `scripts/locales/de.psd1` + `en.psd1`, placeholders `{0}`) or
  `ui_step docker.gpu_check` (Bash, strings in `scripts/locales/de.sh` + `en.sh`,
  placeholders `%s`). Output must go through the shared UI helpers
  (`scripts/lib/UI.psm1` or `scripts/lib/ui.sh`) so headers, sections,
  `[+]`/`[OK]`/`[!]`/`[X]`, menus, yes/no questions, and download progress remain
  consistent. Installations ask for confirmation
  (`Confirm-Install` / `ui_confirm_install`); `LLMBENCH_AUTO_INSTALL=1/0` can skip
  the prompt.
- **`tests/test_i18n_coverage.py`** fails if a `_()` source string has no English
  translation, if an installer key exists in only one language, or if a script references
  an unknown key.
- **Tests mock subprocess/HTTP boundaries** instead of requiring real GPUs, binaries, or
  Docker. Canonical examples:
  - `tests/test_backends.py`: `LlamaCppBackend` methods are tested by replacing the
    underlying functions (`run_llama_bench`, `start_llama_server`, ...) with fakes via
    `monkeypatch.setattr`; no real `llama-bench` call is made.
  - `tests/test_endpoint.py`: HTTP load tests use `httpx.MockTransport`, for example
    `httpx.MockTransport(_sse_response_handler(...))`, together with a
    `_PatchedAsyncClient` subclass that injects the mock transport. No real server is
    required.

  New backends and telemetry providers follow the same pattern: subprocess calls
  (`docker`, `rocm-smi`, `xpu-smi`, ...) and HTTP calls are mocked rather than
  tested against real hardware/binaries.

## Adding a new backend

1. Add `llmbench/backends/<name>.py` with a class implementing `BenchmarkBackend`
   (`llmbench/backends/base.py`). The required abstract methods are:
   - `run_benchmark(model_path, profile, kind, out_dir, bench_cfg, on_progress=None)`
   - `start_server(model_path, profile, endpoint_cfg, bench_cfg, log_path)`
   - `stop_server(proc)`
   - `wait_health(base_url, timeout_s, headers=None)`
2. The base class also provides the optional non-abstract hooks
   `begin_profile(...)` / `end_profile()` with no-op defaults. They are intended for
   HTTP-only backends that benefit from starting a server once per profile rather than once
   per test type. Check the current `backends/base.py` signature when preparing a PR.
3. Use `LlamaCppBackend` (`llmbench/backends/llama_cpp.py`) as the subprocess reference
   and `VllmBackend` as the Docker/HTTP reference.
4. Register the backend in the factory (`backends/__init__.py`, or wherever
   `get_backend(cfg)` currently lives) and add the configuration field selecting it.
5. **Tests:** add `tests/test_backends_<name>.py` covering each method with mocked
   subprocess/Docker/HTTP calls. Tests must not require a real server, container, or
   download.
6. Also follow "Installing/removing backend runtimes" below: every new backend needs a
   symmetrical install/uninstall path.

## Adding a new telemetry provider

1. Add a class in `llmbench/telemetry.py` (or a new module if the file becomes too large)
   that implements `TelemetryProvider`. Required methods:
   - `initialize() -> bool` — verify availability and return `True` only on success.
   - `sample_gpus() -> list[GpuSample]` — return one `GpuSample` per detected GPU.
   - `shutdown() -> None` — release resources cleanly.
2. `GpuSample` (dataclass in `telemetry.py`) has fixed fields:
   `index`, `util_gpu_percent`, `util_memory_percent`, `memory_used_bytes`,
   `memory_total_bytes`, `temperature_c`, optional `power_w`, and `compute_pids`.
   If a source cannot provide a field, use a documented empty/`None` value rather than
   removing the field.
3. Use `NvidiaProvider`, `AmdProvider`, and `DefaultProvider` as references.
4. Extend `get_telemetry_provider()`. When multiple GPU vendors are available,
   `CompositeProvider` is used rather than a "first one wins" rule.
5. **Tests:** extend `tests/test_telemetry.py` with mocked provider output. No test may
   require actual hardware; unavailable providers must fail cleanly and allow fallback
   behavior.

## Installing/removing backend runtimes

Every runtime required by a backend (binary, Docker image, volume, ...) must support
**both directions**:

- **Install:** automated through `llmbench install-backend --backend <name>` or the
  existing `llmbench install-llama-cpp` as reference.
- **Remove:** a counterpart that fully cleans up its runtime resources — stopping/removing
  containers, removing images, removing volumes where appropriate (model blobs kept by
  default unless an explicit purge flag is used), and removing local state.

No backend may be **install-only**. After uninstalling, `docker ps -a`, `docker images`,
and `docker volume ls` should be back to the expected pre-installation state. See
[ROADMAP.en.md](ROADMAP.en.md) for the planned mechanisms.

## Authorship, credit, and attribution

Contributions should remain clearly attributed to the people who actually created them.

- **PR author remains visible:** External contributions are submitted through the normal
  fork/branch and pull-request workflow. The maintainer does not re-publish the work under
  their own name.
- **Preserve commit authorship:** Commits should use the original author's Git identity.
  Maintainers should not remove or replace author/co-author attribution with their own
  identity.
- **Collaborative work:** When multiple people substantially work on the same commit, Git's
  `Co-authored-by: Name <email>` trailer can be used.
- **Changelog credit:** Relevant external contributions are credited in the changelog with
  the contributor's GitHub handle, for example:

  ```markdown
  - Added KV-cache detection and verified context limits — @username
  ```
- **Release notes:** External contributors are mentioned with `@username` next to their
  changes or in a dedicated contributors section.
- **Maintainer changes to another person's PR:** Small integration, review, or conflict
  resolution changes do not change the original attribution of the feature. If multiple
  people contributed substantial parts, all are credited.
- **No credit shifting:** Reviewing, merging, or releasing a contribution does not
  automatically make the maintainer the author of the contributed code.

### Merge and review model

`main` is protected. Changes are submitted through pull requests and must satisfy the
configured branch rules and status checks. Code-owner review is required for protected
areas. `.github/CODEOWNERS` defines the maintainer as repository code owner.

External contributors do **not** need direct write access to `main`. The normal flow is:

```text
Fork/Branch -> Commits -> Pull Request -> CI/Review -> Maintainer approval -> Merge
```

## Pull-request checklist

Before opening a PR:

- [ ] `pytest -q` and `ruff check .` pass locally.
- [ ] Both changelog languages were updated where the change is user-visible:
  [`CHANGELOG.md`](CHANGELOG.md) and [`CHANGELOG.en.md`](CHANGELOG.en.md). External
  contributions credit the contributor with `@username`.
- [ ] New/changed functionality has tests that mock HTTP/subprocess boundaries.
- [ ] Every new `_()` source string has a matching entry in
  `llmbench/locales/en.json`.
- [ ] New backends/telemetry providers have a documented install/uninstall path or clean
  fallback behavior.
- [ ] Documentation changes keep German and English Markdown counterparts synchronized.

## Further references

- [`README.md`](README.md) — user view, quick start, result structure
- [`README.de.md`](README.de.md) — German README
- [`ROADMAP.en.md`](ROADMAP.en.md) — backend/telemetry roadmap in English
- [`docs/DOCKER.en.md`](docs/DOCKER.en.md) — Docker operation in English
- [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md) — release acceptance checklist
