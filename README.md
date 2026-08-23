# LLM Server Benchmark

Reproduzierbares Benchmark-Tool für lokale LLM-Server und Workstations auf Basis von **llama.cpp**.

Ziel ist die direkte Vergleichbarkeit mehrerer Server unter identischen Bedingungen — und der **Nachweis**, dass die Bedingungen tatsächlich identisch waren.

- Prompt Processing / Input Tokens pro Sekunde
- Text Generation / Output Tokens pro Sekunde
- Long-Context-Performance bei 8K, 32K, 64K und ~128K belegtem Kontext
- CPU-, RAM-, GPU- und VRAM-Auslastung
- GPU-Leistungsaufnahme, Temperatur und Tokens/s pro Watt
- Full-GPU- und Hybrid-Profile
- parallele Requests / Multi-User-Tests
- TTFT P50 / P95
- System-TPS und Interactivity-TPS
- HTML-, CSV- und JSON-Berichte
- SHA256-Prüfung der GGUF-Dateien **und** der llama.cpp-Programmdateien
- automatische Konsistenzprüfung beim Vergleich mehrerer Serverläufe

## Version 1.2.0

Der Schwerpunkt dieser Version ist der Nachweis der Vergleichbarkeit. Bis 1.1.1 hat das Werkzeug korrekt gemessen, aber nicht festgehalten, *unter welchen Bedingungen*. Zwei Server konnten unbemerkt mit verschiedenen Einstellungen, verschiedenen llama.cpp-Builds oder verschiedenen Modelldateien verglichen werden.

Neu:

- Die tatsächlich verwendete Konfiguration, ein **Konfigurations-Fingerabdruck**, der llama.cpp-Build und der SHA256 von `llama-bench` landen in `summary.json`.
- `llmbench compare` prüft vor dem Vergleich, ob die Läufe überhaupt vergleichbar sind, und stellt Abweichungen an den Anfang des Berichts.
- Die automatische Erkennung durchsucht nur noch das Projekt, nicht mehr PATH und Systemordner.
- Endpoint-Tests laufen mit denselben Parametern wie `llama-bench`, mit festem Seed, fester Antwortlänge und Aufwärmläufen.
- Jeder Einzeltest hat ein Zeitlimit; das Web-Dashboard ist gegen Zugriffe von fremden Webseiten abgesichert.

Die vollständige Liste steht in `CHANGELOG.md`.

## Schnellstart

### Windows

```text
1. Repository herunterladen oder klonen
2. GGUF-Dateien nach models/ kopieren
3. START_BENCHMARK.bat ausführen
```

`START_BENCHMARK.bat` richtet bei Bedarf Python ein, lädt den passenden llama.cpp-Build herunter, erzeugt die Konfiguration und startet den Benchmark. Ist Python 3.10+ bereits vorhanden, genügt auch `setup.bat`.

### Linux und macOS

```bash
./setup.sh
```

`setup.sh` legt `.venv` an und installiert `llmbench` samt Web-Dashboard.

