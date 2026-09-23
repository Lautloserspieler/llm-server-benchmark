# Changelog

## Unreleased

### Windows: llama.cpp weicht automatisch auf einen lauffaehigen Build aus

- Fix: Stuerzte der gewaehlte llama.cpp-Build beim ersten Start ab (z. B.
  `cuda-13.4` mit Exitcode `-1073741819` = `0xC0000005`, Zugriffsverletzung),
  brach das komplette Setup ab. Jetzt probiert das Setup eine Liste von Builds
  nacheinander: passende CUDA-Version (hoechste <= der vom Treiber gemeldeten),
  weitere derselben Hauptversion, aeltere CUDA-Hauptversion (z. B. `cuda-12.4`),
  Vulkan, CPU. Der erste Build, der startet, wird installiert.
- GPUs unter Compute Capability 7.5 (z. B. Pascal) ueberspringen CUDA-13-Builds;
  Grafikkarte und Compute Capability werden angezeigt.
- Verstaendliche Fehlercodes statt Zahlen (Absturz, fehlende DLL, fehlender
  CPU-Befehlssatz); Ausgabe aller Startproben in `.runtime/llama-probe.log`.
- Warnung, wenn statt CUDA nur Vulkan/CPU laeuft (Ergebnisse dann nicht mit
  CUDA-Servern vergleichbar). Ein bewusst gewaehlter Ausweich-Build wird im
  Zustand vermerkt und beim naechsten Start nicht wieder durch den
  abstuerzenden Build ersetzt.
- `LLMBENCH_LLAMACPP_BUILD_BACKEND=auto|cuda|vulkan|cpu` gilt jetzt auch unter
  Windows.
- Paketauswahl und Installation liegen im neuen Modul
  `scripts/lib/LlamaCpp.psm1` und sind mit pwsh-Tests abgedeckt.

### Setup: NVIDIA-Treiberpruefung, Neustart-Fortsetzung, Backend-Auswahl

- Windows: Vor dem Docker-GPU-Setup wird geprueft, ob eine NVIDIA-Karte und ein
  ausreichend neuer Treiber (ab 580, noetig fuer das CUDA-13-Image) vorhanden
  sind. Fehlt er oder ist er zu alt, gibt es eine klare Meldung und das Angebot,
  die offizielle NVIDIA-Treiberseite zu oeffnen - Treiber werden nie still
  installiert. WSL/Docker werden dann gar nicht erst installiert; der
  Auto-Modus macht nativ weiter.
- Braucht eine Installation einen Neustart, bietet das Setup an, nach der
  naechsten Anmeldung automatisch weiterzumachen (einmaliger RunOnce-Eintrag)
  und Windows direkt neu zu starten. Gilt jetzt auch fuer `START_BENCHMARK.bat`.
- Neue Backend-Auswahl im Setup (`python -m llmbench.backend_select`, Windows
  und Linux): Tabelle mit Status und Download-Groesse, Rueckfrage vor jedem
  Image-Download, anschliessend Wahl des Standard-Backends (`tools.backend`).
  Ohne Docker wird nichts versucht; ein fehlgeschlagenes optionales Backend
  bricht das Setup nicht ab.

### Sprachsystem ueberall + einheitliche Terminal-Oberflaeche

- Die Sprache (Deutsch/English) wird jetzt **ganz am Anfang** von
  `setup.bat`/`setup.sh` bzw. der Start-Skripte gewaehlt, in `.runtime/language`
  gespeichert und ueberall genutzt: Installer-Skripte, Python-CLI, Berichte und
  Docker-Container (`LLMBENCH_LANG` wird ueber `compose.yaml` durchgereicht).
- Alle Windows-Skripte (PowerShell) und Linux/macOS-Skripte (Bash) holen ihre
  Texte aus `scripts/locales/{de,en}.psd1` bzw. `{de,en}.sh` und nutzen
  gemeinsame UI-Helfer (`scripts/lib/UI.psm1`, `scripts/lib/ui.sh`): Kopfzeile,
  Abschnittslinien, farbige `[+]`/`[OK]`/`[!]`/`[X]`-Meldungen, nummerierte
  Menues mit markierter Vorauswahl, Ja/Nein-Fragen (`j/n` bzw. `y/n`) und ein
  Download-Fortschrittsbalken mit Tempo und Restzeit.
- `setup.bat`/`START_BENCHMARK.bat` sind nur noch duenne Starter; die Logik
  liegt in `scripts/SETUP.ps1` bzw. `scripts/START_BENCHMARK.ps1`.
