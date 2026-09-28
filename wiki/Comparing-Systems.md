# Systeme vergleichen

## Grundregel

Nur vergleichbare Bedingungen ergeben einen belastbaren Hardwarevergleich.

## Strikter Vergleich

```bash
llmbench compare results/server-a results/server-b --strict
```

Der strikte Modus meldet inkompatible Bedingungen als Fehler.

## Wichtige Vergleichsmerkmale

- exakte Modell-Datei / Modell-Hash
- Quantisierung
- Backend
- Backend-Build
- Benchmark-Konfiguration
- Profile
- Hardware-Modus
- Kontext-/Generationstiefen
- relevante Runtime-Einstellungen

## GPU vs GPU Overload

Ein normaler `gpu`-Lauf und ein `gpu_overload`-Lauf sind methodisch verschieden und werden deshalb nicht als direkt gleichwertige Runs behandelt.

## Betriebssystem

Windows und Linux können unterschiedliche Treiber-, Scheduler-, Speicher- und Backendpfade nutzen. Ergebnisse können verglichen werden, aber die Plattformdifferenz muss sichtbar bleiben.

## Power-Limit

Beispiel:

```text
RTX 5090 @ 450 W
RTX 5090 @ 600 W
```

Das sind nicht dieselben Testbedingungen.

## Modellfamilien

Ein allgemeines Hardwareurteil sollte nicht nur aus einer Modellfamilie abgeleitet werden. Die Standardsuite verteilt sich deshalb über mehrere Familien.

## Empfehlung für Referenzläufe

1. gleicher Git-Stand
2. gleiche Modell-Suite
3. gleiche Quantisierung
4. gleiches Backend/Build
5. Long-Preset
6. System möglichst im Ruhezustand
7. keine Fremdlast
8. Reports gemeinsam archivieren
