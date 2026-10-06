# Docker + NVIDIA CUDA Runtime

[🇩🇪 Deutsch](DOCKER.md) | 🇬🇧 English

Since v1.5.0, `llm-server-benchmark` can run on Linux and Windows inside a reproducible CUDA container environment. For users, the existing entry points remain the normal way to start:

- Linux/macOS: `./setup.sh` and `./START_BENCHMARK.sh`
- Windows: `setup.bat` and `START_BENCHMARK.bat`

## Why Docker?

The container fixes the result-relevant software layer:

- Ubuntu 24.04 userspace
- NVIDIA CUDA 13.2.1 runtime/toolkit
- llama.cpp commit `64a155d242cb427766055ea9caea6f34df1ca94b` (Build 10808)
- Python and llmbench dependencies from the repository

The NVIDIA kernel driver remains on the host. The GPU is passed through with NVIDIA
Container Toolkit on Linux or Docker Desktop with WSL2 GPU virtualization on Windows.

## Prebuilt images from GHCR

The normal Docker path uses the image built by GitHub Actions:

```text
ghcr.io/lautloserspieler/llm-server-benchmark:latest
```

`setup.sh` or `setup.bat` first tries to pull this image. A local CUDA build is used only
when the image cannot be pulled, no suitable local image exists, or a local build was
explicitly requested.

Force a local build:

```bash
LLMBENCH_DOCKER_BUILD_LOCAL=1 ./setup.sh
```

Windows PowerShell:

```powershell
$env:LLMBENCH_DOCKER_BUILD_LOCAL = '1'
.\setup.bat
```

A different or immutable pinned image can be selected with `LLMBENCH_DOCKER_IMAGE`:

```bash
export LLMBENCH_DOCKER_IMAGE=ghcr.io/lautloserspieler/llm-server-benchmark:sha-<git-commit>
./setup.sh
```

For strict reproducibility, a `sha-<git-commit>` tag is preferable to `latest`, because
`latest` intentionally moves with new main builds.

### GitHub Actions image tags

The workflow `.github/workflows/docker-image.yml` uses Docker Buildx and GHCR:

- Pull requests: build and smoke-test the image, **do not** publish it.
- Push to `main`: publish `latest` and `sha-<full-commit>`.
- Git tag `vX.Y.Z`: additionally publish SemVer tags such as `X.Y.Z`, `X.Y`, and `X`.
- `workflow_dispatch`: manual build/smoke-test without a registry push.
- GitHub Actions cache accelerates CUDA/llama.cpp builds.
- SBOM and build provenance are generated for published OCI images.

GitHub Container Registry may initially create new container packages as private. If the
image should be pullable without registry authentication on arbitrary benchmark servers,
the GHCR package must be set to **Public**. If a pull fails, setup can still fall back to an
existing local image or a local CUDA build.

## Execution modes

Default:

```text
LLMBENCH_EXECUTION_MODE=auto
```

Possible values:

| Value | Behavior |
| --- | --- |
| `auto` | Prefer Docker/CUDA; fall back to the native path when the runtime is unavailable |
| `docker` | Require Docker/CUDA; fail instead of silently using native execution |
| `native` | Force the existing native benchmark path |

Linux examples:

```bash
LLMBENCH_EXECUTION_MODE=docker ./setup.sh
LLMBENCH_EXECUTION_MODE=docker ./START_BENCHMARK.sh
```

PowerShell examples:

```powershell
$env:LLMBENCH_EXECUTION_MODE = 'docker'
.\setup.bat
.\START_BENCHMARK.bat
```

## Linux

On Ubuntu/Debian, `setup.sh` attempts the following in Docker mode:

1. Install/configure Docker Engine, Buildx, and the Docker Compose plugin if Docker is missing.
2. Install NVIDIA Container Toolkit if `nvidia-ctk` is missing.
3. Run `nvidia-ctk runtime configure --runtime=docker`.
4. Restart the Docker daemon.
5. Test GPU passthrough with `nvidia-smi` inside an official NVIDIA CUDA container.
6. Pull the prebuilt GHCR image; build locally only when necessary.
7. Verify CUDA/NVIDIA visibility with `llama-bench --list-devices` inside the image.
8. Prepare models, configuration, and the doctor check inside the container.

