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

## 2. Benchmark starten

```bash
llmbench run --config benchmark.yaml --duration short --hardware gpu
```

## 3. Dauer wählen

- `short`: Smoke-/Plausibilitätstest
- `medium`: besserer Vergleich
- `long`: Referenz- und Stabilitätslauf

```bash
llmbench run --duration short
llmbench run --duration medium
llmbench run --duration long
```

## 4. Hardware-Modus

```bash
llmbench run --hardware cpu
llmbench run --hardware gpu
llmbench run --hardware both
llmbench run --hardware gpu_overload
```

`gpu_overload` ignoriert den konservativen VRAM-Preflight bewusst und ist für Grenz-/Unified-Memory-Tests gedacht.

## 5. Einzelnes Modell

```bash
llmbench run --model "Qwen3.5-9B" --hardware gpu --duration medium
```

## 6. Ergebnisdateien

```text
results/
  SERVER_YYYYMMDD-HHMMSSZ/
    hardware.json
    summary.json
    benchmarks.csv
    report.html
    report.pdf
```

## 7. Systeme vergleichen

```bash
llmbench compare results/system-a results/system-b --strict
```
