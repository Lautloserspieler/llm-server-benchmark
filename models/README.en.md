# Models

[🇩🇪 Deutsch](README.md) | 🇬🇧 English

Place the **GGUF files** you want to benchmark in this directory.

The next time `START_BENCHMARK.bat` is started, all `*.gguf` files in this folder and its
subdirectories are detected automatically and added to `benchmark.yaml`.

Example:

```text
models/
  gemma-12b-q4_0.gguf
  gpt-oss-20b-q4_0.gguf
  qwen-27b-q4_0.gguf
```

The model files themselves do **not** belong in the Git repository because of their size.
