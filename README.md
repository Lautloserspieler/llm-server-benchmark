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
- Live-Anzeige im Terminal während des Laufs
- PDF-, HTML-, CSV- und JSON-Berichte
- SHA256-Prüfung der GGUF-Dateien **und** der llama.cpp-Programmdateien
- automatische Konsistenzprüfung beim Vergleich mehrerer Serverläufe
- Dauerlast-Test: CPU- und GPU-Server gleichzeitig, kurz und lang, zur Throttling-Erkennung

## Version 1.4.0

Die kurzen pp/tg-Tests sind vorbei, bevor die Hardware überhaupt warm wird — für Temperatur und Throttling taugen sie nicht. Neu ist deshalb ein Dauerlast-Test (`soak`), der einen CPU-Only- und einen GPU-Server **gleichzeitig** startet und beide über mehrere Minuten unter Last hält, während Temperatur, Leistungsaufnahme und Tokens/s laufend mitgeschrieben werden. Jeder Modelllauf bekommt automatisch einen kurzen (5 Minuten) und einen langen (30 Minuten) Durchgang; ein Rückgang der Tokens/s über die Laufzeit gilt als Hinweis auf Throttling und erscheint als Warnung im Bericht.

`llmbench bootstrap` legt für neu erkannte Modelle jetzt automatisch auch ein `CPU-Only`-Profil an — Voraussetzung für den Soak-Test und nebenbei ein direkt vergleichbarer reiner CPU-Pfad für die normalen Tests. Details unter [Dauerlast-Test (Soak-Test)](#dauerlast-test-soak-test).

## Version 1.3.0

Während eines Laufs war bisher nichts zu sehen. Neu ist deshalb eine Statuszeile im Terminal, die laufend zeigt, welcher Test gerade läuft, wie weit er ist, was die Hardware dabei tut und wie lange der Gesamtlauf noch dauert:

```text
[3/9] qwen-27b-q4_0 · Full-GPU · long_context
    pp512                     1284.30 t/s   ±12.10
    tg128                       58.70 t/s   ±0.40
  laeuft 04:12 · run 2/5 · CPU 18% · GPU 98% · 11.4/12.0 GiB · 187 W · 71 °C · noch ca. 23:41
```

Fertige Einzelergebnisse bleiben als feste Zeilen stehen, die Statuszeile darunter aktualisiert sich. Ohne Terminal, etwa bei Umleitung in eine Datei, schaltet die Ausgabe selbsttätig auf einzelne Zeilen um; erzwingen lässt sich das mit `--plain`.

Am Ende steht eine Ergebnistabelle direkt im Terminal, und jeder Lauf erzeugt zusätzlich einen PDF-Bericht mit Diagrammen.

Das Web-Dashboard ist entfallen — die Live-Anzeige ersetzt es.

## Version 1.2.0

Der Schwerpunkt dieser Version war der Nachweis der Vergleichbarkeit. Bis 1.1.1 hat das Werkzeug korrekt gemessen, aber nicht festgehalten, *unter welchen Bedingungen*. Zwei Server konnten unbemerkt mit verschiedenen Einstellungen, verschiedenen llama.cpp-Builds oder verschiedenen Modelldateien verglichen werden.

Neu:

- Die tatsächlich verwendete Konfiguration, ein **Konfigurations-Fingerabdruck**, der llama.cpp-Build und der SHA256 von `llama-bench` landen in `summary.json`.
- `llmbench compare` prüft vor dem Vergleich, ob die Läufe überhaupt vergleichbar sind, und stellt Abweichungen an den Anfang des Berichts.
- Die automatische Erkennung durchsucht nur noch das Projekt, nicht mehr PATH und Systemordner.
- Endpoint-Tests laufen mit denselben Parametern wie `llama-bench`, mit festem Seed, fester Antwortlänge und Aufwärmläufen.
- Jeder Einzeltest hat ein Zeitlimit.

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

`setup.sh` legt `.venv` an und installiert `llmbench` mit allen Abhängigkeiten.

> **Wichtig:** Unter Linux und macOS wird llama.cpp **nicht** automatisch heruntergeladen. Lade `llama-bench` und `llama-server` von den [offiziellen Releases](https://github.com/ggml-org/llama.cpp/releases) oder baue sie selbst, und lege beide unter `tools/llama.cpp/` ab. Für einen Serververgleich auf allen Servern denselben Build verwenden — `llmbench compare` meldet Abweichungen.

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

Nach der ersten Installation wird llama.cpp **nicht** bei jedem Start aktualisiert, sonst könnten zwei Server unbemerkt mit verschiedenen Builds messen. Ein bewusstes Update erfolgt über `UPDATE_DEPENDENCIES.bat`.

#### Build festschreiben

Ohne feste Vorgabe installiert das Setup den neuesten llama.cpp-Build — und der hängt davon ab, *wann* jemand das Setup gestartet hat. Zwei Server, die eine Woche auseinander eingerichtet werden, bekommen verschiedene Builds.

Für eine Vergleichsserie deshalb den Build festschreiben. Der erste Server nennt nach der Installation den verwendeten Tag; diesen in eine Datei `llama-cpp-version.txt` im Projektordner schreiben:

```text
b10456
```

Alle weiteren Server installieren dann genau diesen Build. Die Datei gehört ins Repository — sie ist Teil der Testbedingungen. Alternativ einmalig per Parameter:

```powershell
.\START_BENCHMARK.bat -LlamaCppTag b10456
```

Oder über die Umgebungsvariable `LLMBENCH_LLAMACPP_TAG`. Reihenfolge: Parameter, dann Umgebungsvariable, dann `llama-cpp-version.txt`, dann neuester Build.

Welcher Build tatsächlich installiert wurde, steht in `tools/llama.cpp/.llama-build.json` und in jedem Ergebnis unter `tools.llama_cpp_build_ids`. `llmbench compare` meldet Abweichungen als Fehler.

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

### Dauerlast-Test (Soak-Test)

Die pp/tg-Tests dauern jeweils nur Sekunden — die Hardware erreicht in dieser Zeit kein thermisches Gleichgewicht. Der Soak-Test startet deshalb einen CPU-Only- und einen GPU-Server **gleichzeitig** (genau wie im Mehrbenutzerbetrieb, wenn ein Server beide Lastarten parallel bedient) und hält beide über längere Zeit unter Dauerlast, während Temperatur, Leistungsaufnahme und Tokens/s durchgehend mitgeschrieben werden.

Jeder Modelllauf umfasst automatisch zwei Durchgänge:

- **kurz** (`soak.duration_short_seconds`, Standard 5 Minuten)
- **lang** (`soak.duration_long_seconds`, Standard 30 Minuten)

Voraussetzung sind zwei Profile je Modell: eines mit `gpu_layers: 0` (CPU) und eines mit `gpu_layers` ungleich 0 (GPU). `llmbench bootstrap` legt für neu erkannte Modelle automatisch `CPU-Only` und `Full-GPU` an. Fehlt eines der beiden, wird der Soak-Test für dieses Modell übersprungen und ein Hinweis im Bericht vermerkt — der restliche Lauf bleibt gültig.

Throttling wird heuristisch erkannt: Fallen die Tokens/s vom frühen Teil des Laufs (10–30 % der Laufzeit) zum späten Teil (70–100 %) um mehr als `soak.throttle_tps_drop_fraction` (Standard 15 %), gilt das als Hinweis auf thermisches Throttling. Die gemessene Maximaltemperatur je GPU steht zusätzlich im Bericht — das Ergebnis lohnt in jedem Fall den eigenen Blick.

Abschaltbar über `soak.enabled: false`. `llmbench compare` und `report.pdf` enthalten die Soak-Ergebnisse aktuell noch nicht, nur `report.html` und `summary.json`.

## Konfiguration

Die Vorlage liegt in `benchmark.example.yaml`; beim ersten Start entsteht daraus `benchmark.yaml`. Diese Datei ist maschinenspezifisch und per `.gitignore` ausgeschlossen — geteilt wird die Vorlage.

Neue Modelle erhalten zunächst ein Full-GPU- und ein CPU-Only-Profil:

```yaml
profiles:
  - name: "Full-GPU"
    gpu_layers: -1
    threads: auto
  - name: "CPU-Only"
    gpu_layers: 0
    threads: auto
```

`gpu_layers: 0` erzwingt reine CPU-Inferenz — direkt vergleichbar mit dem Full-GPU-Profil und Voraussetzung für den Soak-Test oben. Nicht gewünscht: das Profil aus `benchmark.yaml` entfernen oder `soak.enabled: false` setzen.

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

# Ohne sich aktualisierende Statuszeile, etwa für eine Protokolldatei
llmbench run --config benchmark.yaml --plain

# Modellerkennung erneut ausführen
llmbench bootstrap --config benchmark.yaml --root . --llama-dir tools/llama.cpp --models-dir models
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
```

Die `raw_*.json` enthalten den exakten Befehl, stdout, stderr, Laufzeit und die vollständige Telemetrie mit allen Einzelmesspunkten. `summary.json` enthält davon nur die Aggregate und bleibt dadurch auch nach mehrstündigen Läufen handhabbar.

`report.pdf` ist der Bericht zum Weitergeben: Serverdaten, Nachweis der Testbedingungen, Ergebnistabellen und Balkendiagramme je Modell und Profil, Telemetrie und Endpoint-Werte. Prompt Processing und Text Generation bekommen dabei getrennte Diagramme, weil sie um eine Größenordnung auseinanderliegen. Lässt sich das PDF nicht erzeugen, etwa weil `reportlab` fehlt, bleibt der Lauf gültig und der Grund steht als Hinweis in `summary.json`.

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
