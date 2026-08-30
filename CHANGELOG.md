# Changelog

## 1.4.0

### Dauerlast-Test (CPU + GPU gleichzeitig)

- Neuer Testtyp `soak`: startet einen CPU-Only- und einen GPU-Server
  gleichzeitig und haelt beide ueber laengere Zeit unter Dauerlast, um
  thermisches Throttling sichtbar zu machen. Die bisherigen pp/tg-Tests
  dauern nur Sekunden - zu kurz, um die Hardware ueberhaupt ins thermische
  Gleichgewicht zu bringen.
- Laeuft standardmaessig als Teil jedes `llmbench run`: ein kurzer Durchgang
  (`soak.duration_short_seconds`, Standard 5 Minuten) und ein langer
  (`soak.duration_long_seconds`, Standard 30 Minuten).
- Throttling-Heuristik: Tokens/s im fruehen Teil des Laufs (10-30 %) gegen
  Tokens/s im spaeten Teil (70-100 %) verglichen; ein Rueckgang ueber
  `soak.throttle_tps_drop_fraction` (Standard 15 %) gilt als Hinweis auf
  Throttling und erscheint als Warnung im Bericht.
- `llmbench bootstrap` legt fuer neu erkannte Modelle jetzt automatisch ein
  `CPU-Only`-Profil (`gpu_layers: 0`) zusaetzlich zu `Full-GPU` an - noetig
  als Grundlage fuer den Soak-Test, macht den reinen CPU-Pfad aber auch fuer
  die normalen pp/tg-Tests direkt vergleichbar.
- Ergebnisse stehen in `report.html` und `summary.json`
  (`models[].soak`); `llmbench compare` und `report.pdf` enthalten sie noch
  nicht.
- `ResourceMonitor` kann jetzt mehrere Zielprozesse gleichzeitig als "eigene"
  Last markieren (`set_target_pids`), damit sich CPU- und GPU-Server im
  Soak-Test nicht gegenseitig als Fremdlast melden.
- Abschaltbar ueber `soak.enabled: false`.

### Hardware-Auswahl (`--hardware`)

- Neue Option `llmbench run --hardware {cpu,gpu,both}` (Standard `both`):
  beschraenkt den Lauf auf Profile mit `gpu_layers: 0` (`cpu`), auf Profile
  mit `gpu_layers` ungleich 0 (`gpu`, inklusive Hybrid-Profile) oder testet
  alle Profile (`both`).
- Der Soak-Test laeuft nur bei `both`, da er CPU und GPU gleichzeitig
  braucht; bei `cpu` oder `gpu` wird er uebersprungen und das steht als
  Hinweis im Bericht.
- Passt ein Modell zur gewaehlten Hardware kein Profil, wird es
  uebersprungen (Hinweis im Bericht) statt den Lauf abzubrechen; ebenso der
  Endpoint-Test, falls er ein passendes Profil braucht.
- `START_BENCHMARK.bat` und `START_BENCHMARK.sh` fragen die Auswahl jetzt
  interaktiv ab, direkt nach der Frage nach der Testdauer.

## 1.3.0

### Live-Anzeige waehrend des Laufs

- Neue Statuszeile im Terminal: laufender Test, verstrichene Zeit, Fortschritt
  aus `llama-bench --progress`, GPU-Auslastung, VRAM, Leistungsaufnahme,
  Temperatur und eine Restzeitschaetzung. Bisher war waehrend eines Laufs
  ueberhaupt nichts zu sehen.
- Die Ausgabe von `llama-bench` wird jetzt nebenlaeufig mitgelesen statt
  komplett abgefangen. Fortschrittsmeldungen sind mit Wagenruecklauf statt
  Zeilenumbruch getrennt; das wird eigens behandelt.
- Kennt der installierte Build `--progress` nicht, wird der Test einmal ohne
  wiederholt statt zu scheitern.
- Jedes Einzelergebnis erscheint sofort nach seinem Test, nicht erst im Bericht.
- Die Restzeit wird je Testart gemittelt: ein Long-Context-Test dauert ein
  Vielfaches eines Prompt-Tests, ein Gesamtmittel waere deutlich daneben.
- Ohne Terminal (Umleitung in eine Datei) schaltet die Anzeige selbsttaetig auf
  einzelne Zeilen um. Erzwingbar mit `llmbench run --plain`.
- Am Ende steht eine Ergebnistabelle direkt im Terminal.

### PDF-Bericht

- Jeder Lauf erzeugt zusaetzlich `report.pdf`: Serverdaten, Nachweis der
  Testbedingungen, Ergebnistabellen und Balkendiagramme je Modell und Profil,
  Telemetrie und Endpoint-Werte.
- Prompt Processing und Text Generation bekommen getrennte Diagramme. Auf einer
  gemeinsamen Skala waeren die Generierungsbalken nicht mehr ablesbar.
