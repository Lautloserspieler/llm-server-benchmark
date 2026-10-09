# Changelog

[🇩🇪 Deutsch](CHANGELOG.md) | 🇬🇧 English

## Unreleased

### Compare: measured energy efficiency

- `llmbench compare` now ranks energy efficiency from the persisted
  `tokens_per_joule` and `wh_per_1k_tokens` telemetry metrics instead of deriving a
  new GPU-only Tokens/s-per-Watt value.
- Comparison preserves measurement scope and component coverage. Different energy scopes
  are marked non-comparable and are excluded from the efficiency score.
- Legacy GPU-only Tokens/s/W values remain visible for older result files as informational
  data but no longer affect the aggregate score.
- HTML, PDF, `comparison.json`, and the new `comparison_efficiency.csv` expose
  Tokens/Joule, Wh/1k tokens, and measured-component energy where available.

### System telemetry: reporting complete

- Terminal, HTML, and PDF reports now expose CPU utilization, frequency, temperature,
  package power and CPU energy together with GPU power, temperature, and energy.
- Measured CPU/GPU components are shown under the explicit `measured_components` scope
  with coverage, average/peak power, and energy, and are never labelled as wall power.
- Prompt and generation tests show Tokens/Joule and Wh/1k tokens where available;
  missing sensors are reported as unavailable rather than zero.

### Effective KV-cache introspection

- Schema-v3 results now retain a provenance-aware effective KV-cache configuration
  per benchmark profile. Requested settings remain separate.
- llama.cpp and vLLM collect only explicit runtime, log, or metric observations;
  missing or conflicting values remain visible as unknown/unavailable and never
  fail an otherwise valid benchmark.
- Terminal, HTML, PDF, and CSV show the comparable KV-cache core while
  backend-specific details remain in the JSON artifact.
- llama.cpp uses `build_commit` as the common runtime version and retains
  `build_number` as a native detail. vLLM retains native cache tokens and its
  executor-wide GPU memory budget only as details, not comparable KV capacity or
  KV memory usage; total-device VRAM telemetry is unchanged.

### System telemetry: energy and efficiency

- CPU energy uses available RAPL/powercap energy counters directly where
  possible; GPU energy is integrated from measured power and real sample
  timestamps.
- CPU and GPU energy are combined under the explicit `measured_components`
  scope and are never presented as whole-system wall power.
- Prompt and generation benchmarks can expose conservative Tokens/Joule and
  Wh/1k-token efficiency metrics when both energy and workload are known.
  Long-context runs intentionally make no efficiency claim yet.
- Schema v3 preserves provenance and measurement scope for the new energy and
  efficiency values; unavailable sensors remain unavailable rather than zero.

### Memory-bandwidth characterization

- Schema-v3 hardware artifacts now represent memory domains separately from GPUs,
  with explicit GB/s provenance and unknown/unavailable states.
- Apple Silicon may match a small bundled catalog of official specifications;
  NVIDIA retains safe NVML bus/clock inputs without guessing a data-rate formula,
  and AMD SMI values are labelled as current-clock provider operating ceilings.
- `llmbench run --collect-memory-bandwidth` optionally records an installed
  `mactop` Apple system-DRAM trace. The observation is experimental, non-blocking,
  and never reported as process-exclusive effective bandwidth.
- Thanks to @enmanuelmag for the roadmap and design review.

### Result schema v3 provenance

- New result artifacts use schema version 3 and preserve evidence for requested, defaulted,
  detected, calculated, measured, and verified values. The initial migration covers configured
  GPU layers, detected physical CPU cores, and measured llama.cpp throughput.
- Readers, reports, comparison, and CSV export remain compatible with schema v2 results.
  HTML/PDF now include a compact provenance section and CSV has scalar provenance columns.
- Thanks to @enmanuelmag for the provenance roadmap and review direction.

### Verified context capability and depth curve

