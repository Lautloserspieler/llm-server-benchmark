# Troubleshooting

## Modell wurde heruntergeladen, aber als Fehler gemeldet

Aktuelle Versionen von `huggingface_hub` aktualisieren nach dem eigentlichen Download noch die Fortschrittsanzeige. llmbench prüft nach späten Progress-Fehlern erneut, ob das GGUF bereits vollständig lokal vorhanden ist.

Prüfen:

```bash
llmbench download --suite all --verify-only
```

## Modell wird nicht gefunden

Prüfe:

- Dateiendung `.gguf`
- vollständiges Shard-Set
- richtige Quantisierung
- `models/.llmbench-model-selection.json`
- Modell liegt im konfigurierten Modellordner

## OOM / VRAM reicht nicht

Normaler GPU-Modus sollte übergroße Full-GPU-Modelle konservativ überspringen.

Optionen:

- kleineres Modell
- stärkere Quantisierung
- Hybridprofil
- bewusst `gpu_overload`

## CPU-Test läuft extrem lange

Große Modelle auf CPU können Stunden benötigen. Der Benchmark besitzt getrennte CPU-/GPU-Timeouts; das Long-Preset erlaubt CPU-only-Läufen deutlich mehr Zeit.

## GPU zieht nicht das maximale Power-Limit

Ein Power-Limit ist nur eine Obergrenze. Nicht jeder Inferenzworkload erreicht diese Grenze.

Live prüfen:

```bash
watch -n 1 'nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,memory.used,power.draw,power.limit,clocks.gr --format=csv'
```

## GPU wird schon vor dem Test genutzt

Andere Compute-Prozesse schließen oder die Warnung dokumentieren. Fremdlast kann tok/s und Telemetrie verfälschen.

## llama-server startet nicht

`llmbench doctor` ausführen und Server-Log prüfen. Aktuelle Versionen melden frühe Serverabbrüche mit Exitcode und Logauszug.

## Docker sieht die NVIDIA-GPU nicht

Erst außerhalb von Docker prüfen:

```bash
nvidia-smi
```

Danach GPU-Zugriff im Container separat prüfen.

## Alte Auswahl enthält Qwen3.5-35B-A3B

Die Standardauswahl migriert diesen Slot automatisch auf `GLM-4.7-Flash`. Die alte GGUF-Datei wird nicht automatisch gelöscht.