- Modellauswahl, Setup-Wizard, Stresstests, Backend-Installation und
  Docker-Meldungen sind uebersetzt; die Modellauswahl zeigt eine Tabelle.
- Linux: `setup.sh` fragt jetzt ebenfalls vor jeder Installation (Python,
  Docker Engine, Compose-Plugin, NVIDIA Container Toolkit) und laeuft mit der
  Bash 3.2 von macOS.
- Neuer Test `tests/test_i18n_coverage.py` stellt sicher, dass jeder Text in
  allen Sprachen vorhanden ist; `tests/test_installer_scripts.py` fuehrt die
  Installer-Skripte mit Attrappen tatsaechlich aus (pwsh/bash).
- Fix: `llmbench bootstrap` (bei jedem Start ausgefuehrt) hat die gewaehlte
  Sprache in `benchmark.yaml` stets auf Deutsch zurueckgesetzt.
- Fix: Statusangaben "Zeitueberschreitung" erschienen in englischen Berichten
  auf Deutsch; fuenf PDF-Beschriftungen hatten keine englische Uebersetzung.

### Windows-Setup installiert fehlende Komponenten nach Rueckfrage

- `setup.bat` erkennt fehlendes WSL2/Ubuntu, Docker Desktop und Python 3.10+,
  fragt jeweils `[J/n]` und laedt/installiert die Komponente dann automatisch
  (Docker Desktop ueber winget bzw. offiziellen Installer, Python ueber den
  bestehenden SHA256-geprueften Bootstrap).
- Docker Desktop wird bei Bedarf gestartet und ggf. auf Linux-Container
  umgeschaltet; `setup.bat` wartet bis zu 5 Minuten, bis es bereit ist.
- Braucht eine Installation einen Neustart, endet das Setup mit einer klaren
  Meldung (Exitcode 3010) statt mit PowerShell-Stacktrace und faellt nicht
  mehr faelschlich auf den Native-Modus zurueck.
- `LLMBENCH_AUTO_INSTALL=1` installiert ohne Rueckfrage, `=0` nie.

## 1.6.0

### vLLM als zweites Backend (ueber Docker)

- Neues Backend `vllm`: `tools.backend: vllm` in `benchmark.yaml` benchmarkt
  einen vLLM-Server statt llama.cpp. vLLM laeuft dabei ausschliesslich als
  Docker-Container (offizielles Image `vllm/vllm-openai`) - kein lokales
  pip/venv-Setup noetig, und Windows (Docker Desktop/WSL2) sowie Linux
  (natives Docker) verhalten sich dadurch identisch.
- Prompt-/Generation-/Long-Context-Messungen laufen ueber kalibrierte
  HTTP-Requests gegen die OpenAI-kompatible `/v1/completions`-Schnittstelle
  (neues Modul `llmbench/http_bench.py`), inklusive Schutz gegen vLLMs
  Prefix-Caching (jeder Fuellprompt bekommt eine eindeutige Nonce, damit
  Wiederholungen nicht versehentlich einen Cache-Hit statt echter
  Prompt-Verarbeitung messen).
- Neue Befehle `llmbench install-backend --backend vllm` und
  `llmbench uninstall-backend --backend vllm [--purge-models]`: automatische
  Installation (Image-Pull) und restlose Deinstallation (Container, Image,
  optional das Modell-Volume) - kein Backend darf install-only sein.
- `llmbench compare --strict` lehnt jetzt Vergleiche zwischen Laeufen mit
  unterschiedlichem Backend ab (z. B. llama.cpp gegen vLLM), da Tokens/s
  zwischen Backends nicht direkt vergleichbar sind.
- `BenchmarkBackend` (Basisklasse fuer alle Backends) hat zwei neue,
  optionale Hooks `begin_profile`/`end_profile` fuer Backends, die den
  Server einmal pro Profil statt einmal pro Testart starten wollen -
  bestehende llama.cpp-Konfigurationen sind davon unberuehrt.

### AMD-GPU-Live-Telemetrie (rocm-smi)

- Neuer `AmdProvider` liefert erstmals laufende GPU-Auslastung, VRAM,
  Temperatur und Power fuer AMD-GPUs (`rocm-smi --json`), bisher gab es dort
  nur einmalige Hardware-Erkennung ohne Live-Werte.
- Bei mehreren gleichzeitig vorhandenen GPU-Herstellern nutzt ein neuer
  `CompositeProvider` jetzt alle verfuegbaren Quellen parallel, statt wie
  bisher nur den erstbesten Hersteller zu beruecksichtigen.
