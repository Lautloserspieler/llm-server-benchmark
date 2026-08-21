# LLM Server Benchmark

Ein reproduzierbares Benchmark-Programm für lokale LLM-Server auf Basis von **llama.cpp**.

Ziel ist nicht, einzelne Modelle „zu bewerten“, sondern Server und Workstations unter identischen Bedingungen vergleichbar zu machen:

- Welche GGUF-Modelle laufen auf dem System?
- Wie schnell ist die Prompt-Verarbeitung?
- Wie schnell ist die reine Token-Generierung?
- Wie verändert sich die Leistung bei 8K / 32K / 64K / ~128K belegtem Kontext?
- Wie viel CPU, RAM, GPU, VRAM und Leistungsaufnahme werden benötigt?
- Wie verhält sich ein echter LLM-Server bei mehreren parallelen Nutzern?
- Wie schneiden mehrere Server mit exakt denselben Modelldateien gegeneinander ab?

## Wichtiges Messprinzip

Für einen fairen Vergleich müssen auf allen Servern verwendet werden:

1. dieselbe `llama.cpp`-Version,
2. exakt dieselben GGUF-Dateien,
3. dieselbe Quantisierung,
4. dieselbe Benchmark-Konfiguration,
5. möglichst derselbe GPU-Treiber-/Softwarestand.

Das Programm berechnet optional die **SHA256-Prüfsumme** jeder GGUF-Datei. Dadurch kann später belegt werden, dass auf zwei Servern wirklich dieselbe Datei getestet wurde.

## Enthaltene Tests

### 1. Prompt Processing

Standardmäßig:

- pp512
- pp4096
- pp8192

Messwert: **Input Tokens/s**.

Dieser Test ist besonders relevant für RAG, Dokumentenanalyse und große Prompts.

### 2. Text Generation

Standardmäßig:

- tg128
- tg512

Messwert: **Output Tokens/s**.

Dieser Wert beschreibt die reine Generierungsleistung des Inferenzkerns. `llama-bench` schließt Tokenisierung und Sampling aus; deshalb ist er ideal für Hardwarevergleiche, aber nicht identisch mit der vollständigen Endnutzer-Latenz.

### 3. Long Context

Standardmäßig werden Context Depths getestet bei:

- 0
- 8.192
- 32.768
- 65.536
- 130.000 Tokens

`llama-bench -d` füllt den KV-Cache tatsächlich bis zur jeweiligen Tiefe. Damit wird nicht nur ein maximales Kontextfenster eingestellt, sondern die Leistung bei belegtem Kontext gemessen.

### 4. Hardware-Telemetrie

Während jedes Tests werden erfasst:

- CPU-Auslastung Ø / Max
- RAM-Nutzung Ø / Max
- GPU-Auslastung Ø / Max
- VRAM-Nutzung Ø / Max
- GPU-Leistungsaufnahme Ø / Max
- maximale GPU-Temperatur

NVIDIA-Telemetrie wird über NVML (`nvidia-ml-py`) gelesen.

### 5. Endpoint-/Multi-User-Test

Optional kann das Programm `llama-server` selbst starten und den nativen Streaming-Endpunkt unter Last testen.

Standardmäßig können z. B. folgende Parallelitätsstufen verwendet werden:

- 1 Nutzer
- 2 Nutzer
- 4 Nutzer
- 8 Nutzer

Gemessen werden:

- **System TPS** – gesamte ausgegebene Tokens/s über alle Requests,
- **Interactivity TPS** – durchschnittliche Tokens/s pro Request,
- **TTFT P50**,
- **TTFT P95**,
- erfolgreiche/fehlgeschlagene Requests.

Diese Metriken orientieren sich an der Art von Messgrößen, die auch bei serverseitigen LLM-Benchmarks wie MLPerf Endpoints relevant sind.

Prompt-Caching wird für den automatisch gestarteten `llama-server` deaktiviert, damit wiederholte Benchmark-Requests nicht künstlich durch Cache-Treffer beschleunigt werden.

## Voraussetzungen

- Windows 10/11 oder Linux
- Python 3.10 oder neuer
- NVIDIA-Treiber für NVIDIA-GPUs
- CUDA-fähiger Build von `llama.cpp`
- `llama-bench` und für Endpoint-Tests `llama-server`
- lokale GGUF-Modelldateien

## Windows – Schnellstart

### 1. ZIP entpacken

Zum Beispiel nach:

```text
C:\LLMBenchmark
```

### 2. llama.cpp bereitstellen

Trage die Pfade in `benchmark.yaml` ein, beispielsweise:

```yaml
tools:
  llama_bench: "C:/llama.cpp/llama-bench.exe"
  llama_server: "C:/llama.cpp/llama-server.exe"
```

Verwende für alle zu vergleichenden Systeme möglichst denselben llama.cpp-Build.

### 3. Erster Start

PowerShell im Projektordner:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\START_BENCHMARK.ps1
```

Beim ersten Aufruf wird:

- `.venv` erstellt,
- das Programm installiert,
- `benchmark.yaml` aus dem Beispiel erzeugt, falls es noch nicht existiert.

Danach Modellpfade anpassen und das Skript erneut starten.

## Manuelle Installation

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
Copy-Item benchmark.example.yaml benchmark.yaml
```

Dann:

```powershell
llmbench doctor --config benchmark.yaml
```

und:

```powershell
llmbench run --config benchmark.yaml
```

Alternativ ohne installierten CLI-Alias:

```powershell
python -m llmbench run --config benchmark.yaml
```

## Nur ein Modell testen

```powershell
llmbench run --config benchmark.yaml --model "Qwen-27B-Q4_0"
```

