# LLM Server Benchmark

Reproduzierbares Benchmark-Tool fuer lokale LLM-Server und Workstations auf Basis von **llama.cpp**.

Ziel ist die direkte Vergleichbarkeit mehrerer Server unter identischen Bedingungen - inklusive Nachweis, dass Build, Modell-Dateien und Benchmark-Einstellungen wirklich uebereinstimmen.

## Funktionen

- Prompt Processing / Input-Tokens pro Sekunde
- Text Generation / Output-Tokens pro Sekunde
- Long-Context-Tests bei real belegtem KV-Cache
- CPU-, RAM-, GPU- und VRAM-Auslastung
- NVIDIA-Leistungsaufnahme, Temperatur und Tokens/s pro Watt
- CPU-, GPU- und Hybrid-Profile
- parallele Endpoint-/Multi-User-Tests
- TTFT P50 / P95
- System-TPS und Interactivity-TPS
- kurzer und langer Dauerlast-/Soak-Test
- V2-Stresstests fuer TTFT, Multi-Tenant und KV-/Kontext-Grenzen
- echter Quantisierungsvergleich fuer mehrere Quants desselben Basismodells
- automatische Standard-Modell-Suite ueber Hugging Face
- automatische llama.cpp-Installation unter Windows, Linux und macOS
- vollstaendige Unterstuetzung gesplitteter GGUF-Modelle
- PDF-, HTML-, CSV- und JSON-Berichte
- SHA256-Pruefung der Modelle und llama.cpp-Binaries
- Konsistenzpruefung beim Vergleich mehrerer Server

## Schnellstart

### Windows

```text
1. Repository klonen oder herunterladen
2. START_BENCHMARK.bat starten
3. Setup/Download fertig laufen lassen
4. Benchmark-Dauer und Hardware-Auswahl waehlen
```

`START_BENCHMARK.bat` richtet bei Bedarf Python projektlokal ein, installiert die Python-Abhaengigkeiten, installiert bzw. prueft llama.cpp, prueft die komplette V2-Modell-Suite und laedt fehlende Modelle oder GGUF-Shards automatisch nach.

Ist die Installation bereits vollstaendig, wird das Setup uebersprungen und direkt der Benchmark-Pfad gestartet.

Wenn Python 3.10+ bereits vorhanden ist, kann alternativ `setup.bat` benutzt werden.

### Linux / macOS

```bash
./setup.sh
./START_BENCHMARK.sh
```

Python-Abhaengigkeiten, die V2-Modell-Suite und llama.cpp selbst werden automatisch eingerichtet. Fehlen `llama-bench`/`llama-server` unter `tools/llama.cpp/`, laedt `llmbench` einen passenden vorgebauten Release direkt von GitHub: bei erkannter GPU zuerst einen Vulkan-Build (laeuft auch auf NVIDIA-/AMD-/Intel-GPUs), sonst bzw. bei Startproblemen automatisch einen CPU-Build. Manuell auch einzeln aufrufbar:

```bash
llmbench install-llama-cpp --root .
```

llama.cpp veroeffentlicht fuer Linux keine vorgebauten CUDA-Pakete (nur fuer Windows); der Vulkan-Build ist der automatische Weg zu GPU-Beschleunigung unter Linux. Fuer eine native CUDA-Beschleunigung bleibt nur ein manueller Build aus dem llama.cpp-Quellcode.

