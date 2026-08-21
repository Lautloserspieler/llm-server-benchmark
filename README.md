# LLM Server Benchmark

Reproduzierbares Benchmark-Tool für lokale LLM-Server und Workstations auf Basis von **llama.cpp**.

Ziel ist die direkte Vergleichbarkeit von Servern unter identischen Bedingungen:

- Prompt Processing / Input Tokens pro Sekunde
- Text Generation / Output Tokens pro Sekunde
- Long-Context-Performance bei 8K, 32K, 64K und ~128K belegtem Kontext
- CPU-, RAM-, GPU- und VRAM-Auslastung
- GPU-Leistungsaufnahme und Temperatur
- Full-GPU- und Hybrid-Profile
- parallele Requests / Multi-User-Tests
- TTFT P50 / P95
- System-TPS und Interactivity-TPS
- HTML-, CSV- und JSON-Berichte
- SHA256-Prüfung der verwendeten GGUF-Dateien
- Vergleich mehrerer Serverläufe

## Version 1.1.1 – One-Click-Setup ohne winget

Unter Windows ist **kein manuelles Python- oder llama.cpp-Setup nötig**. `winget` wird für die Python-Installation nicht mehr benötigt.

Einfach:

```text
1. Repository herunterladen oder klonen
2. GGUF-Dateien nach models/ kopieren
3. START_BENCHMARK.bat starten
```

Der erste Start richtet das System automatisch ein.

### Was automatisch installiert bzw. eingerichtet wird

`START_BENCHMARK.bat` bzw. `scripts/START_BENCHMARK.ps1` erledigt automatisch:

1. Prüfung auf Python 3.10 oder neuer.
2. Falls Python fehlt: direkter Download des offiziellen Python-3.12.10-Installers von `python.org`.
3. SHA256-Prüfung des heruntergeladenen Python-Installers.
4. Projektlokale Installation unter `.runtime/python` – keine globale PATH-Änderung und keine systemweite Python-Installation erforderlich.
5. Erstellung einer isolierten `.venv`.
6. Installation/Aktualisierung aller benötigten Python-Pakete.
7. Erkennung einer NVIDIA-GPU über `nvidia-smi`.
8. Abfrage des neuesten offiziellen llama.cpp-Releases von GitHub.
9. Automatische Auswahl des passenden Windows-x64-Builds:
   - CUDA 13.3, wenn der Treiber CUDA 13 unterstützt,
   - sonst CUDA 12.4 bei NVIDIA,
   - CPU-Build, falls keine NVIDIA-GPU erkannt wird.
10. Download von `llama-bench` und `llama-server`.
11. Bei CUDA: Download der passenden CUDA-Runtime-DLLs. Ein separates CUDA Toolkit ist nicht notwendig.
12. Speicherung des verwendeten llama.cpp-Builds unter `tools/llama.cpp/.llama-build.json`.
13. Erstellung bzw. Aktualisierung von `benchmark.yaml`.
14. Automatische Erkennung aller `*.gguf`-Dateien unter `models/`.
15. Ausführung von `llmbench doctor` zur Vorprüfung.
16. Automatischer Start des Benchmarks, sobald mindestens ein Modell vorhanden ist.

### Python-Bootstrap

Wenn bereits Python 3.10+ vorhanden ist, verwendet das Setup die bestehende Installation zur Erstellung von `.venv`.

Wenn kein geeignetes Python vorhanden ist, wird **Python 3.12.10 direkt von python.org** geladen und ausschließlich für dieses Projekt nach

```text
.runtime/python/
```

installiert. Das Setup unterstützt Windows **x64** und **ARM64**. Der Download wird vor der Ausführung gegen eine fest hinterlegte SHA256-Prüfsumme aus den offiziellen Python-Release-Metadaten geprüft.

Damit funktioniert das Setup auch auf Systemen, auf denen Microsoft Store oder `winget` deaktiviert bzw. durch Unternehmensrichtlinien blockiert sind.

## Modelle

Die GGUF-Modelle werden nicht automatisch heruntergeladen, weil sie keine Programmabhängigkeit sind und häufig viele Gigabyte groß sind.

Lege sie einfach hier ab:

```text
models/
  gemma-12b-q4_0.gguf
  gpt-oss-20b-q4_0.gguf
  qwen-27b-q4_0.gguf
```

Beim nächsten Start werden alle GGUF-Dateien automatisch erkannt und in `benchmark.yaml` eingetragen. Bereits vorhandene Profile und manuelle Anpassungen bleiben erhalten.

Die Modelldateien werden durch `.gitignore` ausdrücklich vom Repository ausgeschlossen.

## Reproduzierbarkeit

Für einen fairen Serververgleich sollten verwendet werden:

1. dieselbe llama.cpp-Version,
2. exakt dieselben GGUF-Dateien,
3. dieselbe Quantisierung,
4. dieselbe Benchmark-Konfiguration,
5. möglichst derselbe Treiber-/Softwarestand.

Das Tool berechnet optional SHA256-Prüfsummen der Modelle. So kann nachgewiesen werden, dass auf mehreren Servern wirklich dieselbe Datei getestet wurde.

### llama.cpp wird bewusst eingefroren

