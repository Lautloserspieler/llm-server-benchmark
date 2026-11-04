# LLM Server Benchmark

🇩🇪 Deutsch | [🇬🇧 English](README.md)

**Reproduzierbares Benchmarking für lokale LLM-Inferenz mit llama.cpp und containerisierten Server-Backends.**

[![Tests](https://github.com/Lautloserspieler/llm-server-benchmark/actions/workflows/tests.yml/badge.svg)](https://github.com/Lautloserspieler/llm-server-benchmark/actions/workflows/tests.yml)
[![Security](https://github.com/Lautloserspieler/llm-server-benchmark/actions/workflows/security.yml/badge.svg)](https://github.com/Lautloserspieler/llm-server-benchmark/actions/workflows/security.yml)
[![Docker](https://github.com/Lautloserspieler/llm-server-benchmark/actions/workflows/docker-image.yml/badge.svg)](https://github.com/Lautloserspieler/llm-server-benchmark/actions/workflows/docker-image.yml)
[![OpenSSF Scorecard](https://github.com/Lautloserspieler/llm-server-benchmark/actions/workflows/scorecard.yml/badge.svg)](https://github.com/Lautloserspieler/llm-server-benchmark/actions/workflows/scorecard.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

LLM-Benchmark-Ergebnisse werden häufig auf eine einzelne Zahl wie **84 tok/s** reduziert. Diese Zahl ist jedoch nur dann aussagekräftig, wenn die Rahmenbedingungen bekannt sind.

**LLM Server Benchmark** speichert Hardware, Treiber, Backend, Modelldateien, Quantisierung, Benchmark-Einstellungen, Ausführungsumgebung und Telemetrie gemeinsam mit dem Leistungsergebnis. Ziel ist es, Vergleiche lokaler LLM-Server **wiederholbar, überprüfbar und belastbar** zu machen.

---

## Community & Support

GitHub Discussions ist der bevorzugte Ort für Community-Themen:

- **Fragen und Troubleshooting:** nutze [Q&A](https://github.com/Lautloserspieler/llm-server-benchmark/discussions/categories/q-a)
- **Benchmark-Ergebnisse:** teile und vergleiche Ergebnisse unter [Benchmark Results](https://github.com/Lautloserspieler/llm-server-benchmark/discussions/categories/benchmark-results) und nutze die [Benchmark-Ergebnisvorlage](https://github.com/Lautloserspieler/llm-server-benchmark/discussions/84)
- **Ideen und frühe Vorschläge:** nutze [Ideas](https://github.com/Lautloserspieler/llm-server-benchmark/discussions/categories/ideas)
- **Hardware-, Betriebssystem-, Treiber- und CUDA-Themen:** nutze [Hardware & OS](https://github.com/Lautloserspieler/llm-server-benchmark/discussions/categories/hardware-os)
- **Bugs und konkrete Feature Requests:** öffne ein GitHub Issue

Discussions sind sowohl auf **Deutsch als auch auf Englisch** willkommen.

---

## Highlights

- Reproduzierbare lokale LLM-Benchmarks statt isolierter Tokens/s-Zahlen
- Natives **llama.cpp**-Benchmarking
- Unterstützung für das containerisierte **vLLM**-Backend
- NVIDIA-GPU-Telemetrie über NVML
- AMD-GPU-Telemetrie über `rocm-smi`
- CPU-only-, GPU- und Hybrid-Benchmarkprofile
- Durchsatz für Prompt-Verarbeitung und Textgenerierung
- Long-Context-Benchmarks mit befülltem KV-Cache
- Endpoint-/Lasttests mit TTFT und Concurrency-Messungen
- Stress-, Soak-, OOM-, Multi-Tenant- und Quantisierungstests
- HTML-, PDF-, CSV- und JSON-Berichte
- Lokaler bereinigter [Community-JSON-Export](docs/community-export.de.md) mit exakter Vorschau, isolierten Batch-Fehlern und Offline-Pruefung
- Fingerprints für Modelle, Binaries und Konfiguration
- Maschinenübergreifender Vergleich mit strikter Reproduzierbarkeitsprüfung
- Starter für Windows, Linux und macOS
- Docker-Image mit SBOM, Provenance und Schwachstellen-Scanning
- CI mit Python 3.10–3.14 unter Windows und Linux

---

## Warum dieses Projekt existiert

Ein nützliches Benchmark-Ergebnis sollte mehr beantworten als:

> Wie viele Tokens pro Sekunde hat das Modell generiert?

Es sollte außerdem beantworten:

- Welche genaue CPU und GPU haben das Ergebnis erzeugt?
- Welcher Treiber und welche GPU-Runtime waren aktiv?
- Wurde tatsächlich CUDA, ROCm, Vulkan, Metal oder CPU-Ausführung verwendet?
- Welches Backend und welcher Backend-Build wurden getestet?
- Welche exakten Modelldateien und welche Quantisierung wurden verwendet?
- Haben beide Maschinen identische Benchmark-Einstellungen genutzt?
- Wie hoch waren VRAM-Nutzung, Leistungsaufnahme und Temperatur?
- Hat ein anderer Prozess GPU-Ressourcen verbraucht?
- Wie verändert sich die Leistung bei langem Kontext oder parallelen Requests?
- Kann jemand anderes dieselbe Messung reproduzieren?

`llmbench` speichert diese Nachweise zusammen mit der Benchmark-Ausgabe.

---

## Support-Matrix

### Inferenz-Backends

| Backend | Status | Ausführung | Hinweise |
| --- | --- | --- | --- |
| **llama.cpp** | ✅ Unterstützt | Nativ | Referenz-Backend mit `llama-bench` und `llama-server` |
| **vLLM** | ✅ Unterstützt | Docker | OpenAI-kompatibles Serving-Backend |
| **TGI** | 🧪 Beta | Docker | Implementiert; ausführliche Praxistests stehen noch aus |
| **Ollama** | ✅ Unterstützt | Docker | Native API; CPU und GPU |

### GPU-Telemetrie

| Plattform | Status | Telemetriequelle |
| --- | --- | --- |
| **NVIDIA** | ✅ Unterstützt | NVML / `nvidia-ml-py`, `nvidia-smi` |
| **AMD** | ✅ Unterstützt | `rocm-smi --json` |
| **Intel GPU** | 📋 Geplant | `xpu-smi` |
| **Apple Silicon** | ✅ Benchmark-Ausführung | Plattform-llama.cpp-Build; Telemetrie eingeschränkter |

Siehe [ROADMAP.md](ROADMAP.md) für den aktuellen Entwicklungsplan.

---

## Was llmbench misst

### Kern-Inferenz

- Prompt-Verarbeitung / Eingabetokens pro Sekunde
- Textgenerierung / Ausgabetokens pro Sekunde
- Long-Context-Leistung
- CPU-only-, GPU- und Hybrid-Ausführungsprofile
- Wiederholte Läufe zur Messung der Streuung

### Interaktives Serving

- Systemdurchsatz
- Tokens/s pro Request
- TTFT P50 / P95
- Request-Erfolgsrate
- Konfigurierbare Concurrency-Stufen
- Endpoint-/Server-Verhalten unter Last

### Stress und Kapazität

- Kurze und lange Soak-Tests
- Hinweise auf thermisches Throttling
- TTFT-Stress
- Multi-Tenant-/Zwei-Modell-Last
- KV-Cache- und Kontextlimit-/OOM-Tests
- Quantisierungsvergleiche desselben Basismodells

### Hardware-Telemetrie

- CPU-Auslastung
- RAM-Auslastung
- GPU-Auslastung
- VRAM-Nutzung
- GPU-Temperatur
- NVIDIA-Leistungsaufnahme
- Erkennung fremder/Hintergrund-GPU-Prozesse
- Erfassung von Linux-CPU-Governor und Power-Profil

---

## Schnellstart

### Windows

**PowerShell** öffnen und Repository klonen:

```powershell
git clone https://github.com/Lautloserspieler/llm-server-benchmark.git
cd llm-server-benchmark
```

Setup starten:

```powershell
.\setup.bat
```

Das Setup prüft die benötigten Komponenten und führt durch fehlende Abhängigkeiten wie Python 3.10+, WSL2, Docker Desktop und GPU-Voraussetzungen. Systemändernde Installationen benötigen eine Bestätigung, sofern die automatische Installation nicht ausdrücklich aktiviert wurde.

Nach dem Setup den Benchmark-Starter ausführen:

```powershell
.\START_BENCHMARK.bat
```

Der Starter lässt anschließend Benchmark-Dauer, Hardware-Modus und weitere verfügbare Optionen auswählen.

Falls die Skriptausführung in PowerShell eingeschränkt ist, können die `.bat`-Starter auch aus der Eingabeaufforderung gestartet werden:

```cmd
setup.bat
START_BENCHMARK.bat
```

Die Sprache kann während des Setups ausgewählt oder vor dem Start erzwungen werden:

```powershell
$env:LLMBENCH_LANG = "de"
# oder
$env:LLMBENCH_LANG = "en"

.\setup.bat
```

### Linux

```bash
git clone https://github.com/Lautloserspieler/llm-server-benchmark.git
cd llm-server-benchmark

chmod +x setup.sh START_BENCHMARK.sh
./setup.sh
./START_BENCHMARK.sh
```

Für native NVIDIA-CUDA-Builds müssen ein funktionierender NVIDIA-Treiber und das CUDA Toolkit installiert sein, sodass `nvcc` verfügbar ist.

### macOS

```bash
git clone https://github.com/Lautloserspieler/llm-server-benchmark.git
cd llm-server-benchmark

chmod +x setup.sh START_BENCHMARK.sh
./setup.sh
./START_BENCHMARK.sh
```

Apple-Silicon-Beschleunigung wird durch den plattformeigenen llama.cpp-Build bereitgestellt.

---

# Kurzer Test aller Backends

`SMOKE_ALL_BACKENDS.bat` unter Windows oder `bash SMOKE_ALL_BACKENDS.sh` unter Linux starten. Der Starter richtet bei Bedarf eine `.venv` mit den Python-Projektabhaengigkeiten ein. Der Test prueft llama.cpp, Ollama, vLLM und TGI nacheinander. Im Terminal zeigen Fortschrittsbalken die abgeschlossenen Backends und Testphasen; ein Timer laeuft auch waehrend Modellvorbereitung und Serverstart weiter. Bei umgeleiteter Ausgabe oder `--no-progress` erscheinen einfache Phasenmeldungen.

Jedes Backend durchlaeuft Voraussetzungen, automatische Installation/Vorbereitung, Modellvorbereitung, Serverstart, Health-Check, kurze gestreamte Textgenerierung und Aufraeumen. Standardmaessig wird fuer llama.cpp und Ollama eine verfuegbare GPU verwendet; nur ohne passende GPU wird die CPU gewaehlt. vLLM und TGI brauchen NVIDIA-GPU-Unterstuetzung in Docker. `--device gpu` verlangt GPU-Ausfuehrung; `--device cpu` waehlt CPU fuer llama.cpp/Ollama und ueberspringt vLLM/TGI. Die Ergebnistabelle zeigt das gewaehlte Geraet. Das ist ein Funktionscheck und liefert keine vergleichbaren Performancewerte. Der Test verwendet feste kleine Kontext-/Batch-Einstellungen; Chatformat und zusaetzliche Serverargumente aus der Benchmark-Konfiguration werden nicht uebernommen. `benchmark.yaml` bleibt unveraendert.

Fuer llama.cpp wird Gemma 3 1B Q4_K_M (ca. 0.8 GB) bei Bedarf nach `models/` geladen. Ollama nutzt `gemma3:1b`, vLLM/TGI nutzen `Qwen/Qwen2.5-0.5B-Instruct`. Modelle bleiben im jeweiligen Cache. Fehlende Backends werden automatisch vorbereitet: llama.cpp wird mit dem vorhandenen Installer installiert, die konfigurierten Docker-Images werden bei Bedarf geladen. Installationsmeldungen und Downloadfortschritt erscheinen waehrend der Setup-Phase. Dafuer sind Netzwerkzugriff und gegebenenfalls Build-Werkzeuge erforderlich. Ein Installationsfehler wird als `failed` gemeldet, die anderen Backends werden weiter getestet. `--no-install` deaktiviert diese Vorbereitung und ueberspringt fehlende Installationen. Fehlendes Docker oder fehlende GPU-Unterstuetzung bleiben als `skipped` sichtbar. Vorhandene Benchmark-Container bleiben unberuehrt; Smoke-Container erhalten eigene eindeutige Namen und werden nach dem Test entfernt. Die lokale HTTP-Adresse aus `endpoint.base_url` verwendet standardmaessig Port 8080. Ist dieser belegt, wird automatisch ein freier Port gewaehlt und im Bericht gespeichert. Nur ein ausdrueckliches `--base-url` verlangt genau den angegebenen Port.

```bash
# Nur ausgewaehlte Backends, mit eigenem Port
bash SMOKE_ALL_BACKENDS.sh --backends ollama vllm --base-url http://127.0.0.1:18080

# Vorhandene GGUF-Datei verwenden, Zeitlimits anpassen
python scripts/smoke_all_backends.py --backends llama_cpp --gguf /pfad/modell.gguf --startup-timeout 900 --request-timeout 180

# Geeignet fuer CI: auch uebersprungene Backends beanstanden
python scripts/smoke_all_backends.py --no-install --strict --no-progress --output results/mein-smoke
```

`--startup-timeout` gilt fuer die Serverbereitschaft und bei Ollama auch pro Modell-Pull-Anfrage (Standard: 600 Sekunden). Es ist kein Gesamtlimit fuer Downloads und den gesamten Lauf. `--request-timeout` begrenzt die gesamte Textgenerierung (Standard: 120 Sekunden). Fuer vLLM setzt der Smoke-Test `--gpu-memory-utilization 0.5`, `--enforce-eager` und maximal eine gleichzeitige Sequenz. Damit reserviert der kleine Test standardmaessig 50 % des gesamten GPU-Speichers. Bei Bedarf laesst sich der Anteil mit `--gpu-memory-utilization 0.35` anpassen; der Anteil bezieht sich auf den gesamten, nicht den freien VRAM. Auch dieser reduzierte Anteil muss beim Start frei sein. Waehrend der Bereitschaftspruefung wird der Containerstatus kontrolliert: Ein beendeter Container wird mit Exitcode und Logauszug sofort als Fehler gemeldet. Der Start zeigt den eindeutigen Containernamen und den passenden `docker logs -f`-Befehl an.

TGI verwendet fuer den Smoke-Test ein begrenztes Profil: eine Anfrage/ein Batch, 128 Eingabetokens, 256 Gesamttokens, deaktivierte CUDA-Graphen und den allgemeinen Transformers-Pfad auf der GPU ohne FlashAttention/FlashInfer und Prefix-Cache. Die GPU-Speicherfraktion betraegt 0.5; der Container ist auf 12 GiB RAM ohne zusaetzlichen Swap begrenzt. Diese Einstellungen gelten nur fuer den Smoke-Test und verhindern den unbeschraenkten Standard-Warmup.

Eine Ergebnistabelle fasst Status, Dauer und Fehlerphase zusammen. `results/backend-smoke/report.json` wird nach jedem Backend atomar aktualisiert und enthaelt auch Phasenlaufzeiten, Logpfad, Containername und getrennte Aufraeumfehler. Server-Logs liegen daneben; auch nach einem fehlgeschlagenen Containerstart werden sie vor dem Entfernen gesichert. Erneute Laeufe im selben Ausgabeverzeichnis ersetzen den Bericht und die Logs getesteter Backends. Nutze fuer getrennte Laeufe unterschiedliche `--output`-Verzeichnisse. Bei Strg+C wird das aktuelle Backend aufgeraeumt, als `aborted` gespeichert und der Lauf beendet.

Exitcodes: `0` = mindestens ein Backend erfolgreich und keine Fehler, `1` = Fehler (mit `--strict` auch teilweise uebersprungene Backends), `2` = alle Backends uebersprungen oder ungueltige CLI-Argumente, `130` = Benutzerabbruch.

## Manuelle Python-Installation

Für Entwicklung oder manuelle CLI-Nutzung:

```bash
git clone https://github.com/Lautloserspieler/llm-server-benchmark.git
cd llm-server-benchmark

python -m venv .venv
```

Umgebung aktivieren:

**Windows**

```powershell
.\.venv\Scripts\Activate.ps1
```

**Linux/macOS**

```bash
source .venv/bin/activate
```

Projekt installieren:

```bash
python -m pip install --upgrade pip
pip install -e .
```

Installation prüfen:

```bash
llmbench --version
llmbench --help
```

---

## Typischer Ablauf

Ein normaler Benchmark-Ablauf sieht so aus:

```bash
# 1. Konfiguration, Tools, Hardware und Modellpfade prüfen
llmbench doctor --config benchmark.yaml

# 2. Lokale Tools und Modelle erkennen
llmbench bootstrap \
  --config benchmark.yaml \
  --root . \
  --llama-dir tools/llama.cpp \
  --models-dir models

# 3. Benchmark ausführen
llmbench run --config benchmark.yaml --hardware gpu --duration medium

# 4. Optional die Stress-Suite einschließen
llmbench run --config benchmark.yaml --hardware gpu --duration medium --stress

# 5. Zwei Systeme vergleichen
llmbench compare \
  "results/ServerA_..." \
  "results/ServerB_..." \
  --out comparison

# 6. Vergleiche mit inkompatiblen Bedingungen ablehnen
llmbench compare \
  "results/ServerA_..." \
  "results/ServerB_..." \
  --strict
```

`llmbench compare` verwendet für das Energieeffizienz-Ranking die gespeicherten Werte `tokens_per_joule` und `wh_per_1k_tokens`, wenn alle verglichenen Systeme denselben Messumfang und dieselbe Komponentenabdeckung besitzen. Unterschiedliche Scopes (zum Beispiel nur GPU gegenüber CPU-Paket + GPU) werden als nicht vergleichbar gemeldet und nicht gegeneinander gerankt. Alte GPU-only-Werte in Tokens/s pro Watt bleiben nur als Information erhalten.

---

## Benchmark-Konfiguration

Mit der mitgelieferten Vorlage beginnen:

```bash
cp benchmark.example.yaml benchmark.yaml
```

Wichtige Abschnitte:

```yaml
project:
  name: "LLM Server Benchmark"
  output_dir: "results"

tools:
  backend: "llama_cpp"

benchmark:
  repetitions: 5
  batch_size: 2048
  ubatch_size: 512
  flash_attention: auto
  prompt_tokens: [512, 4096, 8192]
  generation_tokens: [128, 512]
  context_depths: [0, 8192, 32768, 65536, 130000]

endpoint:
  enabled: false
  concurrency: [1, 2, 4, 8]

models:
  - name: "Example-Model"
    path: "models/example.gguf"
    profiles:
      - name: "Full-GPU"
        gpu_layers: -1
      - name: "CPU-Only"
        gpu_layers: 0
```

Siehe [benchmark.example.yaml](benchmark.example.yaml) für die vollständige Konfiguration.

---

## Hardware-Modi

```bash
llmbench run --hardware cpu
llmbench run --hardware gpu
llmbench run --hardware both
```

Es kann auch ein einzelnes Modell ausgewählt werden:

```bash
llmbench run --config benchmark.yaml --model "Gemma 3 1B"
```

Und ein Dauer-Preset:

```bash
llmbench run --duration short
llmbench run --duration medium
llmbench run --duration long
```

### Optionale Memory-Bandwidth-Telemetrie

Hardware-Snapshots bewahren Memory-Bandwidth-Kapazitaeten pro Domain, sofern ein
Provider sie sicher liefern kann. NVIDIA speichert erkannte Bus-/Clock-Eingaben
ohne einen Transfer-Rate-Multiplikator zu raten; AMD-Providerwerte bleiben
explizit an den aktuellen Memory-Clock gebunden; Apple-Theoriewerte erfordern
einen exakten Match im gebuendelten Katalog mit offiziellen Quellen.

Optionale Runtime-Beobachtungen werden so gesammelt:

```bash
llmbench run --collect-memory-bandwidth
```

Auf unterstuetzten Apple-Silicon-Hosts startet dies einen bereits installierten
`mactop`-Sidecar und speichert dessen JSON-Trace beim Lauf. Es installiert keine
Software, blockiert einen Benchmark bei Nichtverfuegbarkeit nicht und meldet
System-/SoC-Traffic statt prozessexklusiver oder universeller "effective bandwidth".

---

## Modus für volle Leistung

Jeder `llmbench run`- und `llmbench stress-*`-Aufruf stellt die Maschine zuerst auf volle Leistung, damit die Ergebnisse die Hardware statt eines Energiesparprofils widerspiegeln. Dieser Modus ist standardmäßig aktiv und **bleibt nach dem Lauf aktiv**.

| Plattform | Was geändert wird |
| --- | --- |
| **Linux** | power-profiles-daemon / tuned → `performance`, ACPI-Plattformprofil → `performance`, CPU-Governor und Energy-Performance-Preference → `performance`, Turbo/Boost an, `scaling_max_freq` → Hardwaremaximum, Intel-RAPL-Limits → maximal erlaubt, PCIe ASPM → `performance`, NVIDIA Persistence Mode an und Power-Limit → `power.max_limit`, AMD-GPU-Power-Cap → `power1_cap_max` und DPM-Level `high` |
| **Windows** | eigener Energieplan `llmbench Volle Leistung` (Kopie von *Ultimative Leistung*, Fallback auf *Höchstleistung*) mit 100 % minimalem/maximalem Prozessorzustand, aggressivem Boost, keinem Core Parking, keinem PCIe ASPM, keinem Standby; NVIDIA-Power-Limit → `power.max_limit` |

```bash
llmbench performance status   # hat llmbench etwas gesetzt?
llmbench performance on       # volle Leistung ohne Benchmark aktivieren
llmbench performance off      # exakte vorherige Einstellungen wiederherstellen
llmbench run --no-performance-mode   # Energieeinstellungen für einen Lauf nicht ändern
```

Power-Limits und sysfs-Werte benötigen root unter Linux (über `sudo`, bei Bedarf einmal abgefragt) beziehungsweise eine erhöhte Shell unter Windows. Alles, was nicht gesetzt werden kann, wird in der Lauf-Ausgabe und in `summary.json` (`performance_mode`, `warnings`) aufgeführt — der Benchmark läuft trotzdem weiter. Die ursprünglichen Werte werden in `.runtime/performance_state.json` gespeichert, sodass `performance off` immer den Zustand von vor der Änderung durch llmbench wiederherstellt.

Konfiguration in `benchmark.yaml`:

```yaml
performance:
  enabled: true
  restore_after_run: false   # true = nach jedem Lauf wiederherstellen
  use_sudo: true
```

Firmware-Limits wie BIOS/UEFI PL1/PL2, Laptop-EC-Limits oder thermische Grenzen können nicht vom Betriebssystem aufgehoben werden.

## llama.cpp-Setup

llama.cpp direkt installieren oder prüfen:

```bash
llmbench install-llama-cpp --root .
```

Für reproduzierbare Maschinenvergleiche die llama.cpp-Revision in folgender Datei festschreiben:

```text
llama-cpp-version.txt
```

Beispiel:

```text
b10456
```

Linux/macOS:

```bash
llmbench install-llama-cpp --root . --tag b10456
```

Windows PowerShell:

```powershell
$env:LLMBENCH_LLAMACPP_TAG = "b10456"
```

Die tatsächlich verwendete Build-Identität wird in den Ergebnis-Metadaten gespeichert.

---

## NVIDIA-/CUDA-Verhalten

Auf NVIDIA-Systemen integriert sich llmbench in die NVIDIA-Werkzeuge, anstatt die GPU als anonymen Beschleuniger zu behandeln.

Erfasste Informationen:

- GPU-Modell
- Treiberversion
- VRAM
- Compute Capability
- VBIOS
- Power-Limit
- Auslastung
- Temperatur
- Leistungsaufnahme
- Compute-Prozesse

Unter Linux kann llmbench llama.cpp automatisch mit `GGML_CUDA=ON` bauen, wenn `nvcc` verfügbar ist.

Die Backend-Auswahl kann ausdrücklich gesteuert werden:

```bash
export LLMBENCH_LLAMACPP_BUILD_BACKEND=auto
export LLMBENCH_LLAMACPP_BUILD_BACKEND=cuda
export LLMBENCH_LLAMACPP_BUILD_BACKEND=vulkan
export LLMBENCH_LLAMACPP_BUILD_BACKEND=cpu
```

PowerShell:

```powershell
$env:LLMBENCH_LLAMACPP_BUILD_BACKEND = "cuda"
```

---

## vLLM-Backend

vLLM läuft über Docker und nicht als native Python-Abhängigkeit von llmbench.

Installieren:

```bash
llmbench install-backend --backend vllm
```

Entfernen:

```bash
llmbench uninstall-backend --backend vllm
```

In der Benchmark-Konfiguration auswählen:

```yaml
tools:
  backend: "vllm"
  vllm_image: "vllm/vllm-openai:latest"
```

Ein vLLM-Profil kann anschließend Optionen wie Tensor Parallelism und GPU Memory Utilization definieren.

---

## Standard-Modellsuite

**Auf allen Backends gibt es dieselben Modelle** (llama.cpp, Ollama, vLLM, TGI). Ergebnisse verschiedener Backends sind nur vergleichbar, wenn dasselbe Modell gemessen wurde; deshalb gibt es einen gemeinsamen Katalog. Jedes Modell hat die zum Backend passende Referenz:

| Klasse | Modell | Ollama | llama.cpp (GGUF) | vLLM / TGI (Hugging Face) |
| --- | --- | --- | --- | --- |
| small | Gemma 3 1B | `gemma3:1b` · Q4_K_M | `ggml-org/gemma-3-1b-it-GGUF` · Q4_K_M | `google/gemma-3-1b-it` · bf16 |
| small | Granite 4.2 3B | `granite4.2:3b` · Q4_K_M | `ibm-granite/granite-4.2-3b-GGUF` · Q4_K_M | `ibm-granite/granite-4.2-3b` · bf16 |
| small | Qwen3 8B | `qwen3:8b` · Q4_K_M | `Qwen/Qwen3-8B-GGUF` · Q4_K_M | `Qwen/Qwen3-8B` · bf16 |
| mid | DeepSeek-R1 14B | `deepseek-r1:14b` · Q4_K_M | `bartowski/DeepSeek-R1-Distill-Qwen-14B-GGUF` · Q4_K_M | `deepseek-ai/DeepSeek-R1-Distill-Qwen-14B` · bf16 |
| mid | GPT-OSS 20B | `gpt-oss:20b` · MXFP4 | `ggml-org/gpt-oss-20b-GGUF` · MXFP4 | `openai/gpt-oss-20b` · MXFP4 |
| mid | Mistral Small 3.2 24B | `mistral-small3.2:24b` · Q4_K_M | `bartowski/mistralai_Mistral-Small-3.2-24B-Instruct-2506-GGUF` · Q4_K_M | `mistralai/Mistral-Small-3.2-24B-Instruct-2506` · bf16 |
| heavy | Qwen3.8 27B | `qwen3.8:27b` · Q4_K_M | `bartowski/Qwen3.8-27B-GGUF` · Q4_K_M | `Qwen/Qwen3.8-27B` · bf16 |
| heavy | DeepSeek-R1 70B | `deepseek-r1:70b` · Q4_K_M | `bartowski/DeepSeek-R1-Distill-Llama-70B-GGUF` · Q4_K_M | `deepseek-ai/DeepSeek-R1-Distill-Llama-70B` · bf16 |
| heavy | GPT-OSS 120B | `gpt-oss:120b` · MXFP4 | `ggml-org/gpt-oss-120b-GGUF` · MXFP4 | `openai/gpt-oss-120b` · MXFP4 |
| extreme | Qwen3 235B | `qwen3:235b` · Q4_K_M | `unsloth/Qwen3-235B-A22B-GGUF` · Q4_K_M | `Qwen/Qwen3-235B-A22B` · bf16 |

Das Modell trägt auf **jedem Backend denselben Anzeigenamen**, damit `llmbench compare` die Läufe zuordnen kann. Die Gewichte sind zwischen den Backends nicht byte-identisch (GGUF und Ollama sind quantisiert, vLLM lädt die Originalgewichte); `doctor` und `compare` warnen davor. Modelle außerhalb des Katalogs funktionieren weiter, mit dem Hinweis, dass sie sich nicht backendübergreifend vergleichen lassen. Die älteren reinen llama.cpp-Modelle (Qwen3.5-9B, Gemma-4-12B-IT, GLM-4.7-Flash, Qwen3.5-122B-A10B, Mistral-Small-4-119B-2603, DeepSeek-V4-Flash-0731) bleiben als „legacy“ wählbar, gehören aber nicht zur Standardauswahl.

Die Hugging-Face-Repositories und GGUF-Dateinamen wurden gegen den Hub geprüft (04.11.2026). Eine ungeprüfte Referenz erscheint in den Menüs als „(ungeprüft)“. Alles lässt sich mit `python scripts/verify_model_catalog.py` erneut prüfen (braucht Netzwerkzugriff).

Normale Nutzer wählen Modelle während `setup.bat` / `setup.sh` in der Terminal-UI aus. **A / Alle Standardmodelle** wählt alles außer Extreme. Extreme muss ausdrücklich gewählt werden, damit niemals versehentlich ein sehr großer Download startet.

Die zugrunde liegende CLI `llmbench download --suite ...` bleibt für Automatisierung und fortgeschrittene/manuelle Nutzung verfügbar, ist aber nicht der normale Setup-Weg.

Gesplittete GGUF-Dateien werden als ein logisches Modell behandelt. Unvollständige Shard-Sätze werden als unvollständig abgelehnt.

---

## Stress-Befehle

```bash
llmbench stress-ttft --config benchmark.yaml
llmbench stress-multitenant --config benchmark.yaml
llmbench stress-oom --config benchmark.yaml
llmbench stress-quant --config benchmark.yaml
```

`stress-quant` vergleicht unterschiedliche Quantisierungen nur dann, wenn sie zum selben Basismodell gehören.

---

## Reproduzierbarkeit

Jeder Lauf speichert die Informationen, die erforderlich sind, um zu prüfen, ob zwei Benchmark-Ergebnisse tatsächlich vergleichbar sind.

| Nachweis | Zweck |
| --- | --- |
| `config_fingerprint` | Hash der ergebnisrelevanten Benchmark-Einstellungen |
| `config` | Vollständige Konfiguration des Laufs |
| `tools.llama_bench.binary.sha256` | Hash des exakt verwendeten llama-bench-Binaries |
| `tools.llama_cpp_build_ids` | llama.cpp-Build-Identität |
| `llmbench_version` | Version des Benchmark-Frameworks |
| `models[].model.sha256` | Exakter Modell- oder kombinierter GGUF-Shard-Fingerprint |
| Hardware-Metadaten | CPU, RAM, GPU, Treiber und Ausführungsumgebung |

Wenn Reproduzierbarkeit entscheidend ist:

```bash
llmbench compare run-a run-b --strict
```

Der Befehl beendet sich mit Statuscode `1`, wenn inkompatible Bedingungen erkannt werden.

---

## Ergebnisstruktur

Ein Lauf erzeugt einen eigenständigen Ergebnisordner ähnlich diesem:

```text
results/
  SERVERNAME_YYYYMMDD-HHMMSSZ/
    hardware.json
    summary.json
    summary.partial.json
    benchmarks.csv
    report.pdf
    report.html

    MODEL/
      PROFILE/
        raw_prompt.json
        raw_generation.json
        raw_long_context.json

      endpoint/
        endpoint_load.json
        llama-server.log

    stress/
      index.json
      ttft/
      multitenant/
      oom/
      quant/
```

Die Rohdateien bewahren Befehle, stdout/stderr und Telemetrie auf. `summary.json` enthält die aggregierten Daten, die für Berichte und Vergleiche verwendet werden.

### Ergebnisschema v3 und Herkunft

Neue Läufe schreiben `summary.json` mit `schema_version: 3`. Die Referenzfelder bewahren
ihren JSON-Wert zusammen mit der Herkunft: Profil-`gpu_layers` (Einheit `layers`), erkannte
CPU-`physical_cores` (Einheit `cores`) und llama.cpp-`avg_ts` (Einheit `tokens/s`). `source`
ist `requested`, `defaulted`, `detected`, `calculated`, `measured` oder `verified`. Eine
fehlende Herkunft ist mit `status: unknown` beziehungsweise `unavailable` und einem Grund
explizit; `null` steht niemals für `0` oder `false`. Optionales `evidence.method`, `reference`
und `provider` beschreiben das Verfahren ohne Vertrauensbewertung.

llmbench liest v2-Ergebnisse unverändert weiter und zeigt ihre fehlende Herkunft als unknown.
Ergebnisse aus zukünftigen Schemaversionen werden mit einem Hinweis auf ein nötiges Update
abgelehnt. HTML/PDF enthalten eine kompakte Herkunftstabelle; `benchmarks.csv` behält skalare
Metriken und ergänzt `configured_gpu_layers`, `gpu_layers_source` und `avg_ts_source`.
Die beiden `*_source`-Spalten enthalten bei bekannter Herkunft deren Kennung, sonst den
expliziten Zustand `unknown` oder `unavailable`.

### Effektive KV-Cache-Konfiguration

Bei lokalen `llama.cpp`- und vLLM-Läufen kann jedes Profil zusätzlich ein
`kv_cache`-Objekt enthalten. Es speichert ausschließlich vom Runtime bestätigte
oder deterministisch berechnete Werte; angeforderte YAML-/CLI-Einstellungen
werden nie als effektive Werte kopiert. Jedes gemeinsame Feld ist ein
Schema-v3-Envelope mit Herkunft oder dem expliziten Zustand
`unknown`/`unavailable`. Nicht verfügbare Parser oder Metriken lassen einen
ansonsten gültigen Benchmark nicht fehlschlagen.

Die aktuell ausgelieferten nativen Details bleiben bewusst JSON-spezifisch:
llama.cpp bewahrt `build_number` neben der kanonischen
`build_commit`-Runtime-Version auf; vLLM bewahrt
`gpu_kv_cache_size_tokens` und `executor_gpu_memory_budget_fraction` auf.
Letzteres ist ein executor-weites Konfigurationsbudget für Gewichte,
Aktivierungen und KV-Cache, keine reine KV-Speichernutzung. Keiner der beiden
vLLM-Werte ist ein backendübergreifender Kapazitätsvergleich. Beobachtete
Gesamt-VRAM-Telemetrie pro Gerät bleibt getrennt und unverändert.

`llmbench bootstrap` markiert die von ihm erzeugten Profile privat und wertgebunden,
damit ihre `gpu_layers`-Werte als `defaulted` ausgegeben werden; ein explizit in YAML
eingetragener Wert bleibt `requested`. Wählt Auto-Tuning eine positive, endliche Messung,
ist der finale `gpu_layers`-Wert `calculated` und enthält die gewählte TPS sowie die Zahl
erfolgreicher Kandidaten. Ein Fallback ohne erfolgreiche Messung bleibt `unknown` und
beansprucht keine berechnete Herkunft.

Ein Envelope ist bewusst eigenständig:

```json
"avg_ts": {
  "value": 80.5,
  "unit": "tokens/s",
  "source": "measured",
  "evidence": {"method": "benchmark_measurement"}
}
```

Standardmethoden sind `user_configuration`, `configuration_default`,
`hardware_introspection`, `backend_runtime_introspection`, `backend_log_parsing`,
`model_metadata`, `derived_calculation`, `benchmark_measurement` und
`experimental_validation`; eigene Methoden verwenden `custom:vendor/procedure`. Der v3-
Backend-Deskriptor ist `{ "id", "name"?, "config" }`. Er kennzeichnet das gewählte
Benchmark-Backend, nicht die Implementierung hinter einem externen Endpoint. `requested`
setzt einen expliziten YAML-Wert voraus, ein nachweislich geliefertes Preset ist `defaulted`;
llmbench leitet beides nicht aus gleichen Werten oder Profilnamen ab.

### Verifizierte Kontext-Kapazitaet

Long-Context-Ergebnisse enthalten jetzt pro Profil eine ausdrueckliche
Kapazitaetszusammenfassung. Eine Kontexttiefe gilt nur dann als verifiziert, wenn bei dieser
belegten Tiefe sowohl Prompt Processing als auch Text Generation vollstaendig abgeschlossen
wurden. Die hoechste abgeschlossene Tiefe wird als `maximum_verified_context` gespeichert
und erhaelt in Schema v3 `source: verified` sowie
`evidence.method: experimental_validation`.

Der Kapazitaetsblock bewahrt ausserdem die angeforderten und abgeschlossenen Tiefen, die
erste fehlgeschlagene Tiefe soweit bekannt, den Grenzstatus und eine Kontext-
Performance-Tabelle. Kapazitaetsfehler erscheinen als OOM-/Kapazitaetsgrenze, Timeouts
bleiben davon getrennt und eine nur teilweise abgeschlossene Tiefe erhoeht niemals das
verifizierte Maximum. HTML-, PDF- und Terminal-Berichte zeigen dieselbe Grenze sowie die
verfuegbaren Prefill-/Decode-Durchsatzwerte.

Beispiel:

```json
"context_capability": {
  "maximum_verified_context": {
    "value": 131072,
    "unit": "tokens",
    "source": "verified",
    "evidence": {"method": "experimental_validation"}
  },
  "first_failed_context": 262144,
  "limit_status": "skipped_capacity"
}
```

---

## Berichte

llmbench erzeugt mehrere Ausgabeformate, damit Ergebnisse sowohl von Menschen als auch automatisiert ausgewertet werden können:

- **HTML** — interaktiver/lesbarer Bericht
- **PDF** — portabler Benchmark-Bericht
- **CSV** — tabellarische Analyse
- **JSON** — vollständige maschinenlesbare Ergebnisdaten
- **Terminal-Ausgabe** — schnelle lokale Übersicht

---

## Docker-Image

Das Projekt enthält ein CUDA-fähiges Docker-Image mit llmbench und der festgeschriebenen llama.cpp-Runtime.

Die CI-Pipeline:

- baut das Image
- führt einen Smoke-Test ohne GPU-Anforderung aus
- überprüft die enthaltenen llama.cpp-Binaries
- scannt mit Trivy nach HIGH- und CRITICAL-Schwachstellen
- veröffentlicht SBOM-Metadaten
- veröffentlicht Build-Provenance
- pusht freigegebene Builds nach GHCR

Siehe [docs/DOCKER.md](docs/DOCKER.md) für Details zur Nutzung.

---

## Entwicklung

Entwicklungsabhängigkeiten installieren:

```bash
pip install -e ".[dev]"
```

Wichtige lokale Prüfungen:

```bash
ruff check .
mypy llmbench
pytest -q
```

Coverage:

```bash
pytest --cov=llmbench --cov-report=term-missing
```

Python-Paket bauen:

```bash
python -m build
```

GitHub Actions validiert das Projekt aktuell unter:

- Ubuntu
- Windows
- Python 3.10
- Python 3.11
- Python 3.12
- Python 3.13
- Python 3.14

Weitere CI-Prüfungen umfassen CodeQL, Dependency Review, `pip-audit`, Packaging-Tests, Coverage, Docker-Smoke-Tests und Container-Schwachstellen-Scanning.

Vor dem Öffnen eines Pull Requests bitte [CONTRIBUTING.md](CONTRIBUTING.md) lesen.

---

## Sicherheit

Bitte vermutete Schwachstellen **nicht** als normale öffentliche Issues veröffentlichen.

Siehe [SECURITY.de.md](SECURITY.de.md) für Hinweise zur verantwortungsvollen Meldung.

Das Repository nutzt außerdem:

- CodeQL
- GitHub Dependency Review
- `pip-audit`
- Trivy-Container-Scanning
- OpenSSF Scorecard
- Dependabot
- SHA-gepinnte GitHub Actions

---

## Dokumentation

| Dokument | Zweck |
| --- | --- |
| [Wiki](https://github.com/Lautloserspieler/llm-server-benchmark/wiki) | Zweisprachiges deutsch/englisches Benutzerhandbuch, Methodik, Modellsuite, Troubleshooting und Ergebnisinterpretation |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Entwicklungs-Setup, Architektur und Beitragsregeln |
| [ROADMAP.md](ROADMAP.md) | Roadmap für Backends, Telemetrie und Features |
| [CHANGELOG.md](CHANGELOG.md) | Ausgelieferte Änderungen |
| [docs/DOCKER.md](docs/DOCKER.md) | Docker-Nutzung |
| [docs/RELEASE_CHECKLIST.de.md](docs/RELEASE_CHECKLIST.de.md) | Release-Validierungscheckliste |
| [SECURITY.de.md](SECURITY.de.md) | Meldung von Schwachstellen |

---

## Projektumfang

Dieses Projekt ist **kein offizieller MLPerf-Submission-Runner**.

Es ist ein unabhängiges Open-Source-Framework mit Fokus auf reproduzierbares Benchmarking lokaler LLM-Inferenzserver und Hardware.

---

## Beitragen

Beiträge sind willkommen.

Gute Bereiche für Beiträge sind:

- neue Benchmark-Backends
- zusätzliche Telemetrie-Provider
- Testabdeckung
- Plattformkompatibilität
- Verbesserungen an Berichten
- Reproduzierbarkeitsprüfungen
- Dokumentation

Vor einem Pull Request bitte [CONTRIBUTING.md](CONTRIBUTING.md) lesen.

---

## Lizenz

Veröffentlicht unter der [MIT License](LICENSE).
