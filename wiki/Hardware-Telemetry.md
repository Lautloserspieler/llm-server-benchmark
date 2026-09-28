# Hardware-Telemetrie

llmbench speichert Leistungswerte zusammen mit Telemetrie, damit sich Performance und Hardwarezustand gemeinsam beurteilen lassen.

## CPU

Erfasst werden unter anderem:

- CPU-Auslastung
- logische/physische Kerne
- RAM-Auslastung
- Energieprofil/Governor, soweit verfügbar

CPU-Package-Temperatur und CPU-Package-Power sind nicht auf jeder Plattform standardisiert verfügbar und gehören derzeit nicht zu den überall garantierten Kernmetriken.

## NVIDIA GPU

Typische Messwerte:

- GPU-Auslastung
- VRAM-Nutzung
- Temperatur
- Leistungsaufnahme
- Power-Limit
- aktive Compute-Prozesse
- Treiber-/GPU-Metadaten

## AMD GPU

AMD-Telemetrie wird über `rocm-smi` erfasst, soweit vom System bereitgestellt.

## Baseline

Vor Lasttests versucht llmbench einen Ruhewert zu erfassen. Bleibt die GPU bereits vorher stark ausgelastet, wird das als möglicher Störfaktor markiert.

## Fremdprozesse

GPU-Prozesse, die nicht zum Benchmark gehören, können Messergebnisse verfälschen. Absichtlich parallel gestartete Benchmarkserver werden als eigene Prozesse registriert.

## Leistung und Temperatur gemeinsam lesen

Stabile tok/s, konstante Leistungsaufnahme und ein Temperaturplateau ohne Einbruch sprechen gegen offensichtliches thermisches Throttling. Ein sinkender Durchsatz bei steigender Temperatur kann ein Hinweis sein, muss aber zusammen mit Power-, Takt- und Backendverhalten bewertet werden.

## Rohdaten

Detaillierte Samples liegen in den jeweiligen `raw_*.json`-Dateien. `summary.json` enthält aggregierte Werte.
