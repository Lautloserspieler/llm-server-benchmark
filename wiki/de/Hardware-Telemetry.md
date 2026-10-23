[Deutsch](DE-Hardware-Telemetry) | [English](EN-Hardware-Telemetry)

---

# Hardware-Telemetrie

llmbench speichert Leistungswerte zusammen mit Telemetrie.

## CPU

Typische Daten:

- CPU-Auslastung
- physische/logische Kerne
- RAM-Auslastung
- Energieprofil/Governor, soweit verfügbar

CPU-Package-Temperatur und CPU-Package-Power sind nicht auf jeder Plattform standardisiert verfügbar und daher keine überall garantierten Kernmetriken.

## NVIDIA

Typische Messwerte:

- GPU-Auslastung
- VRAM
- Temperatur
- Leistungsaufnahme
- Power-Limit
- Compute-Prozesse
- Treiber-/GPU-Metadaten

## AMD

AMD-Telemetrie wird über `rocm-smi` erfasst, soweit verfügbar.

## Intel

Intel-GPU-Telemetrie wird über `xpu-smi` erfasst (`xpu-smi discovery -j` zur Erkennung, `xpu-smi stats -d <id> -j` einmal pro GPU), soweit verfügbar: Auslastung, VRAM, Temperatur und Leistungsaufnahme. Von xpu-smi nicht gelieferte Werte bleiben leer statt `0`; Compute-Prozesse werden nicht aufgelistet.

## Baseline und Fremdlast

Vor Lasttests versucht llmbench einen Ruhewert zu erfassen. Fremde GPU-Prozesse werden als möglicher Störfaktor markiert.

## Rohdaten

Detaillierte Samples liegen in `raw_*.json`; `summary.json` enthält aggregierte Werte.
