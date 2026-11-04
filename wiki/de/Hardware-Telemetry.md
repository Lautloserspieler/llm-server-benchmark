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

## Messumfang, Einheiten und Messqualität

- `power.coverage` nennt genau die gemessenen Komponenten (`cpu_package`, `gpu:<n>`). Komponentenenergie ist die Summe nur dieser Komponenten und **keine** Wandleistung. `wall_power_w` / `wall_energy_wh` bleiben leer, solange es keine echte Wandleistungsquelle gibt; Läufe mit unterschiedlichem Messumfang werden nie gegeneinander gerankt.
- `summary.json` enthält einen `units`-Block (Prozent, Bytes, Celsius, Watt, Wattstunden, Joule, Megahertz, Sekunden), damit Werte nicht falsch gelesen werden.
- Jeder GPU-Eintrag hat `sample_completeness`: den Anteil der Samples, in denen der jeweilige Sensor einen Wert geliefert hat. Ein Wert unter `1.0` bedeutet Lücken; Lücken werden nie mit `0` gefüllt und bei der Energieintegration nicht überbrückt.
- Fällt ein Gerät in einer Messrunde aus, behält es seine Position mit leeren Werten; das gilt auch bei gemischten Herstellern, wo ein ausfallendes Herstellerwerkzeug die GPUs der anderen Hersteller nicht mehr verschiebt.
- Leistung wird nur zwischen aufeinanderfolgenden Samples integriert, die höchstens zehn Messintervalle (mindestens 10 s) auseinanderliegen; ein hängender Sampler erzeugt dadurch nie erfundene Energie.
- Der Block `sampling` hält das angeforderte Intervall, das beobachtete Intervall samt Jitter sowie Dauer und Overhead-Anteil des Samplers fest.
- Die Herstellerprovider (NVML, `rocm-smi`, `xpu-smi`) sind durch deterministische Mock-Tests abgedeckt (normale, fehlerhafte, Timeout- und Fehlsensor-Ausgabe). AMD- und Intel-Zuordnungen wurden von der Testsuite nicht auf physischer Hardware verifiziert; nicht getestete Hardware gilt nicht als validiert.

## Rohdaten

Detaillierte Samples liegen in `raw_*.json`; `summary.json` enthält aggregierte Werte.