- Schlaegt die PDF-Erzeugung fehl, bleibt der Lauf gueltig; der Grund landet als
  Hinweis in `summary.json`.
- Neue Abhaengigkeit: `reportlab`.

### Web-Dashboard entfernt

- `llmbench serve`, `llmbench/server.py` und der gesamte `web/`-Ordner sind
  entfallen, ebenso die Abhaengigkeiten `fastapi` und `uvicorn` und das
  Extra `[web]`. Die Live-Anzeige im Terminal ersetzt es.

## 1.2.0

### Reproduzierbarkeit

- `summary.json` enthaelt jetzt die tatsaechlich verwendete Konfiguration,
  einen Konfigurations-Fingerabdruck, die llmbench-Version, den
  llama.cpp-Build und den SHA256 der llama-bench-Programmdatei.
- `llmbench compare` prueft vor dem Vergleich, ob die Laeufe ueberhaupt
  vergleichbar sind: Konfiguration, llama.cpp-Build, Modell-SHA256 und
  Profileinstellungen. Abweichungen stehen oben im Bericht.
- Neuer Schalter `llmbench compare --strict` fuer Exitcode 1 bei Abweichungen.
- Die automatische Suche nach llama.cpp durchsucht nicht mehr Arbeitsverzeichnis,
  PATH und Systempfade. Damit kann die bewusst eingefrorene Version nicht mehr
  unbemerkt durch eine andere ersetzt werden. Alte Verhalten per
  `--allow-system-search`.
- Die Modellerkennung durchsucht nur noch den Modellordner des Projekts,
  nicht mehr `C:/llm_models` oder `~/.cache/llama.cpp/models`.
- Modellnamen werden eindeutig vergeben. Zwei GGUF-Dateien mit gleichem
  Dateinamen ueberschreiben sich nicht mehr gegenseitig im Ergebnisordner.
- Ergebnisordner tragen UTC-Zeitstempel.

### Messmethodik

- `llama-server` wird mit denselben Kernparametern gestartet wie `llama-bench`
  (Batch, UBatch, Flash Attention, KV-Cache-Typen).
- Endpoint-Tests setzen `ignore_eos` und einen festen Seed, damit die
  Tokenzahl pro Request nicht mehr schwankt.
- Neue Aufwaermlaeufe vor der Messung (`endpoint.warmup_requests`).
- `benchmark.timeout_seconds` begrenzt jeden Einzeltest; Ueberschreitungen
  werden als `timeout` im Ergebnis vermerkt statt den Lauf haengen zu lassen.
- Der Monitor erkennt fremde Prozesse auf der GPU und vermerkt sie als Warnung;
  ausserdem wird ein Ruhewert vor der Last erfasst.
- Der Windows-Energieplan bzw. der Linux-CPU-Governor wird mit erfasst.

### Berichte

- Fehlgeschlagene und abgebrochene Tests sind im Vergleich als solche sichtbar
  statt als leere Zelle.
- Der Vergleich enthaelt jetzt auch Endpoint-Ergebnisse (System-TPS, TTFT) und
  eine Effizienztabelle in Tokens/s pro Watt.
- Alle GPUs werden angezeigt, nicht nur die erste.
- Fehlende TTFT-Werte erscheinen als "—" statt als 0,00 ms.
- Rohsamples der Telemetrie liegen nur noch in `raw_*.json`; `summary.json`
  bleibt dadurch auch nach langen Laeufen handhabbar.
- Berichte unterstuetzen den Dunkelmodus.

### Web-Dashboard

- Die CORS-Freigabe fuer beliebige Herkuenfte wurde entfernt.
- Zustandsaendernde Endpunkte pruefen die Fetch-Metadaten des Browsers.
  Eine fremde Webseite kann keine Benchmarks mehr starten und die
  Konfiguration nicht mehr ueberschreiben.
- `/api/runs/{id}` prueft den Pfad; Zugriffe ausserhalb des Ergebnisordners
  werden abgewiesen.
- `GET /api/config` liefert den Dateiinhalt wieder korrekt (war immer leer).
- Beim Speichern wird `benchmark.yaml.bak` angelegt, die Konfiguration
  validiert und `flash_attention` normalisiert.
- `--allow-remote` gibt das Dashboard bewusst ins Netz frei und erzwingt
  dann ein Zugriffstoken.

### Windows-Setup

- `START_BENCHMARK_CORE.ps1` ermittelt das llama.cpp-Release nicht mehr über
  `/releases/latest`. Diese Adresse liefert bei llama.cpp ein altes Release
  ohne Windows-Pakete, wodurch das Setup mit "Kein passendes llama.cpp-Asset
  gefunden" abbrach. Stattdessen wird die Release-Liste durchgegangen und das
  neueste Release genommen, das die benötigten Dateien wirklich enthält.
