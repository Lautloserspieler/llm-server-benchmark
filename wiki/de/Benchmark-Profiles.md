[Deutsch](DE-Benchmark-Profiles) | [English](EN-Benchmark-Profiles)

---

# Benchmark-Profile

## CPU-only

```yaml
gpu_layers: 0
```

Für CPU-Vergleiche, RAM-Bandbreite und große Modelle außerhalb des VRAM.

## Full-GPU

```yaml
gpu_layers: -1
```

Im normalen `gpu`-Modus wird konservativ geprüft, ob das Modell zur erkannten VRAM-Kapazität passt.

## Hybrid

Teil-Offload ist sinnvoll, wenn das Modell nicht vollständig in VRAM passt.

## GPU Overload

```bash
llmbench run --hardware gpu_overload
```

Bewusster Grenztest für Unified Memory und übergroße Modelle. Nicht direkt mit normalen `gpu`-Runs vergleichen.

## Soak-Threadaufteilung

CPU- und GPU-Server teilen sich im kombinierten Soak-Test das CPU-Threadbudget standardmäßig ungefähr 75/25.

Beispiel bei 32 Threads:

```text
CPU-Server: 24
GPU-Server: 8
```

CPU und GPU besitzen getrennte Concurrency- und Timeout-Einstellungen.
