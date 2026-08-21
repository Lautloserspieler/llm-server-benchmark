# Changelog

## 1.1.0

- Windows-One-Click-Setup über `START_BENCHMARK.bat`.
- Python 3.12 wird bei Bedarf automatisch via `winget` installiert.
- Virtuelle Umgebung und Python-Abhängigkeiten werden automatisch eingerichtet.
- Aktuelles offizielles `llama.cpp`-Release wird automatisch geladen.
- Automatische Auswahl von CUDA 13.3, CUDA 12.4 oder CPU-Build.
- Passende CUDA-Runtime-DLLs werden automatisch installiert.
- Installierter llama.cpp-Build wird für reproduzierbare Tests eingefroren.
- `UPDATE_DEPENDENCIES.bat` für bewusstes Dependency-/llama.cpp-Update.
- Automatische Erkennung von GGUF-Modellen unter `models/`.
- Neue Modelle werden automatisch in `benchmark.yaml` eingetragen.
- Download-Verzeichnisse und GGUF-Dateien werden von Git ausgeschlossen.
- Neue Bootstrap-Tests.
