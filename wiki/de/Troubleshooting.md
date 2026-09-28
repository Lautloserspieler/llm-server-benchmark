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

## llama-server startet nicht

`llmbench doctor` ausführen und das Server-Log prüfen.

## Alte Auswahl enthält Qwen3.5-35B-A3B

Der Standardslot wird automatisch auf `GLM-4.7-Flash` migriert. Die alte GGUF-Datei wird nicht gelöscht.