- Long-context results now derive a per-profile `maximum_verified_context` only from depths
  where prompt processing and text generation both completed.
- Schema v3 records that maximum with `source: verified`, unit `tokens`, and
  `experimental_validation` evidence.
- The normalized capability data retains requested/completed depths, the first failed depth,
  capacity/OOM versus timeout boundaries, and the available prefill/decode curve.
- HTML, PDF, and terminal reports show the verified maximum and context-depth table.

### Ubuntu reference run: CPU isolation, capacity status, and long-context recovery

- CPU-only llama.cpp profiles now enforce `device none` in addition to `gpu_layers: 0`.
  Current builds also disable operation offload so CUDA builds cannot silently move prompt
  operations onto the GPU.
- Expected VRAM limits during the combined soak test are stored as `skipped_capacity`
  instead of a generic error. This especially applies to full-GPU profiles whose weights
  already do not fit into detected VRAM during preflight.
- If a long-context run fails only at a later context stage, all previously completed
  prompt/generation pairs are preserved. The run is stored as `partial` and records the
  context stage that was not reached and any detected capacity boundary.
- The same now applies to a **benchmark timeout**: fully completed context stages are
  recovered from llama-bench JSON that was already written, while a half-finished next
  stage is discarded. The limiting reason remains visible as `limit_status: timeout`.
- The default OOM/context stress ladder now extends to 393,216 tokens (384K). Existing
  configurations that still use the unchanged legacy default ending around 130K are
  migrated automatically, while explicitly customized `oom_contexts` lists are preserved.
- If `stress-quant` cannot find two quantizations of the same base model, the test is now
  reported as `skipped` (exit code 2) instead of failed. A structured `quant.json` is still
  written with reason `no_matching_quantizations`, while real quant benchmark failures
  continue to return an error.
- Terminal, HTML, PDF, CSV, and comparison outputs understand the new partial/capacity
  states and continue to show valid partial results.
- Regression tests reproduce cases observed in the Ubuntu/RTX-5090 reference run:
  CPU prompt offload despite `-ngl 0`, a VRAM boundary in the soak test, and Qwen3.8-27B
  completing measurements through 131K before failing at 262K.
- Docker CI now uses a daily-changing cache key for the runtime security layer. This avoids
  reusing a stale BuildKit cache for `apt-get upgrade` after Ubuntu security updates while
  still keeping the expensive llama.cpp CUDA build cacheable.

### GitHub Wiki as a bilingual user manual

- Versioned Wiki sources are separated into `wiki/de/` and `wiki/en/`; all user pages
  are available in German and English.
- `Home.md` acts as the language selector. Every page links directly to its counterpart.
- `_Sidebar.md` and `_Footer.md` provide navigation for both languages.
- The `Publish Wiki` workflow verifies that each German page has an English counterpart
  and publishes the sources as flat `DE-*` and `EN-*` pages in the GitHub Wiki.
- A completely empty Wiki is intentionally handled with an informational message only.
  After the initial Home page exists, the workflow can be started manually and then keeps
  the Wiki synchronized automatically when source pages change.
- The README links to the Wiki as the bilingual user manual.

### Hugging Face download recognizes completed GGUFs correctly

- Fix: the Rich/tqdm bridge now implements `set_description_str`, which current
  `huggingface_hub` calls after completed Xet downloads.
- A GGUF file that has already been fully written locally is re-detected after a late
  progress/finalization error instead of incorrectly being treated as a failed download.
- Regression tests reproduce the observed case: file completely written, followed by a
  progress callback failure.

### Standard model suite updated for 2026

- The setup terminal UI now also shows DeepSeek-V4-Flash-0731 as `[EXTREME]`. It can be
  selected explicitly by model number; `A = All standard models` intentionally remains
  limited to the six normal reference models and never starts the extreme download.
