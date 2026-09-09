# Linux: llama.cpp automatisch kompilieren

`llmbench install-llama-cpp` waehlt unter Linux automatisch einen passenden llama.cpp-Build und bevorzugt auf NVIDIA-Systemen den nativen CUDA-Pfad.

## Standardweg

```bash
./setup.sh
./START_BENCHMARK.sh
```

Oder manuell:

```bash
python -m llmbench install-llama-cpp --root .
```

Das Ergebnis landet unter:

```text
tools/llama.cpp/
  llama-bench
  llama-server
  .llama-build.json
```

## NVIDIA / CUDA – automatischer Standardpfad

Wenn alle folgenden Bedingungen erfuellt sind,

1. Linux auf `x64` oder `arm64`,
2. `nvidia-smi` erkennt mindestens eine NVIDIA-GPU,
3. ein CUDA Toolkit mit `nvcc` ist verfuegbar,
4. Source-Builds sind nicht deaktiviert,

baut `llmbench` llama.cpp **zuerst automatisch mit CUDA** aus dem offiziellen Quellcode:

```text
-DGGML_CUDA=ON
```

Ein vorhandener Vulkan-/CPU-Build wird in diesem Fall nicht stillschweigend weiterverwendet. Wenn der gespeicherte Backend-Typ nicht zur gewuenschten NVIDIA/CUDA-Konfiguration passt, wird die Installation neu aufgebaut.

Schlaegt der automatische CUDA-Build im Standardmodus `auto` fehl, kann der Installer auf einen passenden Vulkan-Release und danach CPU zurueckfallen. Mit einem explizit erzwungenen `cuda`-Backend wird ein CUDA-Fehler dagegen als Fehler gemeldet statt unbemerkt einen anderen Backend-Typ zu verwenden.

## Ubuntu/Debian-Abhaengigkeiten

Der Installer prueft `git`, `cmake`, `make` und einen C/C++-Compiler. Fehlen diese Werkzeuge und `apt-get` ist verfuegbar, versucht er automatisch:

```bash
sudo apt-get update
sudo apt-get install -y git build-essential cmake pkg-config
```

Das CUDA Toolkit selbst wird nicht als beliebiges Paket erraten. Fuer den NVIDIA-Pfad muss `nvcc` bereits ueber `PATH`, `CUDA_HOME`, `CUDA_PATH` oder typischerweise `/usr/local/cuda/bin/nvcc` gefunden werden.

Auf anderen Distributionen muessen die Build-Werkzeuge vorher manuell installiert werden.

## CUDA, Vulkan oder CPU erzwingen

Standard ist `auto`:

```bash
LLMBENCH_LLAMACPP_BUILD_BACKEND=auto python -m llmbench install-llama-cpp --root .
```

NVIDIA CUDA explizit erzwingen:

```bash
LLMBENCH_LLAMACPP_BUILD_BACKEND=cuda python -m llmbench install-llama-cpp --root . --force
```

CPU erzwingen:

```bash
LLMBENCH_LLAMACPP_BUILD_BACKEND=cpu python -m llmbench install-llama-cpp --root . --force
```

Vulkan erzwingen:

```bash
LLMBENCH_LLAMACPP_BUILD_BACKEND=vulkan python -m llmbench install-llama-cpp --root . --force
```

## Source-Build deaktivieren

Wenn nur vorgebaute Releases erlaubt sein sollen:

```bash
LLMBENCH_LLAMACPP_SOURCE_BUILD=0 python -m llmbench install-llama-cpp --root .
```

Dadurch steht der automatische native CUDA-Source-Build unter Linux nicht zur Verfuegung.

## Backend pruefen

Nach der Installation zeigt diese Datei, welcher Backend-Typ tatsaechlich installiert wurde:

```bash
cat tools/llama.cpp/.llama-build.json
```

Bei einem erfolgreichen nativen NVIDIA-Pfad stehen dort unter anderem:

```json
{
  "backend": "cuda",
  "source_build": true
}
```

## Build reproduzierbar halten

Ein fester llama.cpp-Stand kann ueber `llama-cpp-version.txt`, die Umgebungsvariable `LLMBENCH_LLAMACPP_TAG` oder `--tag` gesetzt werden:

```bash
echo b10604 > llama-cpp-version.txt
python -m llmbench install-llama-cpp --root . --force
```

Der verwendete Build-Typ, die Quelle und der Build-Pfad werden in `tools/llama.cpp/.llama-build.json` gespeichert und spaeter im Benchmark beruecksichtigt.
