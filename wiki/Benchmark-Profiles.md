# Benchmark-Profile

## CPU-only

```yaml
gpu_layers: 0
```

Das Modell wird ohne GPU-Offload getestet.

Geeignet für:

- CPU-Vergleiche
- RAM-Bandbreite
- große Modelle außerhalb des VRAM
- Referenz gegen GPU-Offload

## Full-GPU

```yaml
gpu_layers: -1
```

llmbench versucht, das Modell vollständig über die GPU zu betreiben.

Im normalen `gpu`-Modus wird vorher konservativ geprüft, ob Modellgröße und erkannter VRAM zusammenpassen.

## Hybrid

Ein begrenzter positiver Wert für `gpu_layers` kann Teil-Offload abbilden. Das ist interessant, wenn ein Modell nicht vollständig in VRAM passt.

## GPU Overload

```bash
llmbench run --hardware gpu_overload
```

Dieser Modus ist ein **Stresstest**. Er überschreitet den konservativen VRAM-Preflight bewusst.

Geeignet für:

- Unified Memory
- Grenztests
- Oversized-Modelle

Nicht direkt mit normalen `gpu`-Runs vergleichen.

## Soak-Threadaufteilung

Beim kombinierten CPU/GPU-Soak-Test dürfen sich CPU-only- und GPU-Server nicht gegenseitig alle Threads wegnehmen.

Standardmäßig wird das Threadbudget ungefähr 75/25 geteilt.

Beispiel bei 32 verfügbaren Threads:

```text
CPU-Server: 24 Threads
GPU-Server: 8 Threads
```

Die Werte können über die Soak-Konfiguration angepasst werden.

## Concurrency und Timeouts

CPU und GPU besitzen getrennte Concurrency- und Request-Timeout-Einstellungen. Das ist wichtig, weil CPU-only-Inferenz großer Modelle um Größenordnungen langsamer sein kann.
