[Deutsch](DE-Quick-Start) | [English](EN-Quick-Start)

---

# Quick Start

Der normale Benutzerweg läuft nach dem Setup vollständig über die **Terminal-UI**. Für einen normalen Benchmark musst du keine `llmbench run ...`-Befehle von Hand zusammenbauen.

## 1. Setup einmalig ausführen

### Windows

```powershell
.\setup.bat
```

### Linux

```bash
./setup.sh
```

Im Setup werden unter anderem Sprache, Modelle und verfügbare Backends eingerichtet.

## 2. Benchmark über den Starter öffnen

Nach erfolgreichem Setup startest du künftig immer über den passenden Starter.

### Windows

```powershell
.\START_BENCHMARK.bat
```

### Linux

```bash
./START_BENCHMARK.sh
```

Der Starter prüft die Installation, Modelle und Umgebung und öffnet anschließend die Terminal-UI.

## 3. Dauer in der Terminal-UI auswählen

Die UI fragt:

**Wie lange soll getestet werden?**

- **short** – schneller Check
- **medium** – Standardwerte
- **long** – präzisere Referenz- und Stabilitätsmessungen

Du musst dafür keinen CLI-Parameter eingeben.

## 4. Hardware in der Terminal-UI auswählen

Danach fragt die UI, was getestet werden soll:

- **CPU only**
- **GPU only**
- **GPU only – VRAM-Limit bewusst überschreiten / Unified Memory testen**
- **CPU und GPU – inklusive Dauerlasttest**

Der dritte Punkt entspricht dem `gpu_overload`-Modus, wird aber normal über das Menü ausgewählt.

## 5. Zusätzliche Stress-Tests auswählen

Die Terminal-UI fragt anschließend, ob zusätzliche Stress-Tests ausgeführt werden sollen.

Dazu gehören je nach Backend und Konfiguration unter anderem:

- TTFT
- Multi-Tenant
- OOM / Kapazitätsgrenzen
- Quantisierungsvergleich

Danach zeigt die UI deine Auswahl zusammengefasst an und startet den Benchmark.

## 6. Ergebnisdateien

Ein Lauf erzeugt typischerweise:

```text
results/
  SERVER_YYYYMMDD-HHMMSSZ/
    hardware.json
    summary.json
    benchmarks.csv
    report.html
    report.pdf
```

Die wichtigsten Einstiege sind:

- `report.html` für die visuelle Auswertung
- `report.pdf` zum Teilen/Archivieren
- `summary.json` für maschinelle Auswertung

## 7. Systeme vergleichen

Der eigentliche Benchmark wird über die Starter und Terminal-UI ausgeführt. Für fortgeschrittene Auswertung steht zusätzlich die CLI zum Vergleichen vorhandener Runs zur Verfügung:

```bash
llmbench compare results/system-a results/system-b --strict
```