On other Linux distributions, llmbench does not perform a system-wide Docker installation.
If Docker and the NVIDIA runtime are already configured correctly, the container path can
still be used.

Official references:

- Docker Engine: https://docs.docker.com/engine/install/
- Docker Compose GPU: https://docs.docker.com/compose/how-tos/gpu-support/
- NVIDIA Container Toolkit: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html

## Windows

Docker GPU support is used only when Docker Desktop runs with the Linux/WSL2 backend and the
real GPU smoke test succeeds. Docker Desktop documents NVIDIA GPU support on Windows for the
WSL2 backend path.

If Docker Desktop is not installed or GPU passthrough is unavailable, `auto` continues to
use the native Windows path.

Reference:

- https://docs.docker.com/desktop/features/gpu/

## Persistent data

Large data does **not** live inside the image:

```text
models/                 -> /workspace/models
results/                -> /workspace/results
benchmark.yaml          -> /workspace/benchmark.yaml
.cache/huggingface/     -> /workspace/.cache/huggingface
```

Models and results therefore survive container removal and do not have to be downloaded
again when switching images.

## GPU selection

By default, all GPUs provided by the NVIDIA runtime are visible:

```text
LLMBENCH_GPU_DEVICES=all
```

The Compose file reserves NVIDIA GPUs using `driver: nvidia`, `count: all`, and
`capabilities: [gpu]`.

## Customizing the image

Build defaults can be overridden without modifying the Dockerfile when a local build is
forced:

```bash
export LLMBENCH_DOCKER_BUILD_LOCAL=1
export LLMBENCH_CUDA_DEVEL_IMAGE=nvidia/cuda:13.2.1-devel-ubuntu24.04
export LLMBENCH_CUDA_RUNTIME_IMAGE=nvidia/cuda:13.2.1-runtime-ubuntu24.04
export LLMBENCH_LLAMA_CPP_COMMIT=64a155d242cb427766055ea9caea6f34df1ca94b
./setup.sh
```

These values are recorded in the locally built image and in benchmark metadata.

## Result metadata

`hardware.json` and therefore `summary.json` include fields under
`hardware.execution` such as:

```json
{
  "mode": "docker",
  "containerized": true,
  "container_runtime": "docker",
  "container_image_id": "sha256:...",
  "cuda_runtime_image": "nvidia/cuda:13.2.1-runtime-ubuntu24.04",
  "llama_cpp_commit": "64a155d242cb427766055ea9caea6f34df1ca94b",
  "gpu_devices": "all"
}
```

This records whether a result was produced natively or inside a container and which image
was actually used.

## CPU benchmarks in the container

Compose intentionally sets **no CPU or RAM limits**. The benchmark therefore sees the host
resources instead of accidentally measuring against an artificial container limit. On
Linux, the container runs with the UID/GID of the invoking user so `results/` and
`benchmark.yaml` do not become root-owned.

## Troubleshooting

Linux:

```bash
docker info
docker compose version
nvidia-smi
docker pull ghcr.io/lautloserspieler/llm-server-benchmark:latest
docker run --rm --gpus all nvidia/cuda:13.2.1-base-ubuntu24.04 nvidia-smi
docker compose run --rm llmbench container-check
```

Windows PowerShell:

```powershell
docker info
docker compose version
docker pull ghcr.io/lautloserspieler/llm-server-benchmark:latest
docker run --rm --gpus all nvidia/cuda:13.2.1-base-ubuntu24.04 nvidia-smi
powershell -File .\scripts\DOCKER_BENCHMARK.ps1 -Action Check
```

With `LLMBENCH_EXECUTION_MODE=auto`, a failed Docker setup still leaves the native
benchmark as a fallback. With `docker`, the run intentionally fails so a supposed Docker
benchmark cannot silently execute natively.