- Der llama.cpp-Build lässt sich festschreiben: `llama-cpp-version.txt`,
  Parameter `-LlamaCppTag` oder Umgebungsvariable `LLMBENCH_LLAMACPP_TAG`.
  Ohne Vorgabe hing die installierte Version davon ab, wann das Setup lief.
- Die CUDA-Erkennung greift auf die Treiberversion zurück, wenn der Kopf von
  `nvidia-smi` sich nicht auswerten lässt, und schreibt in die Ausgabe, woher
  der Wert stammt. Vorher fiel sie stillschweigend auf cuda-12.4 zurück.
- Alle PowerShell-Skripte werden als UTF-8 **mit BOM** gespeichert. Windows
  PowerShell 5.1 las sie sonst als ANSI, was jeden Umlaut zerlegte
  ("Systemprüfung" wurde zu "SystemprÃ¼fung").
- `START_BENCHMARK.bat` und `UPDATE_DEPENDENCIES.bat` reichen Argumente durch.
- Der Wrapper übergibt die Parameter per Hashtable-Splatting an das
  Core-Skript. Mit Array-Splatting konnte `-Config` als Wert durchrutschen,
  sodass `benchmark.yaml` im nächsten Parameter landete. Beide Skripte
  nutzen jetzt `[CmdletBinding()]` und binden gar nicht mehr positional.
- Ein vorgegebener llama.cpp-Tag wird auf Plausibilität geprüft, und ein
  nicht existierendes Release meldet das im Klartext statt als roher
  HTTP-404 aus `Invoke-RestMethod`. Das GitHub-Anfragelimit wird ebenfalls
  als solches benannt.
- Neue Vorlage `llama-cpp-version.txt` im Projektordner.
- Die Startprobe nach der Installation nutzt `--list-devices`; `llama-bench`
  kennt kein `--version`. Sie wertet zusätzlich aus, ob die Backends geladen
  wurden, und läuft über `Start-Process` mit getrennten Ausgabekanälen, damit
  stderr nicht als `NativeCommandError` die Meldung unlesbar macht.
- `llmbench doctor` prüft die Langformen der benötigten Optionen
  (`--flash-attn`, `--n-depth`, …). Die Kurzform `-d` kam auch in `-dev` und
  `--delay` vor und wäre nie als fehlend erkannt worden. Der Bericht zeigt
  jetzt die vom Build erkannten Geräte.
- Das Windows-Setup installiert das Paket jetzt mit den Web-Extras, wie
  `setup.bat` auch.

### Sonstiges

- Version an allen Stellen auf 1.2.0 vereinheitlicht.
- `setup.sh` und `setup.bat` installieren das Paket samt Web-Extras.
- `endpoint.api_key` wird jetzt tatsaechlich als Authorization-Header gesendet.
- Der Einrichtungsassistent fragt nach dem Servernamen.
- `llmbench doctor` prueft unterstuetzte llama-bench-Flags, VRAM-Passung
  und freien Speicherplatz.
- Ruff-Konfiguration in `pyproject.toml`, alle Befunde behoben.

## 1.1.1

- `winget` ist fuer die Python-Installation nicht mehr erforderlich.
- Fehlt Python 3.10+, wird Python 3.12.10 direkt von `python.org` heruntergeladen.
- Python wird projektlokal unter `.runtime/python` installiert; keine PATH-Aenderung
  und keine systemweite Installation erforderlich.
- Der offizielle Python-Installer wird vor der Ausfuehrung per SHA256 geprueft.
- Windows x64 und ARM64 werden unterstuetzt.
- `scripts/START_BENCHMARK.ps1` ist jetzt ein Bootstrap-Wrapper, sodass auch der
  direkte PowerShell-Start ohne winget funktioniert.

## 1.1.0

- Windows-One-Click-Setup ueber `START_BENCHMARK.bat`.
- Python 3.12 wird bei Bedarf automatisch eingerichtet.
- Virtuelle Umgebung und Python-Abhaengigkeiten werden automatisch eingerichtet.
- Aktuelles offizielles `llama.cpp`-Release wird automatisch geladen.
- Automatische Auswahl von CUDA 13.3, CUDA 12.4 oder CPU-Build.
- Passende CUDA-Runtime-DLLs werden automatisch installiert.
- Installierter llama.cpp-Build wird fuer reproduzierbare Tests eingefroren.
- `UPDATE_DEPENDENCIES.bat` fuer bewusstes Dependency-/llama.cpp-Update.
- Automatische Erkennung von GGUF-Modellen unter `models/`.
- Neue Modelle werden automatisch in `benchmark.yaml` eingetragen.
- Download-Verzeichnisse und GGUF-Dateien werden von Git ausgeschlossen.
- Neue Bootstrap-Tests.