- Quick Start, Installation, and Model Suite pages in the DE/EN Wiki now describe the
  normal flow correctly through `START_BENCHMARK.bat` / `START_BENCHMARK.sh` and the
  terminal UI for duration, hardware, and additional stress tests. Direct CLI commands are
  documented as advanced use.
- Replaces the old reference suite with current models: Qwen3.5-9B, Gemma-4-12B-IT,
  Qwen3.8-27B, GLM-4.7-Flash, Qwen3.5-122B-A10B, and Mistral-Small-4-119B-2603.
- GLM-4.7-Flash replaces Qwen3.5-35B-A3B in the mid slot so the standard suite is not too
  concentrated on a single model family. Old saved selections are automatically migrated
  from Qwen3.5-35B-A3B to GLM-4.7-Flash.
- DeepSeek-V4-Flash-0731 is available as a separate `extreme` suite and intentionally is
  not part of `all`, preventing setup from unexpectedly downloading a roughly 145-GiB
  model.
- Uses the available 4-bit reference quantization for each model: Q4_K_M for most models,
  UD-Q4_K_M for Mistral 119B, and UD-Q4_K_XL for DeepSeek V4 Flash.
- The underlying `extreme` suite and CLI validation remain available for automation and
  advanced/manual use.

### Benchmark hardening: sustained load, CPU timeouts, and GPU overload

- The combined CPU/GPU soak test now divides available CPU threads 75/25 between the
  CPU-only and GPU servers by default to reduce oversubscription and CPU request timeouts
  observed in long runs.
- CPU and GPU benchmarks now have separate time limits; the long preset allows up to
  14,400 seconds for slow CPU-only runs.
- `gpu_overload` remains an explicit stress test. Expected loading, OOM, or timeout
  boundaries for intentionally oversized full-GPU models are reported as
  `skipped_capacity` instead of a generic benchmark failure.
- `summary.json` stores the hardware selection; normal GPU runs and `gpu_overload` runs
  are treated as different modes during comparison.
- CI fix: the new soak thread split satisfies Ruff/SIM108.

### Always full performance: power plans and power limits on Linux and Windows

- Before every `llmbench run` and `llmbench stress-*`, llmbench switches the machine
  to full performance and leaves it there by default. Linux handling covers
  power-profiles-daemon/tuned, ACPI platform profile, CPU governor,
  energy-performance-preference, turbo/boost, `scaling_max_freq`, Intel RAPL limits,
  PCIe ASPM, NVIDIA persistence mode and power limit, AMD GPU power cap, and DPM level.
  Windows uses a dedicated power plan based on Ultimate Performance (100% processor
  performance, aggressive boost, no core parking, no ASPM, no standby) plus the NVIDIA
  power limit.
- `llmbench performance on|off|status`; `off` restores the exact values that were active
  before llmbench changed them, stored in `.runtime/performance_state.json`.
- New `performance` configuration section (`enabled`, `restore_after_run`,
  `use_sudo`) and `--no-performance-mode`. Settings that cannot be changed without
  root/Administrator are reported in the output and `summary.json`.

### New llama.cpp builds: `--no-mmap` replaced by `--load-mode`

- Fix: current llama.cpp builds no longer recognize `--no-mmap`/`--mlock` and use
  `-lm/--load-mode` instead. CPU-only profiles therefore caused `llama-server` to fail
  with `error: invalid argument: --no-mmap` in soak, endpoint, and stress tests.
  llmbench now checks `--help` once and uses `-lm none` / `-lm mlock` on new builds,
  while keeping the old flags for older builds.
- `llama-bench` previously continued silently with mmap in these builds; it now loads
  correctly without mmap. If a build must run without the option, a translated warning is
  shown in the terminal and summary.
- On Windows, the kernel process `System` (PID 4) is no longer reported as a foreign GPU
  process.

### llama-server startup failures are reported immediately with the real cause

