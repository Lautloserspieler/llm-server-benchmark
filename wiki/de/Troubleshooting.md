[Deutsch](DE-Troubleshooting) | [English](EN-Troubleshooting)

---

# Troubleshooting

## Modell wurde heruntergeladen, aber als Fehler gemeldet

Aktuelle `huggingface_hub`-Versionen aktualisieren nach dem eigentlichen Download noch die Fortschrittsanzeige. llmbench prüft nach späten Progress-Fehlern erneut, ob das GGUF bereits vollständig lokal vorhanden ist.

```bash
llmbench download --suite all --verify-only
```

## Modell wird nicht gefunden

Prüfe:

- Dateiendung `.gguf`
- vollständiges Shard-Set
- richtige Quantisierung
- `models/.llmbench-model-selection.json`
- richtigen Modellordner

## OOM / VRAM reicht nicht

Optionen:

- kleineres Modell
- stärkere Quantisierung
- Hybridprofil
- bewusst `gpu_overload`

## CPU-Test läuft extrem lange

Große CPU-only-Modelle können Stunden benötigen. CPU und GPU besitzen getrennte Timeouts; das Long-Preset erlaubt CPU-Läufen deutlich mehr Zeit.

## GPU erreicht das Power-Limit nicht

Das Power-Limit ist nur eine Obergrenze. Nicht jeder Inferenzworkload erreicht sie.

```bash
nvidia-smi
```

## Fremdlast

Andere Compute-Prozesse schließen oder die Warnung dokumentieren. Fremdlast kann tok/s und Telemetrie verfälschen.

## Vulkan statt CUDA auf einer NVIDIA-Karte

Auf NVIDIA-Karten ist ein Vulkan-Build von llama.cpp erfahrungsgemäß deutlich langsamer als CUDA. llmbench lässt das deshalb nie unbemerkt zu:

- Der Block „Nachweis der Testbedingungen“ zeigt die **GPU-API**, die die Binärdatei wirklich meldet (`cuda`, `vulkan`, ...), gelesen aus `--list-devices`, nicht nur das Angeforderte.
- Bei einer NVIDIA-GPU und einem Vulkan-/CPU-Build gibt der Lauf eine Warnung aus und speichert sie im Ergebnis; die Werte sind dann nicht mit CUDA-Messungen vergleichbar.
- Wenn du **CUDA anforderst**, ist ein Vulkan- oder CPU-Build ein Fehler: Der Lauf stoppt vor der Messung, statt still mit Vulkan zu messen.

Für CUDA das CUDA Toolkit (`nvcc`) installieren und ausdrücklich bauen:

```bash
llmbench install-llama-cpp --backend cuda --force
```

`--backend` akzeptiert `auto`, `cuda`, `vulkan` und `cpu`. Dieselbe Wahl geht über `LLMBENCH_LLAMACPP_BUILD_BACKEND`. Der Installer speichert das Angeforderte neben dem Installierten (`.llama-build.json`).

## llama-server startet nicht

`llmbench doctor` ausführen und das Server-Log prüfen.

## Alte Auswahl enthält Qwen3.5-35B-A3B

Der Standardslot wird automatisch auf `GLM-4.7-Flash` migriert. Die alte GGUF-Datei wird nicht gelöscht.
