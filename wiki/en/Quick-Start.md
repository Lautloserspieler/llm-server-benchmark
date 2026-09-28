[Deutsch](DE-Quick-Start) | [English](EN-Quick-Start)

---

# Quick Start

After setup, the normal user workflow runs entirely through the **terminal UI**. You do not need to manually build `llmbench run ...` commands for a normal benchmark.

## 1. Run setup once

### Windows

```powershell
.\setup.bat
```

### Linux

```bash
./setup.sh
```

Setup configures items such as language, models, and available backends.

## 2. Open the benchmark launcher

After setup, start future benchmark runs through the platform launcher.

### Windows

```powershell
.\START_BENCHMARK.bat
```

### Linux

```bash
./START_BENCHMARK.sh
```

The launcher checks the installation, models, and environment, then opens the terminal UI.

## 3. Choose duration in the terminal UI

The UI asks:

**How long should the test run?**

- **short** – quick check
- **medium** – default values
- **long** – more precise reference and stability measurements

No CLI parameter is required.

## 4. Choose hardware in the terminal UI

The UI then asks what should be tested:

- **CPU only**
- **GPU only**
- **GPU only – intentionally exceed the VRAM limit / test unified memory**
- **CPU and GPU – including sustained-load testing**

The third option is the `gpu_overload` mode, but normal users select it through the menu.

## 5. Choose additional stress tests

The terminal UI then asks whether additional stress tests should run.

Depending on backend and configuration, these include:

- TTFT
- multi-tenant
- OOM / capacity limits
- quantization comparison

The UI summarizes the selected options and starts the benchmark.

## 6. Result files

A run typically creates:

```text
results/
  SERVER_YYYYMMDD-HHMMSSZ/
    hardware.json
    summary.json
    benchmarks.csv
    report.html
    report.pdf
```

Useful entry points:

- `report.html` for visual analysis
- `report.pdf` for sharing and archiving
- `summary.json` for machine-readable analysis

## 7. Compare systems

The benchmark itself is launched through the starter and terminal UI. For advanced analysis, the CLI can also compare completed runs:

```bash
llmbench compare results/system-a results/system-b --strict
```