- Fix: when `llama-server` exited immediately during startup (crash, rejected parameter,
  etc.), soak/endpoint/stress tests used to wait up to 300 seconds and then only report
  `llama-server did not become ready: All connection attempts failed`. The exited process
  is now detected immediately; the error includes a readable exit code (for example
  `0xC0000005 – crash`), the last server-log lines, and the log path.
- An already occupied port is detected before startup and reported clearly.
- Windows setup now checks `llama-server --version` in addition to `llama-bench` during
  startup probing. If the server build crashes, the fallback chain tries the next CUDA
  build, then Vulkan, then CPU.
- Before every test, measurement waits up to 15 seconds for the GPU to become idle after
  the previous test. The warning that the GPU was already busy before a test is now shown
  only when utilization remains elevated after that wait.
- Monitor warnings are translated.

### Windows: llama.cpp automatically falls back to a working build

- Fix: if the selected llama.cpp build crashed on first startup (for example `cuda-13.4`
  with exit code `-1073741819` = `0xC0000005`, access violation), setup previously
  aborted completely. It now tries a sequence of builds: the best matching CUDA version
  (highest <= driver-reported support), other builds in the same major version, an older
  CUDA major version such as `cuda-12.4`, Vulkan, then CPU. The first working build is
  installed.
- GPUs below compute capability 7.5 (for example Pascal) skip CUDA-13 builds; GPU and
  compute capability are shown.
- Readable error descriptions replace raw numbers (crash, missing DLL, unsupported CPU
  instruction set); all startup probes are logged in `.runtime/llama-probe.log`.
- A warning is shown when only Vulkan/CPU works instead of CUDA, because those results are
  not directly comparable to CUDA servers. An explicitly selected fallback build is
  recorded and is not replaced by the crashing build on the next startup.
- `LLMBENCH_LLAMACPP_BUILD_BACKEND=auto|cuda|vulkan|cpu` now also applies on Windows.
- Package selection and installation live in `scripts/lib/LlamaCpp.psm1` and are covered
  by pwsh tests.

### Setup: NVIDIA driver check, reboot continuation, backend selection

- Windows now verifies that an NVIDIA GPU and a sufficiently new driver (580+, required
  for the CUDA-13 image) are present before Docker GPU setup. If the driver is missing or
  too old, setup shows a clear message and offers to open the official NVIDIA driver page;
  drivers are never installed silently. WSL/Docker installation is skipped in that case
  and auto mode continues natively.
- If an installation requires a reboot, setup can resume automatically after the next
  login through a one-time RunOnce entry and can restart Windows immediately. This also
  applies to `START_BENCHMARK.bat`.
- New backend selection during setup (`python -m llmbench.backend_select`, Windows and
  Linux): a table shows status and download size, setup asks before each image download,
  then selects the default backend (`tools.backend`). Without Docker, nothing is
  attempted; failure of an optional backend does not abort setup.

### Language system everywhere + unified terminal UI

- Language (German/English) is selected **at the very beginning** of
  `setup.bat`/`setup.sh` or the launcher scripts, stored in `.runtime/language`, and
  used everywhere: installer scripts, Python CLI, reports, and the Docker container
  (`LLMBENCH_LANG` is passed through `compose.yaml`).
- All Windows scripts (PowerShell) and Linux/macOS scripts (Bash) load text from
  `scripts/locales/{de,en}.psd1` or `{de,en}.sh` and use shared UI helpers
  (`scripts/lib/UI.psm1`, `scripts/lib/ui.sh`): header, section lines, colored
  `[+]`/`[OK]`/`[!]`/`[X]` messages, numbered menus with a marked default,
  yes/no prompts (`j/n` or `y/n`), and download progress with speed and ETA.
- `setup.bat`/`START_BENCHMARK.bat` are now thin launchers; logic lives in
  `scripts/SETUP.ps1` and `scripts/START_BENCHMARK.ps1`.
