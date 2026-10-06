# Linux: automatically building llama.cpp

[🇩🇪 Deutsch](linux-llamacpp-source-build.md) | 🇬🇧 English

On Linux, `llmbench install-llama-cpp` automatically selects a suitable llama.cpp build and
prefers the native CUDA path on NVIDIA systems.

## Standard path

```bash
./setup.sh
./START_BENCHMARK.sh
```

Or manually:

```bash
python -m llmbench install-llama-cpp --root .
```

The result is installed under:

```text
tools/llama.cpp/
  llama-bench
  llama-server
  .llama-build.json
```

## NVIDIA / CUDA — automatic default path

If all of the following conditions are true:

1. Linux on `x64` or `arm64`,
2. `nvidia-smi` detects at least one NVIDIA GPU,
3. a CUDA Toolkit with `nvcc` is available,
4. source builds are not disabled,

then `llmbench` first builds llama.cpp automatically from the official source with CUDA:

```text
-DGGML_CUDA=ON
```

An existing Vulkan/CPU build is not silently reused in this case. If the recorded backend
type does not match the requested NVIDIA/CUDA configuration, the installation is rebuilt.

If the automatic CUDA build fails in the default `auto` mode, the installer may fall back
to a suitable Vulkan release and then CPU. If `cuda` is explicitly forced, a CUDA failure
is reported as an error instead of silently switching backend type.

## Ubuntu/Debian dependencies

The installer checks for `git`, `cmake`, `make`, and a C/C++ compiler. If these tools
are missing and `apt-get` is available, it attempts:

```bash
sudo apt-get update
sudo apt-get install -y git build-essential cmake pkg-config
```

The CUDA Toolkit itself is not guessed as an arbitrary package. For the NVIDIA path,
`nvcc` must already be discoverable through `PATH`, `CUDA_HOME`, `CUDA_PATH`, or a
typical path such as `/usr/local/cuda/bin/nvcc`.

On other distributions, the build tools must be installed manually in advance.

## Force CUDA, Vulkan, or CPU

Default is `auto`:

```bash
LLMBENCH_LLAMACPP_BUILD_BACKEND=auto python -m llmbench install-llama-cpp --root .
```

Force NVIDIA CUDA:

```bash
LLMBENCH_LLAMACPP_BUILD_BACKEND=cuda python -m llmbench install-llama-cpp --root . --force
```

Force CPU:

```bash
LLMBENCH_LLAMACPP_BUILD_BACKEND=cpu python -m llmbench install-llama-cpp --root . --force
```

Force Vulkan:

```bash
LLMBENCH_LLAMACPP_BUILD_BACKEND=vulkan python -m llmbench install-llama-cpp --root . --force
```

## Disable source builds

To allow only prebuilt releases:

```bash
LLMBENCH_LLAMACPP_SOURCE_BUILD=0 python -m llmbench install-llama-cpp --root .
```

This disables the automatic native CUDA source-build path on Linux.

## Verify the backend

After installation, this file shows which backend type was actually installed:

```bash
cat tools/llama.cpp/.llama-build.json
```

For a successful native NVIDIA path it includes, among other fields:

```json
{
  "backend": "cuda",
  "source_build": true
}
```

## Keep the build reproducible

A fixed llama.cpp revision can be selected through `llama-cpp-version.txt`, the
`LLMBENCH_LLAMACPP_TAG` environment variable, or `--tag`:

```bash
echo b10604 > llama-cpp-version.txt
python -m llmbench install-llama-cpp --root . --force
```

The selected build type, source, and build path are stored in
`tools/llama.cpp/.llama-build.json` and later included in benchmark metadata.
