[Deutsch](DE-Installation) | [English](EN-Installation)

---

# Installation

## Voraussetzungen

Empfohlen:

- 64-Bit Windows oder Linux
- Python 3.10+
- ausreichend freier Speicher für Modelle
- aktueller GPU-Treiber
- für Container-Backends: Docker
- für NVIDIA-Docker: funktionierender GPU-Zugriff im Container

## Windows

```powershell
git clone https://github.com/Lautloserspieler/llm-server-benchmark.git
cd llm-server-benchmark
.\setup.bat
```

Das Setup führt dich über die Terminal-UI durch:

- Sprache
- benötigte Komponenten
- Modellauswahl
- optionale Backends
- Konfiguration

Die Modellauswahl zeigt auch **DeepSeek-V4-Flash-0731 [EXTREME]** an. Extreme wird nur geladen, wenn du es ausdrücklich auswählst.

Nach erfolgreichem Setup startest du Benchmarks künftig mit:

```powershell
.\START_BENCHMARK.bat
```

## Linux / Ubuntu

```bash
git clone https://github.com/Lautloserspieler/llm-server-benchmark.git
cd llm-server-benchmark
chmod +x setup.sh START_BENCHMARK.sh
./setup.sh
```

Auch hier läuft die Einrichtung inklusive Modellauswahl über die Terminal-UI.

Danach:

```bash
./START_BENCHMARK.sh
```

## Normaler Benutzerweg

Nach dem Setup musst du für normale Benchmarkläufe keine `llmbench run`- oder `llmbench download --suite`-Befehle von Hand verwenden.

Der vorgesehene Ablauf ist:

```text
setup.bat / setup.sh
        ↓
Modellauswahl in der Terminal-UI
        ↓
START_BENCHMARK.bat / START_BENCHMARK.sh
        ↓
Dauer auswählen
        ↓
Hardware-Modus auswählen
        ↓
Stress-Tests auswählen
        ↓
Benchmark
```

## Native/fortgeschrittene Nutzung

Die Python-CLI bleibt für Entwicklung, Automatisierung und manuelle Sonderfälle verfügbar:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
llmbench install-llama-cpp --root .
```

Für normale Nutzer ist die Terminal-UI jedoch der empfohlene Weg.
