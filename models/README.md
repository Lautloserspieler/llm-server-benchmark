# Modelle

Lege hier die zu benchmarkenden **GGUF-Dateien** ab.

Beim nächsten Start von `START_BENCHMARK.bat` werden alle `*.gguf`-Dateien in diesem Ordner und seinen Unterordnern automatisch erkannt und in `benchmark.yaml` eingetragen.

Beispiel:

```text
models/
  gemma-12b-q4_0.gguf
  gpt-oss-20b-q4_0.gguf
  qwen-27b-q4_0.gguf
```

Die Modelldateien selbst gehören wegen ihrer Größe **nicht** ins Git-Repository.
