# Linux: llama.cpp automatisch kompilieren

`llmbench install-llama-cpp` versucht unter Linux zuerst weiterhin einen passenden
vorgebauten llama.cpp-Release zu verwenden. Wenn kein passendes Paket gefunden
wird oder der Release-Build auf dem Zielsystem nicht startet, kompiliert
`llmbench` llama.cpp automatisch aus dem offiziellen Quellcode.

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

## Ubuntu/Debian-Abhaengigkeiten

Der Installer prueft `git`, `cmake`, `make` und einen C/C++-Compiler. Fehlen
diese Werkzeuge und `apt-get` ist verfuegbar, versucht er automatisch:

```bash
sudo apt-get update
sudo apt-get install -y git build-essential cmake pkg-config
```

Auf anderen Distributionen muessen die Build-Werkzeuge vorher manuell
installiert werden.

## CUDA, Vulkan oder CPU erzwingen

Standard ist `auto`:

1. CUDA, wenn `nvcc` bzw. ein CUDA Toolkit gefunden wird
2. CPU als stabiler Fallback

Manuell steuerbar:

```bash
LLMBENCH_LLAMACPP_BUILD_BACKEND=cuda python -m llmbench install-llama-cpp --root . --force
LLMBENCH_LLAMACPP_BUILD_BACKEND=cpu  python -m llmbench install-llama-cpp --root . --force
```

Vulkan ist ebenfalls moeglich, wenn die Vulkan-Entwicklungsdateien auf dem
System installiert sind:

```bash
LLMBENCH_LLAMACPP_BUILD_BACKEND=vulkan python -m llmbench install-llama-cpp --root . --force
```

## Source-Build deaktivieren

Wenn nur vorgebaute Releases erlaubt sein sollen:

```bash
LLMBENCH_LLAMACPP_SOURCE_BUILD=0 python -m llmbench install-llama-cpp --root .
```

## Build reproduzierbar halten

Ein fester llama.cpp-Stand kann weiterhin ueber `llama-cpp-version.txt`, die
Umgebungsvariable `LLMBENCH_LLAMACPP_TAG` oder `--tag` gesetzt werden:

```bash
echo b10604 > llama-cpp-version.txt
python -m llmbench install-llama-cpp --root . --force
```

Der verwendete Build-Typ, die Quelle und der Build-Pfad werden in
`tools/llama.cpp/.llama-build.json` gespeichert und spaeter im Benchmark
beruecksichtigt.