> **Wichtig:** Unter Linux und macOS wird llama.cpp **nicht** automatisch heruntergeladen. Lade `llama-bench` und `llama-server` von den [offiziellen Releases](https://github.com/ggml-org/llama.cpp/releases) oder baue sie selbst, und lege beide unter `tools/llama.cpp/` ab. Für einen Serververgleich auf allen Servern denselben Build verwenden — `llmbench compare` meldet Abweichungen.

### Web-Dashboard

```bash
pip install -e ".[web]"
python -m llmbench serve
```

Erreichbar unter `http://127.0.0.1:8000`. Der Server bindet an localhost und akzeptiert nur Anfragen aus der eigenen Oberfläche. Für den Zugriff aus dem Netz:

```bash
python -m llmbench serve --allow-remote
```

Dann wird beim Start ein Zugriffstoken ausgegeben, das jede Anfrage mitbringen muss. Alternativ ein eigenes Token über die Umgebungsvariable `LLMBENCH_TOKEN` setzen.

## Modelle

GGUF-Modelle werden nicht automatisch heruntergeladen — sie sind keine Programmabhängigkeit und oft viele Gigabyte groß.

```text
models/
  gemma-12b-q4_0.gguf
  gpt-oss-20b-q4_0.gguf
  qwen-27b-q4_0.gguf
```

Beim nächsten Start werden alle GGUF-Dateien unter `models/` erkannt und in `benchmark.yaml` eingetragen. Vorhandene Profile und manuelle Anpassungen bleiben erhalten. Dateien mit gleichem Namen in verschiedenen Unterordnern bekommen automatisch eindeutige Modellnamen, damit sich ihre Ergebnisse nicht gegenseitig überschreiben.

Modelldateien sind über `.gitignore` vom Repository ausgeschlossen.

## Reproduzierbarkeit

Für einen fairen Serververgleich müssen übereinstimmen:

1. dieselbe llama.cpp-Version,
2. exakt dieselben GGUF-Dateien,
3. dieselbe Quantisierung,
4. dieselbe Benchmark-Konfiguration,
5. möglichst derselbe Treiber- und Softwarestand.

### Was automatisch geprüft wird

Jeder Lauf schreibt in `summary.json`:

| Feld | Bedeutung |
| --- | --- |
| `config_fingerprint` | Hash über alle ergebnisrelevanten Einstellungen |
| `config` | die vollständige verwendete Konfiguration |
| `tools.llama_bench.binary.sha256` | Prüfsumme der Programmdatei |
| `tools.llama_cpp_build_ids` | Build-Commit und -Nummer aus llama.cpp selbst |
| `llmbench_version` | Version dieses Werkzeugs |
| `models[].model.sha256` | Prüfsumme jeder getesteten GGUF-Datei |

`llmbench compare` vergleicht diese Angaben über alle Läufe und meldet Abweichungen als Fehler oder Hinweis, bevor eine einzige Zahl gegenübergestellt wird.

Den Fingerabdruck eines Servers zeigt auch `llmbench doctor` an. Vor einer Vergleichsserie lohnt der kurze Blick: Auf allen Servern muss derselbe Wert stehen.

### llama.cpp wird bewusst eingefroren

Nach der ersten Installation wird llama.cpp **nicht** bei jedem Start aktualisiert, sonst könnten zwei Server unbemerkt mit verschiedenen Builds messen. Ein bewusstes Update erfolgt über `UPDATE_DEPENDENCIES.bat`. Für eine Vergleichsserie dieses Update auf allen Servern vor dem ersten Lauf durchführen und danach nicht mehr anfassen.

Die automatische Erkennung sucht ausschließlich in `tools/llama.cpp` und `bin/` innerhalb des Projekts. Sie greift **nicht** mehr auf das Arbeitsverzeichnis, den PATH oder Systemordner zu — genau das hatte zuvor dazu geführt, dass ein zufällig installiertes llama.cpp den eingefrorenen Build verdrängen konnte. Das alte Verhalten ist über `--allow-system-search` weiterhin erreichbar.

## NVIDIA-Treiber

Ein bestehender NVIDIA-Grafiktreiber wird **nicht** automatisch ersetzt. Die für den gewählten CUDA-Build nötigen CUDA-Runtime-DLLs werden dagegen automatisch installiert; ein separates CUDA Toolkit ist nicht erforderlich. Ohne NVIDIA-GPU installiert das Setup den CPU-Build.

## Benchmark-Suite

### Prompt Processing

Standardmäßig `pp512`, `pp4096`, `pp8192`. Messwert: **Input Tokens/s**.

### Text Generation

Standardmäßig `tg128`, `tg512`. Messwert: **Output Tokens/s**.

### Long Context

Standardmäßig 0, 8.192, 32.768, 65.536 und 130.000 Tokens Kontexttiefe. `llama-bench -d` füllt den KV-Cache tatsächlich bis zur jeweiligen Tiefe — gemessen wird also die Leistung bei real belegtem Kontext, nicht nur ein eingestelltes Kontextfenster.

Jeder Einzeltest ist über `benchmark.timeout_seconds` (Standard: 1 Stunde) begrenzt. Passt eine Kontexttiefe nicht in den Speicher, wird der Test als `timeout` vermerkt und der Lauf fortgesetzt, statt unbegrenzt zu hängen.

### Hardware-Telemetrie

Erfasst werden CPU, RAM, GPU-Auslastung, VRAM, Leistungsaufnahme und Temperatur, dazu der Windows-Energieplan bzw. der Linux-CPU-Governor.

GPU-Telemetrie wird über NVML gelesen und ist damit **NVIDIA-spezifisch**. AMD- und Intel-GPUs werden erkannt und im Bericht aufgeführt, liefern aber keine Auslastungs- und Leistungsdaten.

Weil NVML die gesamte Karte misst, erkennt der Monitor zusätzlich fremde Prozesse auf der GPU und erfasst einen Ruhewert vor der Last. Beides erscheint als Hinweis im Bericht — eine GPU, auf der noch etwas anderes lief, liefert keine belastbaren Vergleichswerte.

### Endpoint- und Multi-User-Test

Optional startet das Tool `llama-server` selbst und testet 1, 2, 4 und 8 parallele Requests. Der Server wird dabei mit denselben Kernparametern gestartet wie `llama-bench` (Batch, UBatch, Flash Attention, KV-Cache-Typen).

Gemessen werden System-TPS, Tokens/s pro Request, TTFT P50 und P95 sowie die Erfolgsquote.

Damit die Zahlen zwischen Läufen vergleichbar bleiben:

- `endpoint.warmup_requests` (Standard 2) wärmt den Server vor der Messung auf; diese Requests werden verworfen.
- `endpoint.ignore_eos` (Standard `true`) erzwingt eine feste Antwortlänge. Ohne das misst System-TPS teilweise, wie früh das Modell aufhört zu schreiben.
- `endpoint.seed` (Standard 42) hält das Sampling deterministisch.

## Konfiguration

Die Vorlage liegt in `benchmark.example.yaml`; beim ersten Start entsteht daraus `benchmark.yaml`. Diese Datei ist maschinenspezifisch und per `.gitignore` ausgeschlossen — geteilt wird die Vorlage.

Neue Modelle erhalten zunächst ein Full-GPU-Profil:

```yaml
profiles:
  - name: "Full-GPU"
    gpu_layers: -1
    threads: auto
```

Hybridprofile lassen sich ergänzen:

```yaml
profiles:
  - name: "Hybrid-30L-10T"
    gpu_layers: 30
    threads: 10
```

Profilnamen müssen je Modell eindeutig sein, Modellnamen im gesamten Projekt — `llmbench doctor` meldet Verstöße.

## CLI

```powershell
# Einrichtung
llmbench setup

# Vorabprüfung inklusive Konfigurations-Fingerabdruck
llmbench doctor --config benchmark.yaml

# Benchmark
llmbench run --config benchmark.yaml
llmbench run --config benchmark.yaml --model "Qwen-27B-Q4_0"

# Modellerkennung erneut ausführen
llmbench bootstrap --config benchmark.yaml --root . --llama-dir tools/llama.cpp --models-dir models

# Web-Dashboard
llmbench serve
```

Ohne Installation als Paket funktioniert auch `python -m llmbench ...` aus dem Projektordner.

`llmbench doctor` prüft zusätzlich, ob der installierte llama.cpp-Build alle benötigten Optionen kennt, ob die Modelle in den VRAM passen und ob genug Plattenplatz frei ist.

## Ergebnisse

Jeder Lauf erzeugt einen eigenen Ordner mit UTC-Zeitstempel:

```text
results/
  SERVERNAME_YYYYMMDD-HHMMSSZ/
    hardware.json
    summary.json          # Ergebnisse, Konfiguration, Build-Nachweis
    summary.partial.json  # Zwischenstand nach jedem Modell
    benchmarks.csv
    report.html
    MODELL/
      PROFIL/
        raw_prompt.json
        raw_generation.json
        raw_long_context.json
      endpoint/
        endpoint_load.json
        llama-server.log
```

Die `raw_*.json` enthalten den exakten Befehl, stdout, stderr, Laufzeit und die vollständige Telemetrie mit allen Einzelmesspunkten. `summary.json` enthält davon nur die Aggregate und bleibt dadurch auch nach mehrstündigen Läufen handhabbar.

## Mehrere Server vergleichen

```powershell
llmbench compare "results/ServerA_..." "results/ServerB_..." --out comparison
```

Erzeugt werden `comparison.html`, `comparison.csv`, `comparison.json` und — sofern Endpoint-Tests gelaufen sind — `comparison_endpoint.csv`.

Der Bericht beginnt mit der Konsistenzprüfung und enthält anschließend Hardware, Benchmark-Vergleich (inklusive Abstand zum jeweils besten Server), Endpoint-Vergleich und eine Effizienztabelle in Tokens/s pro Watt. Fehlgeschlagene und abgebrochene Tests sind als solche gekennzeichnet und verschwinden nicht als leere Zelle.

Für automatisierte Abläufe:

```powershell
llmbench compare "results/ServerA_..." "results/ServerB_..." --strict
```

`--strict` liefert Exitcode 1, sobald die Läufe nicht unter gleichen Bedingungen entstanden sind.

## Tests

```powershell
pip install -e ".[dev]"
pytest -q
ruff check .
```

## MLPerf-Einordnung

Dieses Projekt ist **kein** offizieller MLPerf-Submission-Runner. Es verwendet jedoch serverseitig sinnvolle Messgrößen wie Throughput, Interaktivität, TTFT und Parallelität für reproduzierbare interne Hardwarevergleiche.

- llama.cpp: https://github.com/ggml-org/llama.cpp
- llama-bench: https://github.com/ggml-org/llama.cpp/tree/master/tools/llama-bench
- MLPerf Endpoints: https://mlcommons.org/benchmarks/endpoints/

## Lizenz

MIT – siehe `LICENSE`.