## Endpoint-Test überspringen

```powershell
llmbench run --config benchmark.yaml --skip-endpoint
```

## Ergebnisse

Jeder Lauf erzeugt einen eigenen Ordner, z. B.:

```text
results/
  RTX-PRO-4000-Blackwell-Testserver_20260821-161500/
    hardware.json
    summary.json
    benchmarks.csv
    report.html
    Gemma-12B-Q4_0/
      Full-GPU/
        raw_prompt.json
        raw_generation.json
        raw_long_context.json
      ...
```

### `report.html`

Direkt lesbarer Bericht pro Server.

### `benchmarks.csv`

Flache Tabelle für Excel, Power BI oder weitere Auswertung.

### `summary.json`

Maschinenlesbare Zusammenfassung für automatische Vergleiche.

### `raw_*.json`

Enthält zusätzlich:

- exakten ausgeführten Befehl,
- stdout/stderr von llama-bench,
- Roh-Telemetrie,
- Laufzeit.

Damit bleiben Ergebnisse nachvollziehbar.

## Mehrere Server vergleichen

Kopiere die Ergebnisordner der verschiedenen Server auf einen Rechner und führe aus:

```powershell
llmbench compare `
  "results/ServerA_20260821-120000" `
  "results/ServerB_20260821-130000" `
  "results/ServerC_20260821-140000" `
  --out comparison
```

Erzeugt werden:

```text
comparison/
  comparison.html
  comparison.csv
  comparison.json
```

Der HTML-Bericht stellt identische Modell-/Profil-/Testkombinationen direkt nebeneinander.

## Profile: Full GPU und Hybrid

Jedes Modell kann mehrere Ausführungsprofile besitzen:

```yaml
profiles:
  - name: "Full-GPU"
    gpu_layers: -1
    threads: auto

  - name: "Hybrid-30L-10T"
    gpu_layers: 30
    threads: 10
```

Dadurch können Full-GPU- und CPU/RAM/GPU-Hybridbetrieb sauber getrennt werden.

### Zusätzliche llama-bench-Argumente

Für Sonderfälle:

```yaml
profiles:
  - name: "Custom"
    gpu_layers: 30
    threads: 10
    additional_args:
      - "--no-host"
      - "0"
```

## Endpoint-Test aktivieren

Global:

```yaml
endpoint:
  enabled: true
  auto_start: true
  base_url: "http://127.0.0.1:8080"
  context_size: 32768
  parallel_slots: 8
  concurrency: [1, 2, 4, 8]
  requests_per_level: 8
  max_tokens: 256
```

Pro Modell kann er überschrieben werden:

```yaml
- name: "Qwen-27B-Q4_0"
  path: "C:/Models/qwen-27b-q4_0.gguf"
  endpoint:
    enabled: true
    profile: "Hybrid-30L-10T"
```

Ist `auto_start: false`, erwartet das Programm einen bereits laufenden kompatiblen `llama-server` unter `base_url`.

## Quality Gate

Die bisherige Dokumentenprüfung bleibt bewusst getrennt vom Hardwarebenchmark.

In der Konfiguration kann das bekannte Ergebnis dokumentiert werden:

```yaml
quality_gate: "Bestanden"
```

Das Programm verwendet diesen Wert nur als Hinweis im Report. Es lässt die Antwortqualität **nicht automatisch von einem zweiten LLM bewerten**, weil dies die Reproduzierbarkeit des Hardwarebenchmarks verschlechtern würde.

## Empfohlener Ablauf für eure Server

1. Referenz-GGUF-Dateien auf alle Systeme kopieren.
2. SHA256 vergleichen.
3. Dieselbe llama.cpp-Version installieren.
4. `llmbench doctor` ausführen.
5. Benchmark ohne andere GPU-Last starten.
6. Ergebnisordner sichern.
7. Auf nächstem Server wiederholen.
8. Mit `llmbench compare` gemeinsam auswerten.

## Warum `llama-bench`?

`llama-bench` ist das Performance-Testwerkzeug von llama.cpp. Es unterstützt getrennte Prompt-Processing-, Text-Generation- und kombinierte Tests, mehrere Wiederholungen, Kontexttiefe (`-d`) sowie JSON/CSV-Ausgabe.

Projekt: https://github.com/ggml-org/llama.cpp

Dokumentation: https://github.com/ggml-org/llama.cpp/tree/master/tools/llama-bench

## MLPerf-Einordnung

Dieses Tool ist **kein offizieller MLPerf-Submission-Runner**. Es übernimmt aber sinnvolle serverseitige Messgrößen wie Durchsatz, Interaktivität, TTFT und Parallelität, um interne Serververgleiche verständlich zu machen.

Offizielle MLPerf-Ergebnisse und Regeln stammen von MLCommons:

https://mlcommons.org/benchmarks/endpoints/

## Hinweise zur Vergleichbarkeit

- Tokens/s aus unterschiedlichen Runtimes (z. B. Ollama vs. LM Studio vs. llama.cpp) nicht direkt als identischen Benchmark behandeln.
- „Context Size = 131072“ ist nicht dasselbe wie 131072 tatsächlich belegte Tokens. Deshalb nutzt der Long-Context-Test `llama-bench -d`.
- Ein fehlgeschlagener Full-GPU-Test ist ebenfalls ein Ergebnis: Das Modell passt unter den gewählten Bedingungen nicht vollständig in die gewünschte Konfiguration.
- Für Kundenberichte Modellqualität und Hardwareperformance getrennt darstellen.

## Lizenz

MIT – siehe `LICENSE`.