- Model selection, setup wizard, stress tests, backend installation, and Docker messages
  are translated; model selection uses a table.
- Linux `setup.sh` now also asks before each installation (Python, Docker Engine, Compose
  plugin, NVIDIA Container Toolkit) and runs with macOS Bash 3.2.
- New `tests/test_i18n_coverage.py` verifies that every runtime text is available in all
  supported languages; `tests/test_installer_scripts.py` actually executes installer
  scripts against fakes (pwsh/bash).
- Fix: `llmbench bootstrap`, which runs at every start, previously reset the selected
  language in `benchmark.yaml` to German.
- Fix: the status value "timeout" appeared in German inside English reports; five PDF
  labels were missing English translations.

### Windows setup installs missing components after confirmation

- `setup.bat` detects missing WSL2/Ubuntu, Docker Desktop, and Python 3.10+, asks
  `[J/n]`, and can download/install the component automatically (Docker Desktop through
  winget or the official installer; Python through the existing SHA256-verified bootstrap).
- Docker Desktop is started when needed and can be switched to Linux containers; setup
  waits up to five minutes for readiness.
- If installation requires a reboot, setup ends with a clear message (exit code 3010)
  instead of a PowerShell stack trace and no longer incorrectly falls back to native mode.
- `LLMBENCH_AUTO_INSTALL=1` installs without confirmation; `=0` never installs.

## 1.6.0

### vLLM as the second backend (via Docker)

- New `vllm` backend: `tools.backend: vllm` in `benchmark.yaml` benchmarks a vLLM
  server instead of llama.cpp. vLLM runs exclusively as a Docker container using the
  official `vllm/vllm-openai` image, with no local pip/venv setup. Windows
  (Docker Desktop/WSL2) and Linux (native Docker) therefore behave consistently.
- Prompt, generation, and long-context measurements use calibrated HTTP requests against
  the OpenAI-compatible `/v1/completions` endpoint in the new `llmbench/http_bench.py`
  module, including protection against vLLM prefix caching: every fill prompt gets a
  unique nonce so repeated tests cannot accidentally measure a cache hit instead of real
  prompt processing.
- New commands `llmbench install-backend --backend vllm` and
  `llmbench uninstall-backend --backend vllm [--purge-models]`: automated install
  (image pull) and complete removal (container, image, optionally model volume). Backends
  must not be install-only.
- `llmbench compare --strict` now rejects comparisons between runs using different
  backends (for example llama.cpp vs vLLM), because tokens/s are not directly comparable
  across backend implementations.
- `BenchmarkBackend` adds optional `begin_profile`/`end_profile` hooks for backends
  that start a server once per profile rather than once per test type; existing llama.cpp
  configurations are unaffected.

### AMD GPU live telemetry (rocm-smi)

- New `AmdProvider` supplies live GPU utilization, VRAM, temperature, and power for AMD
  GPUs through `rocm-smi --json`. Previously AMD had only one-time hardware detection.
- When multiple GPU vendors are present, a new `CompositeProvider` uses all available
  sources in parallel instead of selecting only the first vendor.
- Fix: `telemetry_source` in result files was incorrectly reported as `cpu_only` for
  non-NVIDIA sources even when real GPU telemetry was present.

### Project infrastructure

- Added `CONTRIBUTING.md`, `ROADMAP.md`, and GitHub issue/PR templates under
  `.github/` as the foundation for additional backends (Ollama, TGI) and GPU vendors
  (Intel).

## 1.4.1

### Power-saving warning for Linux desktops (for example Ubuntu 24.04 LTS)

- `llmbench doctor` now also detects the active `power-profiles-daemon` profile
  (standard on Ubuntu Desktop with GNOME) and warns when it is not set to
  `performance`. Ubuntu Desktop normally starts in `balanced`, which can materially
  reduce tokens/s compared with servers using a fixed `cpupower` governor and therefore
  distort server comparisons. The recommended fix is shown directly:
  `sudo powerprofilesctl set performance` or
  `sudo cpupower frequency-set -g performance` when no power-profiles-daemon is active.