- Fix: `telemetry_source` in den Ergebnisdateien wurde bei Nicht-NVIDIA-
  Quellen faelschlich als `cpu_only` gemeldet, obwohl echte GPU-Messwerte
  vorlagen.

### Projekt-Infrastruktur

- Neu: `CONTRIBUTING.md`, `ROADMAP.md`, GitHub-Issue-/PR-Vorlagen unter
  `.github/` - Grundlage fuer die geplante Erweiterung um weitere Backends
  (Ollama, TGI) und GPU-Hersteller (Intel), siehe `ROADMAP.md`.

## 1.4.1

### Energiesparmodus-Warnung fuer Linux-Desktops (z. B. Ubuntu 24.04 LTS)

- `llmbench doctor` erkennt jetzt zusaetzlich das aktive Profil von
  `power-profiles-daemon` (Standard auf Ubuntu Desktop mit GNOME) und warnt,
  wenn es nicht auf "performance" steht - Ubuntu Desktop startet
  standardmaessig im Profil "balanced", was gegenueber Servern mit festem
  `cpupower`-Governor spuerbar Tokens/s kostet und Serverver­gleiche
  verfaelscht. Empfohlener Fix wird direkt mitgeliefert
  (`sudo powerprofilesctl set performance` bzw. `sudo cpupower frequency-set
  -g performance`, falls kein `power-profiles-daemon` laeuft).
- `hardware.json`/`report.html`/`report.pdf` zeigen im Feld "Energieplan"
  jetzt zusaetzlich zum CPU-Governor das aktive power-profiles-daemon-Profil
  an, falls vorhanden.

## 1.4.0

### Automatische llama.cpp-Installation unter Linux/macOS

- `setup.sh`, `START_BENCHMARK.sh` und `llmbench setup` installieren
  llama.cpp jetzt automatisch, statt mit einer Fehlermeldung abzubrechen,
  wenn `llama-bench`/`llama-server` unter `tools/llama.cpp/` fehlen -
  analog zum bisherigen Windows-Verhalten in `START_BENCHMARK_CORE.ps1`.
- Neues Modul `llmbench/llama_cpp_setup.py` laedt den passenden vorgebauten
  Release von GitHub (`ggml-org/llama.cpp`): bei erkannter GPU zuerst einen
  Vulkan-Build (`llama-*-bin-ubuntu-vulkan-<arch>.tar.gz`, funktioniert auch
  auf NVIDIA-/AMD-/Intel-GPUs, da llama.cpp fuer Linux keine vorgebauten
  CUDA-Pakete veroeffentlicht), sonst bzw. wenn der Vulkan-Build auf dem
  Zielsystem nicht startet (z. B. fehlender Vulkan-Treiber) automatisch
  einen CPU-Build (`llama-*-bin-ubuntu-<arch>.tar.gz`). macOS nutzt den
  passenden `llama-*-bin-macos-<arch>.tar.gz`-Release (Metal ist bei arm64
  bereits eingebaut).
- Neuer Befehl `llmbench install-llama-cpp [--root .] [--tag b10604] [--force]`
  fuer die manuelle Installation oder ein festes Build-Pin, analog zu
  `START_BENCHMARK.bat -LlamaCppTag`. Respektiert wie unter Windows
  `llama-cpp-version.txt` bzw. die Umgebungsvariable `LLMBENCH_LLAMACPP_TAG`.
- Ein bereits vorhandener, lauffaehiger Build wird nicht neu heruntergeladen
  (Pruefung ueber `.llama-build.json` und einen Startprobe-Aufruf).

### Farbige Ergebnisuebersicht im Terminal

- `llmbench run` zeigt die Ergebnisse nach jedem Lauf jetzt zusaetzlich direkt
  im Terminal an - mit denselben Abschnitten wie `report.html`/`report.pdf`
  (Hardware-Karten, Testbedingungen, Bench-/Telemetrie-Tabellen je Profil,
  Endpoint- und Dauerlastwerte, Hinweise), farbig formatiert ueber `rich`.
  Praktisch fuer Linux-Server, die per SSH ohne Desktop betrieben werden und
  wo man `report.html`/`report.pdf` nicht direkt oeffnet.
- `--plain` sowie eine Umleitung in eine Datei (kein echtes Terminal) schalten
  automatisch auf die bisherige einfache Klartexttabelle ohne Farben und
  Rahmen um.

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
- Ergebnisse stehen in `report.html`, `report.pdf`, `summary.json`
  (`models[].soak`) sowie in `comparison.html` und `comparison.pdf`.
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