Fuer faire Serververgleiche auf allen Rechnern denselben llama.cpp-Build verwenden - siehe [llama.cpp reproduzierbar halten](#llamacpp-reproduzierbar-halten), das gilt genauso unter Linux/macOS.

## Automatische V2-Modell-Suite

Standardmaessig verwaltet `llmbench` folgende Q4_K_M-Modelle:

- Qwen3-8B
- DeepSeek-R1-Distill-Qwen-7B
- Qwen3.8-27B
- Qwen2.5-72B-Instruct
- Mixtral-8x22B-Instruct

Die komplette Suite ist sehr gross. Vor dem Download wird der freie Speicher geprueft und bei wahrscheinlich zu wenig Platz gewarnt.

Manuell ausfuehren:

```powershell
llmbench download --suite small
llmbench download --suite mid
llmbench download --suite heavy
llmbench download --suite all
```

Nur pruefen, ohne etwas herunterzuladen:

```powershell
llmbench download --suite all --verify-only
```

Der Downloader meldet Erfolg erst, wenn alle angeforderten logischen Modelle vollstaendig vorhanden sind. Einzelne fehlgeschlagene Downloads werden nicht mehr verschluckt.

### Gesplittete GGUF-Dateien

Sehr grosse Modelle koennen beispielsweise so vorliegen:

```text
model-Q4_K_M-00001-of-00012.gguf
model-Q4_K_M-00002-of-00012.gguf
...
model-Q4_K_M-00012-of-00012.gguf
```

`llmbench` behandelt diesen Satz als **ein einziges Modell**:

- nur `00001-of-XXXXX.gguf` wird in `benchmark.yaml` eingetragen,
- ein unvollstaendiger Shard-Satz gilt nicht als testbares Modell,
- alte versehentlich einzeln eingetragene Folge-Shards werden beim Bootstrap entfernt,
- Groesse und SHA256-Nachweis beziehen alle Shards ein.

Eigene GGUF-Dateien koennen weiterhin unter `models/` abgelegt werden. `llmbench bootstrap` erkennt sie rekursiv und ergaenzt `benchmark.yaml`, ohne bestehende Profile zu ueberschreiben.

## llama.cpp reproduzierbar halten

Nach der ersten Installation wird llama.cpp nicht bei jedem Benchmark automatisch aktualisiert. Sonst koennten zwei Server unbemerkt mit verschiedenen Builds gemessen werden.

Einen festen Build kann man in `llama-cpp-version.txt` hinterlegen, zum Beispiel:

```text
b10456
```

Unter Windows kann ein Build auch explizit angegeben werden:

```powershell
.\START_BENCHMARK.bat -LlamaCppTag b10456
```

Unter Linux/macOS entweder ebenfalls ueber `llama-cpp-version.txt`, ueber die Umgebungsvariable `LLMBENCH_LLAMACPP_TAG` oder explizit:

```bash
llmbench install-llama-cpp --root . --tag b10456
```

Der tatsaechlich verwendete Build wird in den Ergebnisdaten festgehalten. `llmbench compare` meldet Unterschiede.

## Normaler Benchmark

### Prompt Processing

Standard: `pp512`, `pp4096`, `pp8192`.

Messwert: Input-Tokens/s.

### Text Generation

Standard: `tg128`, `tg512`.

Messwert: Output-Tokens/s.

### Long Context

Der Long-Context-Test verwendet `llama-bench -d`, sodass der KV-Cache tatsaechlich bis zur jeweiligen Tiefe belegt wird.

Zu grosse Kontextstufen laufen nicht unbegrenzt: `benchmark.timeout_seconds` setzt ein Zeitlimit und der restliche Lauf wird fortgesetzt.

### Hardware-Auswahl

```powershell
llmbench run --hardware cpu
llmbench run --hardware gpu
llmbench run --hardware both
```

- `cpu`: nur Profile mit `gpu_layers: 0`
- `gpu`: GPU- und Hybrid-Profile
- `both`: alle Profile; nur hier kann der kombinierte CPU/GPU-Soak-Test laufen

Neu erkannte Modelle erhalten automatisch:

```yaml
profiles:
  - name: Full-GPU
    gpu_layers: -1
    threads: auto
  - name: CPU-Only
    gpu_layers: 0
    threads: auto
```

## Endpoint- und Multi-User-Test

Wenn `endpoint.enabled: true` gesetzt ist, startet das Tool optional selbst `llama-server` und misst mehrere Parallelitaetsstufen.

Erfasst werden unter anderem:

- System-TPS
- Tokens/s pro Request
- TTFT P50
- TTFT P95
- Erfolgsquote

Aufwaerm-Requests werden vor der Messung verworfen. Fester Seed und `ignore_eos` helfen, die Laeufe reproduzierbar zu halten.

## Dauerlast-/Soak-Test

Der Soak-Test startet einen CPU-Only- und einen GPU-Server gleichzeitig und haelt beide unter Last.

Standard:

- kurz: 5 Minuten
- lang: 30 Minuten

Dabei werden Temperatur, Leistungsaufnahme und Tokens/s ueber die Laufzeit beobachtet. Ein deutlicher TPS-Rueckgang wird als moegliches Throttling markiert.

Abschaltbar:

```yaml
soak:
  enabled: false
```

## V2-Stresstests

Alle Stresstests koennen einzeln ausgefuehrt werden:

```powershell
llmbench stress-ttft --config benchmark.yaml
llmbench stress-multitenant --config benchmark.yaml
llmbench stress-oom --config benchmark.yaml
llmbench stress-quant --config benchmark.yaml
```

Oder nach einem normalen Lauf gemeinsam:

```powershell
llmbench run --config benchmark.yaml --stress
```

`START_BENCHMARK.bat` und `START_BENCHMARK.sh` fragen interaktiv, ob die zusaetzlichen Stresstests gestartet werden sollen.

### TTFT-Stress

Startet einen echten Endpoint-Test mit hoher Parallelitaet. Standardmaessig werden die normalen Concurrency-Stufen um 16 und 32 erweitert.

Konfigurierbar:

```yaml
stress:
  ttft_concurrency: [1, 2, 4, 8, 16, 32]
```

### Multi-Tenant

Startet zwei konfigurierte Modelle gleichzeitig auf getrennten Ports und misst beide Endpoints parallel. Rohdaten werden in getrennten Ergebnisordnern gespeichert, damit sie sich nicht gegenseitig ueberschreiben.

Mindestens zwei Modelle in `benchmark.yaml` sind erforderlich.

### KV-/Kontext-OOM-Test

Der Server wird fuer jede Kontextstufe neu gestartet. Dadurch kann unterschieden werden, ob bereits das Anlegen des KV-Caches scheitert oder erst der lange Request.

```yaml
stress:
  oom_contexts: [4096, 8192, 16384, 32768, 65536, 96000, 130000]
```

Der Test versucht zusaetzlich ueber `/tokenize` die tatsaechliche Prompt-Tokenzahl zu bestimmen.

### Quantisierungsvergleich

`stress-quant` vergleicht **nur verschiedene Quantisierungen desselben Basismodells**. Damit ist ein Q4-vs-Q8-Vergleich sinnvoll; verschiedene Modelle werden nicht mehr faelschlich miteinander verglichen.

Die automatische Standard-Suite ist Q4_K_M. Fuer diesen Test muessen deshalb zusaetzlich mindestens zwei Quants desselben Modells vorhanden sein, zum Beispiel:

```text
models/
  same-model-Q4_K_M.gguf
  same-model-Q8_0.gguf
```

Die strukturierten Ergebnisse landen in `stress_quant/quant.json` bzw. bei `--stress` im Stress-Unterordner des normalen Laufs.

## Konfiguration

Vorlage: `benchmark.example.yaml`

Beim ersten Setup entsteht daraus `benchmark.yaml`. Bestehende Modelleintraege und Profile bleiben bei spaeteren Bootstrap-Laeufen erhalten.

Wichtige Befehle:

```powershell
# Einrichtung
llmbench setup

# Konfiguration/Hardware/Modelle pruefen
llmbench doctor --config benchmark.yaml

# Modelle und Tools erneut erkennen
llmbench bootstrap --config benchmark.yaml --root . --llama-dir tools/llama.cpp --models-dir models

# Normaler Benchmark
llmbench run --config benchmark.yaml

# Kurz/mittel/lang
llmbench run --config benchmark.yaml --duration short
llmbench run --config benchmark.yaml --duration medium
llmbench run --config benchmark.yaml --duration long

# Ein Modell
llmbench run --config benchmark.yaml --model "Qwen3-8B"

# Statusausgabe fuer Logdateien vereinfachen
llmbench run --config benchmark.yaml --plain
```

## Reproduzierbarkeit

Fuer einen fairen Vergleich muessen mindestens uebereinstimmen:

1. llama.cpp-Build
2. exakte GGUF-Daten
3. Quantisierung
4. Benchmark-Konfiguration
5. moeglichst Treiber- und Softwarestand

Jeder Lauf speichert unter anderem:

| Feld | Bedeutung |
| --- | --- |
| `config_fingerprint` | Hash der ergebnisrelevanten Benchmark-Einstellungen |
| `config` | verwendete Konfiguration |
| `tools.llama_bench.binary.sha256` | SHA256 von llama-bench |
| `tools.llama_cpp_build_ids` | Build-Kennung aus llama.cpp |
| `llmbench_version` | Tool-Version |
| `models[].model.sha256` | SHA256 des Modells bzw. kombinierter Hash aller GGUF-Shards |

### Energieplan unter Linux

Unter Linux traegt `llmbench` den aktiven CPU-Governor und - falls vorhanden -
das Profil von `power-profiles-daemon` in `hardware.json`/`report.html`/
`report.pdf` ein. Auf Ubuntu Desktop (z. B. 24.04 LTS mit GNOME) laeuft
standardmaessig `power-profiles-daemon` im Profil "balanced", nicht
"performance" - anders als auf vielen Headless-Servern mit festem
`cpupower`-Governor. Das kostet spuerbar Tokens/s und faellt beim Vergleich
mehrerer Server leicht unter den Tisch. `llmbench doctor` warnt deshalb, wenn
der Energieplan nicht auf "performance" steht:

```bash
sudo powerprofilesctl set performance   # Ubuntu Desktop (power-profiles-daemon)
sudo cpupower frequency-set -g performance   # Headless-Server ohne power-profiles-daemon
```

## Ergebnisse

Am Ende eines Laufs erscheint dieselbe Uebersicht auch direkt im Terminal: Hardware-Karten,
Testbedingungen, Tabellen je Modell/Profil, Endpoint- und Dauerlastwerte sowie alle Hinweise –
farbig formatiert wie im HTML-/PDF-Bericht. Das ist besonders auf Linux-Servern ohne Desktop
(SSH-Sitzung) praktisch, wo man die Dateien nicht direkt oeffnet. Mit `--plain` (z. B. beim
Umleiten in eine Logdatei) gibt es stattdessen eine einfache Klartexttabelle ohne Farben und
Rahmen; ohne echtes Terminal (Umleitung erkannt) schaltet `llmbench` automatisch darauf um.

Zusaetzlich erzeugt ein normaler Lauf beispielsweise:

```text
results/
  SERVERNAME_YYYYMMDD-HHMMSSZ/
    hardware.json
    summary.json
    summary.partial.json
    benchmarks.csv
    report.pdf
    report.html
    MODELL/
      PROFIL/
        raw_prompt.json
        raw_generation.json
        raw_long_context.json
      endpoint/
        endpoint_load.json
        llama-server.log
    stress/                 # nur bei --stress
      index.json
      ttft/
      multitenant/
      oom/
      quant/
```

Rohdaten enthalten die exakten Befehle, stdout/stderr und Telemetrie. `summary.json` bleibt auf Aggregate beschraenkt.

## Mehrere Server vergleichen

```powershell
llmbench compare "results/ServerA_..." "results/ServerB_..." --out comparison
```

Strenger CI-/Automationsmodus:

```powershell
llmbench compare "results/ServerA_..." "results/ServerB_..." --strict
```

`--strict` liefert Exitcode 1, wenn die Laeufe unter unterschiedlichen Bedingungen entstanden sind.

## Tests

```powershell
pip install -e ".[dev]"
pytest -q
ruff check .
```

GitHub Actions testet Python 3.10 und 3.12 unter Windows und Ubuntu. Unter Windows werden zusaetzlich die PowerShell-Launcher geparst.

## MLPerf-Einordnung

Dieses Projekt ist kein offizieller MLPerf-Submission-Runner. Es verwendet jedoch fuer interne Hardwarevergleiche relevante Messgroessen wie Throughput, Interaktivitaet, TTFT und Parallelitaet.

## Lizenz

MIT - siehe `LICENSE`.