- `hardware.json`, `report.html`, and `report.pdf` now show the active
  power-profiles-daemon profile in the "Power plan" field in addition to the CPU governor.

## 1.4.0

### Automatic llama.cpp installation on Linux/macOS

- `setup.sh`, `START_BENCHMARK.sh`, and `llmbench setup` now install llama.cpp
  automatically instead of failing when `llama-bench`/`llama-server` are missing
  under `tools/llama.cpp/`, matching the existing Windows behavior.
- New `llmbench/llama_cpp_setup.py` downloads a suitable prebuilt release from
  `ggml-org/llama.cpp`: with a detected GPU, Linux first tries a Vulkan build
  (`llama-*-bin-ubuntu-vulkan-<arch>.tar.gz`), which can work across NVIDIA/AMD/Intel
  because llama.cpp does not publish prebuilt Linux CUDA packages. If Vulkan cannot start
  (for example due to a missing driver), setup falls back to a CPU build
  (`llama-*-bin-ubuntu-<arch>.tar.gz`). macOS uses the matching
  `llama-*-bin-macos-<arch>.tar.gz` release; Metal is already included on arm64.
- New command
  `llmbench install-llama-cpp [--root .] [--tag b10604] [--force]` for manual
  installation or a fixed build pin. It respects `llama-cpp-version.txt` and the
  `LLMBENCH_LLAMACPP_TAG` environment variable.
- An existing working build is not downloaded again; setup verifies
  `.llama-build.json` and performs a startup probe.

### Colored result overview in the terminal

- `llmbench run` now prints results directly in the terminal after every run using the
  same major sections as `report.html`/`report.pdf` (hardware cards, test conditions,
  benchmark/telemetry tables by profile, endpoint/soak values, notes), formatted with
  `rich`. This is especially useful on Linux servers accessed over SSH without a desktop.
- `--plain` and redirected output (not a real terminal) automatically use the previous
  simple text table without colors or box drawing.

### Soak test (CPU + GPU simultaneously)

- New `soak` test starts a CPU-only and a GPU server at the same time and keeps both
  under sustained load to expose thermal throttling. Previous pp/tg tests often lasted
  only seconds, too short for hardware to reach thermal equilibrium.
- It runs by default as part of every `llmbench run`: a short pass
  (`soak.duration_short_seconds`, default 5 minutes) and a long pass
  (`soak.duration_long_seconds`, default 30 minutes).
- Throttling heuristic compares tokens/s in the early part of the run (10–30%) against the
  late part (70–100%). A drop above `soak.throttle_tps_drop_fraction` (default 15%) is
  treated as a throttling indication and appears as a warning in the report.
- `llmbench bootstrap` now creates a `CPU-Only` profile (`gpu_layers: 0`) in addition
  to `Full-GPU` for newly detected models. This is required by the soak test and also
  makes the pure CPU path directly comparable in normal pp/tg tests.
- Results appear in `report.html`, `report.pdf`, `summary.json`
  (`models[].soak`), `comparison.html`, and `comparison.pdf`.
- `ResourceMonitor` can mark multiple target processes as owned load through
  `set_target_pids`, so the CPU and GPU servers do not report each other as foreign load.
- Disable with `soak.enabled: false`.

### Hardware selection (`--hardware`)

- New `llmbench run --hardware {cpu,gpu,both}` option (default `both`) restricts the
  run to profiles with `gpu_layers: 0` (`cpu`), profiles with non-zero
  `gpu_layers` (`gpu`, including hybrid profiles), or all profiles (`both`).
- The soak test runs only with `both` because it needs CPU and GPU at the same time.
  With `cpu` or `gpu` it is skipped and the report explains why.
