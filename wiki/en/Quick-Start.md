[Deutsch](DE-Quick-Start) | [English](EN-Quick-Start)

---

# Quick Start

## 1. Setup

Windows:

```powershell
.\setup.bat
```

Linux:

```bash
./setup.sh
```

## 2. Start a benchmark

```bash
llmbench run --config benchmark.yaml --duration short --hardware gpu
```

## 3. Choose a duration

- `short`: smoke and sanity testing
- `medium`: better comparison quality
- `long`: reference and stability runs

```bash
llmbench run --duration short
llmbench run --duration medium
llmbench run --duration long
```

## 4. Choose a hardware mode

```bash
llmbench run --hardware cpu
llmbench run --hardware gpu
llmbench run --hardware both
llmbench run --hardware gpu_overload
```

`gpu_overload` deliberately bypasses the conservative VRAM preflight and is intended for boundary and unified-memory testing.

## 5. Test one model

```bash
llmbench run --model "Qwen3.5-9B" --hardware gpu --duration medium
```

## 6. Result files

```text
results/
  SERVER_YYYYMMDD-HHMMSSZ/
    hardware.json
    summary.json
    benchmarks.csv
    report.html
    report.pdf
```

## 7. Compare systems

```bash
llmbench compare results/system-a results/system-b --strict
```
