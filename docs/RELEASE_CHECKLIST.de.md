# Release- & Demo-Checkliste

🇩🇪 Deutsch | [🇬🇧 English](RELEASE_CHECKLIST.md)

Dieses Dokument bündelt die Schritte für öffentliche Releases und die Demo-Bereitschaft von **LLM Server Benchmark**.

## Kurzbeschreibung in einem Satz

**LLM Server Benchmark ist ein Open-Source-Framework, das Ergebnisse lokaler LLM-Performance reproduzierbar macht, indem die exakte NVIDIA-GPU-/CUDA-Umgebung, Modell-/Build-Fingerprints und Live-NVML-Telemetrie gemeinsam mit Durchsatz-, Latenz-, Kontext- und Energieeffizienz-Messungen gespeichert werden.**

## Problem

Screenshots lokaler LLM-Benchmarks zeigen häufig nur Modellname und Tokens/s. Dadurch sind
Ergebnisse schwer reproduzierbar oder vergleichbar, weil wichtige Variablen fehlen:

- exakte GPU und Treiber
- CUDA-/Backend-Auswahl
- llama.cpp-Build
- Modelldatei / Quantisierung
- Kontext- und Benchmark-Konfiguration
- VRAM-Druck
- GPU-Hintergrundlast
- Temperatur und Energiezustand

Das Projekt speichert diese Variablen gemeinsam mit der Messung und kann inkompatible
Vergleiche im Strict-Modus ablehnen.

## Verwendete NVIDIA-Technik

- `nvidia-smi` für NVIDIA-GPU-Erkennung und Hardware-Metadaten
- NVML über `nvidia-ml-py` für Live-Auslastung, VRAM, Temperatur, Leistung und Compute-Prozess-Telemetrie
- natives llama.cpp-CUDA-Backend auf NVIDIA-Systemen
- automatischer Linux-CUDA-Source-Build mit `GGML_CUDA=ON`, wenn eine NVIDIA-GPU und das CUDA Toolkit (`nvcc`) erkannt werden
- CUDA-fähiger Windows-Pfad für NVIDIA-Systeme

## Empfohlener Demo-Ablauf

Eine kurze Demo sollte den Nutzen deutlich machen, ohne vorauszusetzen, dass die Zuschauer
die Codebasis verstehen.

### Ablauf für 45–60 Sekunden

1. **0–5 s – Problem**  
   Zwei beliebig wirkende LLM-Leistungswerte zeigen und die Frage stellen:
   *Sind diese Ergebnisse überhaupt vergleichbar?*

2. **5–12 s – Start**  
   `START_BENCHMARK.bat` oder `./START_BENCHMARK.sh` starten.

3. **12–20 s – NVIDIA-Erkennung**  
   Erkannte NVIDIA-GPU, Treiber, VRAM und CUDA-/Backend-Pfad zeigen.

4. **20–35 s – Live-Benchmark**  
   Generierungsdurchsatz zusammen mit GPU-Auslastung, VRAM, Temperatur und Leistung zeigen.

5. **35–47 s – Reproduzierbarkeitsnachweis**  
   Berichtsfelder für llama.cpp-Build, Modell-SHA256 und Konfigurations-Fingerprint zeigen.

6. **47–55 s – Vergleich**  
   `llmbench compare` zwischen zwei Maschinen/Läufen zeigen und hervorheben, dass
   inkompatible Bedingungen erkannt werden.

7. **55–60 s – Abschluss**  
   Das öffentliche GitHub-Repository mit der Botschaft zeigen:
   *Open Source. Reproduzierbar. Für echte lokale LLM-Hardwarevergleiche gebaut.*

## Empfohlene Screenshots

Wenige klare Bilder statt einer Wand aus Terminaltext verwenden:

1. Hardware-Erkennung mit sichtbarer NVIDIA-GPU
2. Benchmark-Ergebnis mit Tokens/s und TTFT
3. NVML-Telemetrie: VRAM, Auslastung, Temperatur und Leistung
4. Provenance-Block mit Modell-/Build-/Konfigurations-Fingerprints
5. Optionaler Maschinenvergleich

## Release-Checkliste

Vor einem Release oder einer öffentlichen Demo:

- [ ] `main` enthält die aktuelle README und Dokumentation
- [ ] GitHub Actions sind grün
- [ ] Repository ist öffentlich
- [ ] MIT-Lizenz ist vorhanden
- [ ] finaler NVIDIA-Windows-Test abgeschlossen
- [ ] finaler NVIDIA-Linux-/CUDA-Test abgeschlossen
- [ ] `llmbench doctor` zeigt die beabsichtigte GPU/das beabsichtigte Backend
- [ ] sauberer Benchmark-Lauf ohne Warnung vor fremder GPU-Last erzeugt
- [ ] HTML-/PDF-Bericht lässt sich korrekt öffnen
- [ ] Demo-Video ist kurz und auf Mobilgeräten lesbar
- [ ] öffentliche Projektlinks zeigen auf das aktuelle Repository
- [ ] Contributor-Attribution geprüft: externe Änderungen nennen im `CHANGELOG.md` den Contributor mit `@username`
- [ ] Release Notes nennen externe Contributors bei ihren Änderungen und schreiben die Autorenschaft nicht dem Maintainer zu
- [ ] Wenn mehrere Personen substanziell gemeinsam gearbeitet haben, werden alle Contributors genannt
- [ ] Deutsche und englische Markdown-Dokumentation ist synchron

## Vorschlag für einen Projekt-Post

> Ich habe **LLM Server Benchmark** gebaut, ein Open-Source-Framework für reproduzierbare lokale LLM-Leistungstests.
>
> Statt nur eine Tokens/s-Zahl zu veröffentlichen, speichert jeder Lauf die exakte GPU-/Treiber-, CUDA-/Backend- und llama.cpp-Build-Konfiguration, Modell-Fingerprints und Benchmark-Einstellungen und sammelt gleichzeitig NVIDIA-NVML-Live-Telemetrie für Auslastung, VRAM, Temperatur und Leistung.
>
> Gemessen werden Durchsatz, TTFT, Long-Context-Verhalten, paralleles Serving, Stressgrenzen und Energieeffizienz. Außerdem kann erkannt werden, wenn zwei Benchmark-Läufe unter inkompatiblen Bedingungen entstanden sind.
>
> Source: https://github.com/Lautloserspieler/llm-server-benchmark

## Finale Validierungsbefehle

```bash
llmbench doctor --config benchmark.yaml
llmbench run --config benchmark.yaml --hardware gpu --duration short
pytest -q
ruff check .
```

Für eine NVIDIA-Linux-Maschine den installierten llama.cpp-Backend-Typ prüfen:

```bash
cat tools/llama.cpp/.llama-build.json
```

Erwartung für den nativen NVIDIA-Pfad:

```json
{
  "backend": "cuda",
  "source_build": true
}
```

Die exakte Datei enthält zusätzliche Felder wie den festgeschriebenen llama.cpp-Tag und Build-Pfade.