- If a model has no profile matching the selected hardware, it is skipped with a report
  note instead of aborting the run; the endpoint test behaves the same way when it needs
  a compatible profile.
- `START_BENCHMARK.bat` and `START_BENCHMARK.sh` now ask for the hardware selection
  interactively immediately after benchmark duration.

## 1.3.0

### Live display during a run

- New terminal status line shows the running test, elapsed time, progress from
  `llama-bench --progress`, GPU utilization, VRAM, power draw, temperature, and ETA.
  Previously there was no live feedback during a run.
- `llama-bench` output is now read concurrently instead of being fully buffered.
  Progress messages use carriage returns instead of line breaks and are handled
  explicitly.
- If the installed build does not support `--progress`, the test is retried once without
  it instead of failing.
- Every individual result appears immediately after its test rather than only in the final
  report.
- ETA is averaged per test type because long-context tests take much longer than prompt
  tests and a global average would be misleading.
- Without a terminal (for example redirected output), the display automatically switches
  to line-oriented text. It can be forced with `llmbench run --plain`.
- A result table is printed in the terminal at the end.

### PDF report

- Every run now also generates `report.pdf`: server information, evidence of test
  conditions, result tables and bar charts for each model/profile, telemetry, and endpoint
  values.
- Prompt processing and text generation use separate charts; a shared scale would make
  generation bars unreadable.
- If PDF generation fails, the run remains valid and the reason is added to
  `summary.json`.
- New dependency: `reportlab`.

### Web dashboard removed

- `llmbench serve`, `llmbench/server.py`, and the complete `web/` directory were
  removed together with `fastapi`, `uvicorn`, and the `[web]` extra. The terminal
  live display replaces the dashboard.

## 1.2.0

### Reproducibility

- `summary.json` now contains the actual configuration used, a configuration fingerprint,
  llmbench version, llama.cpp build, and SHA256 of the llama-bench executable.
- `llmbench compare` checks whether runs are comparable before comparing them:
  configuration, llama.cpp build, model SHA256, and profile settings. Differences are
  shown at the top of the report.
- New `llmbench compare --strict` switch returns exit code 1 on incompatibilities.
- Automatic llama.cpp discovery no longer searches the working directory, PATH, and system
  locations, preventing a deliberately pinned version from being silently replaced by
  another. Legacy behavior is available with `--allow-system-search`.
- Model discovery now scans only the project's model directory, not
  `C:/llm_models` or `~/.cache/llama.cpp/models`.
- Model names are made unique. Two GGUF files with the same filename no longer overwrite
  each other in the result directory.
- Result directories use UTC timestamps.

### Measurement methodology

- `llama-server` starts with the same core parameters as `llama-bench` (batch, ubatch,
  Flash Attention, KV-cache types).
- Endpoint tests set `ignore_eos` and a fixed seed so token count per request does not
  fluctuate.
- Added warmup requests before measurement (`endpoint.warmup_requests`).
- `benchmark.timeout_seconds` limits every individual test; overruns are recorded as
  `timeout` instead of hanging the run.
- The monitor detects foreign GPU processes and records a warning; it also captures an
  idle baseline before load.
- Windows power plan and Linux CPU governor are recorded.

### Reports

- Failed and aborted tests are visible as such in comparisons instead of appearing as
  empty cells.
- Comparison reports now include endpoint results (system TPS, TTFT) and an efficiency
  table in tokens/s per watt.
- All GPUs are shown, not only the first one.
- Missing TTFT values display as "—" instead of 0.00 ms.
- Raw telemetry samples live only in `raw_*.json`; `summary.json` therefore remains
  manageable even after long runs.
- Reports support dark mode.

### Web dashboard

- Wildcard CORS access was removed.
- State-changing endpoints validate browser Fetch Metadata, preventing a foreign website
  from starting benchmarks or overwriting the configuration.
