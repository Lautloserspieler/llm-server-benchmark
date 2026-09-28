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

Windows:

```powershell
.\START_BENCHMARK.bat
```

Linux:

```bash
./START_BENCHMARK.sh
```

Direkt über die CLI:

```bash
llmbench run --config benchmark.yaml --duration short --hardware gpu
```

## 3. Dauer

- `short`: schneller Plausibilitäts-/Smoke-Test
- `medium`: bessere Wiederholbarkeit
- `long`: Referenzlauf mit vielen Wiederholungen und langen Tests

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
```

`both` ist nötig, wenn kombinierte CPU/GPU-Soak-Tests sinnvoll ausgeführt werden sollen.

Overload:

```bash
llmbench run --hardware gpu_overload
```

Dieser Modus ignoriert konservative VRAM-Preflights bewusst und ist für Unified-Memory-/Grenztests gedacht.

## 5. Einzelnes Modell

```bash
llmbench run --model "Qwen3.5-9B" --hardware gpu --duration medium
```

## 6. Ergebnisse

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

Siehe [Systeme vergleichen](Comparing-Systems).