Nach der ersten Installation wird llama.cpp **nicht bei jedem Start automatisch aktualisiert**. Sonst könnten zwei Server unbemerkt mit verschiedenen Builds getestet werden.

Ein bewusstes Update erfolgt über:

```text
UPDATE_DEPENDENCIES.bat
```

Dieses Skript aktualisiert die Python-Abhängigkeiten und lädt die aktuelle llama.cpp-Version erneut herunter. Für eine Vergleichsserie sollte dieses Update auf allen Servern vor dem ersten Lauf durchgeführt und danach nicht mehr verändert werden.

## NVIDIA-Treiber

Ein bestehender NVIDIA-Grafiktreiber wird **nicht automatisch ersetzt**. Ein Treiberwechsel kann Administratorrechte, einen Neustart und Auswirkungen auf andere Software haben.

Die für den ausgewählten llama.cpp-CUDA-Build notwendigen CUDA-Runtime-DLLs werden dagegen automatisch installiert.

Wenn keine NVIDIA-GPU bzw. kein `nvidia-smi` gefunden wird, installiert das Setup automatisch den CPU-Build von llama.cpp.

## Benchmark-Suite

### Prompt Processing

Standardmäßig:

- pp512
- pp4096
- pp8192

Messwert: **Input Tokens/s**.

### Text Generation

Standardmäßig:

- tg128
- tg512

Messwert: **Output Tokens/s**.

### Long Context

Standardmäßig:

- 0
- 8.192
- 32.768
- 65.536
- 130.000 Tokens Context Depth

`llama-bench -d` füllt den KV-Cache tatsächlich bis zur jeweiligen Tiefe. Damit wird nicht nur ein maximales Kontextfenster eingestellt, sondern die Leistung bei real belegtem Kontext gemessen.

### Hardware-Telemetrie

Während der Tests werden u. a. erfasst:

- CPU Ø / Max
- RAM Ø / Max
- GPU Ø / Max
- VRAM Ø / Max
- GPU-Leistungsaufnahme Ø / Max
- maximale GPU-Temperatur

NVIDIA-Telemetrie wird über NVML gelesen.

### Endpoint-/Multi-User-Test

Optional startet das Tool `llama-server` selbst und testet beispielsweise:

- 1 parallelen Request
- 2 parallele Requests
- 4 parallele Requests
- 8 parallele Requests

Gemessen werden:

- System TPS
- Tokens/s pro Request
- TTFT P50
- TTFT P95
- Erfolgs-/Fehlerquote

## Konfiguration

Die Standardkonfiguration befindet sich in:

```text
benchmark.example.yaml
```

Beim ersten Start wird daraus automatisch `benchmark.yaml` erzeugt bzw. ergänzt.

Neue Modelle erhalten zunächst ein Full-GPU-Profil:

```yaml
profiles:
  - name: "Full-GPU"
    gpu_layers: -1
    threads: auto
```

Zusätzliche Hybridprofile können anschließend ergänzt werden, zum Beispiel:

```yaml
profiles:
  - name: "Hybrid-30L-10T"
    gpu_layers: 30
    threads: 10
```

## CLI

Nach dem Setup steht das Tool in der virtuellen Umgebung zur Verfügung.

Installation prüfen:

```powershell
.\.venv\Scripts\python.exe -m llmbench doctor --config benchmark.yaml
```

Benchmark ausführen:

```powershell
.\.venv\Scripts\python.exe -m llmbench run --config benchmark.yaml
```

Nur ein Modell:

```powershell
.\.venv\Scripts\python.exe -m llmbench run --config benchmark.yaml --model "Qwen-27B-Q4_0"
```

Modellerkennung manuell erneut ausführen:

```powershell
.\.venv\Scripts\python.exe -m llmbench bootstrap --config benchmark.yaml --root . --llama-dir tools/llama.cpp --models-dir models
```

## Ergebnisse

Jeder Lauf erzeugt einen eigenen Ordner:

```text
results/
  SERVERNAME_YYYYMMDD-HHMMSS/
    hardware.json
    summary.json
    benchmarks.csv
    report.html
    MODEL/
      PROFIL/
        raw_prompt.json
        raw_generation.json
        raw_long_context.json
```

Die Rohdaten enthalten zusätzlich den exakten llama-bench-Befehl, stdout/stderr, Telemetrie und Laufzeit.

## Mehrere Server vergleichen

```powershell
.\.venv\Scripts\python.exe -m llmbench compare `
  "results/ServerA_..." `
  "results/ServerB_..." `
  --out comparison
```

Erzeugt werden:

- `comparison.html`
- `comparison.csv`
- `comparison.json`

## Tests

Die Python-Test-Suite kann mit folgendem Befehl ausgeführt werden:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

## MLPerf-Einordnung

Dieses Projekt ist **kein offizieller MLPerf-Submission-Runner**. Es verwendet jedoch sinnvolle serverseitige Messgrößen wie Throughput, Interaktivität, TTFT und Parallelität für reproduzierbare interne Hardwarevergleiche.

- llama.cpp: https://github.com/ggml-org/llama.cpp
- llama-bench: https://github.com/ggml-org/llama.cpp/tree/master/tools/llama-bench
- MLPerf Endpoints: https://mlcommons.org/benchmarks/endpoints/

## Lizenz

MIT – siehe `LICENSE`.