- `/api/runs/{id}` validates paths and rejects access outside the result directory.
- `GET /api/config` now correctly returns file content instead of always being empty.
- Saving creates `benchmark.yaml.bak`, validates the configuration, and normalizes
  `flash_attention`.
- `--allow-remote` intentionally exposes the dashboard to the network and then requires
  an access token.

### Windows setup

- `START_BENCHMARK_CORE.ps1` no longer resolves llama.cpp through `/releases/latest`.
  That endpoint could point to an old release without Windows assets and cause setup to
  fail with "No suitable llama.cpp asset found". Setup now walks the release list and
  chooses the newest release that actually contains the required files.
- llama.cpp can be pinned through `llama-cpp-version.txt`, parameter `-LlamaCppTag`,
  or environment variable `LLMBENCH_LLAMACPP_TAG`. Without a pin, the installed version
  depended on when setup was run.
- CUDA detection falls back to the driver version when the `nvidia-smi` header cannot be
  parsed and reports where the value came from. Previously it silently fell back to
  cuda-12.4.
- All PowerShell scripts are stored as UTF-8 **with BOM**. Windows PowerShell 5.1 otherwise
  read them as ANSI and corrupted umlauts.
- `START_BENCHMARK.bat` and `UPDATE_DEPENDENCIES.bat` pass through arguments.
- The wrapper passes parameters to the core script through hashtable splatting. Array
  splatting could let `-Config` slip through as a value so `benchmark.yaml` landed in
  the next parameter. Both scripts now use `[CmdletBinding()]` and avoid positional
  binding.
- A requested llama.cpp tag is validated for plausibility; a missing release is reported
  as a clear message instead of a raw HTTP 404 from `Invoke-RestMethod`. GitHub API rate
  limits are also reported explicitly.
- Added `llama-cpp-version.txt` template at project root.
- The post-install startup probe uses `--list-devices`; `llama-bench` has no
  `--version`. The probe also checks whether backends loaded successfully and uses
  `Start-Process` with separate output channels so stderr does not become an unreadable
  `NativeCommandError`.
- `llmbench doctor` checks long forms of required flags (`--flash-attn`, `--n-depth`,
  …). The short form `-d` also appeared inside `-dev` and `--delay`, so it could not
  safely detect missing support. The report now shows devices recognized by the build.
- Windows setup installs the package with the web extras, matching `setup.bat`.

### Other

- Version numbers were unified to 1.2.0.
- `setup.sh` and `setup.bat` install the package with web extras.
- `endpoint.api_key` is now actually sent as an Authorization header.
- The setup wizard asks for the server name.
- `llmbench doctor` checks supported llama-bench flags, VRAM fit, and free disk space.
- Ruff configuration added to `pyproject.toml`; all findings fixed.

## 1.1.1

- `winget` is no longer required for Python installation.
- If Python 3.10+ is missing, Python 3.12.10 is downloaded directly from `python.org`.
- Python is installed project-locally under `.runtime/python`; no PATH modification or
  system-wide installation is required.
- The official Python installer is verified with SHA256 before execution.
- Windows x64 and ARM64 are supported.
- `scripts/START_BENCHMARK.ps1` is now a bootstrap wrapper so direct PowerShell startup
  also works without winget.

## 1.1.0

- Windows one-click setup through `START_BENCHMARK.bat`.
- Python 3.12 is configured automatically when needed.
- Virtual environment and Python dependencies are configured automatically.
- The current official `llama.cpp` release is downloaded automatically.
- Automatic selection of CUDA 13.3, CUDA 12.4, or CPU build.
- Required CUDA runtime DLLs are installed automatically.
- The installed llama.cpp build is pinned for reproducible tests.
- `UPDATE_DEPENDENCIES.bat` supports explicit dependency/llama.cpp updates.
- Automatic discovery of GGUF models under `models/`.
- New models are added to `benchmark.yaml` automatically.
- Download directories and GGUF files are excluded from Git.
- Added bootstrap tests.
