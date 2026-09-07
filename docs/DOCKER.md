# Docker + NVIDIA CUDA Runtime

Seit v1.5.0 kann `llm-server-benchmark` unter Linux und Windows in einer reproduzierbaren CUDA-Container-Umgebung laufen. Fuer Nutzer bleiben **nur die vorhandenen Einstiegspunkte** relevant:

- Linux/macOS: `./setup.sh` und `./START_BENCHMARK.sh`
- Windows: `setup.bat` und `START_BENCHMARK.bat`

## Warum Docker?

Der Container fixiert die ergebnisrelevante Software-Schicht:

- Ubuntu 24.04 Userspace
- NVIDIA CUDA 13.2.1 Runtime/Toolkit
- llama.cpp Commit `64a155d242cb427766055ea9caea6f34df1ca94b` (Build 10808)
- Python- und llmbench-Abhaengigkeiten aus dem Repository

Der NVIDIA Kernel-Treiber bleibt auf dem Host. Die GPU wird ueber NVIDIA Container Toolkit (Linux) bzw. Docker Desktop mit WSL2-GPU-PV (Windows) durchgereicht.

## Fertige Images aus GHCR

Der normale Docker-Pfad verwendet standardmaessig das von GitHub Actions gebaute Image:

```text
ghcr.io/lautloserspieler/llm-server-benchmark:latest
```

`setup.sh` bzw. `setup.bat` versucht zuerst, dieses Image zu laden. Ein lokaler CUDA-Build wird nur noch verwendet, wenn das Image nicht geladen werden kann, kein passendes Image lokal vorhanden ist oder ein lokaler Build explizit erzwungen wurde.

Lokalen Build erzwingen:

```bash
LLMBENCH_DOCKER_BUILD_LOCAL=1 ./setup.sh
```

Windows PowerShell:

```powershell
$env:LLMBENCH_DOCKER_BUILD_LOCAL = '1'
.\setup.bat
```

Ein anderes oder unveraenderlich gepinntes Image kann ueber `LLMBENCH_DOCKER_IMAGE` verwendet werden:

```bash
export LLMBENCH_DOCKER_IMAGE=ghcr.io/lautloserspieler/llm-server-benchmark:sha-<git-commit>
./setup.sh
```

Fuer streng reproduzierbare Serververgleiche ist ein `sha-<git-commit>`-Tag besser als `latest`, weil `latest` absichtlich mit neuen Main-Builds weiterwandert.

### GitHub Actions Image-Tags

Die Workflow-Datei `.github/workflows/docker-image.yml` verwendet Docker Buildx und GHCR:

- Pull Requests: Image bauen und Smoke-Test ausfuehren, **nicht** veroeffentlichen.
- Push auf `main`: `latest` und `sha-<vollstaendiger-commit>` veroeffentlichen.
- Git-Tag `vX.Y.Z`: zusaetzlich SemVer-Tags wie `X.Y.Z`, `X.Y` und `X` veroeffentlichen.
- `workflow_dispatch`: manueller Build/Smoke-Test ohne Registry-Push.
- GitHub Actions Cache beschleunigt den CUDA-/llama.cpp-Build.
- SBOM und Build-Provenance werden mit dem veroeffentlichten OCI-Image erzeugt.

GitHub Container Registry erzeugt neue Container-Pakete gegebenenfalls zunaechst privat. Soll das Image ohne Registry-Login auf beliebigen Benchmark-Servern gepullt werden, muss das GHCR-Paket auf **Public** stehen. Falls ein Pull nicht moeglich ist, faellt das Setup weiterhin auf ein bereits vorhandenes lokales Image bzw. den lokalen CUDA-Build zurueck.

## Ausfuehrungsmodi

Standard ist:

```text
LLMBENCH_EXECUTION_MODE=auto
```

Moegliche Werte:

| Wert | Verhalten |
| --- | --- |
| `auto` | Docker/CUDA bevorzugen, bei fehlender Runtime auf den nativen Pfad zurueckfallen |
| `docker` | Docker/CUDA erzwingen; Fehler statt Native-Fallback |
| `native` | bisherigen nativen Benchmark erzwingen |

Linux-Beispiele:

```bash
LLMBENCH_EXECUTION_MODE=docker ./setup.sh
LLMBENCH_EXECUTION_MODE=docker ./START_BENCHMARK.sh
```

PowerShell-Beispiele:

```powershell
$env:LLMBENCH_EXECUTION_MODE = 'docker'
.\setup.bat
.\START_BENCHMARK.bat
```

## Linux

Auf Ubuntu/Debian versucht `setup.sh` im Docker-Modus automatisch:

1. Docker Engine + Buildx + Docker Compose Plugin einzurichten, falls Docker fehlt.
2. NVIDIA Container Toolkit zu installieren, falls `nvidia-ctk` fehlt.
3. `nvidia-ctk runtime configure --runtime=docker` auszufuehren.
4. den Docker-Daemon neu zu starten.
5. mit einem offiziellen NVIDIA-CUDA-Container `nvidia-smi` zu testen.
6. das fertige GHCR-Image zu laden; nur bei Bedarf lokal zu bauen.
7. im Image `llama-bench --list-devices` auf CUDA/NVIDIA zu pruefen.
8. Modelle, Konfiguration und Doctor-Check innerhalb des Containers vorzubereiten.

Auf anderen Linux-Distributionen wird keine systemweite Docker-Installation vorgenommen. Ist Docker/NVIDIA Runtime dort bereits korrekt eingerichtet, kann der Container trotzdem verwendet werden.

Offizielle Referenzen:

- Docker Engine: https://docs.docker.com/engine/install/
- Docker Compose GPU: https://docs.docker.com/compose/how-tos/gpu-support/
- NVIDIA Container Toolkit: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html

## Windows

Docker-GPU-Support wird nur verwendet, wenn Docker Desktop mit Linux/WSL2-Backend laeuft und der echte GPU-Smoke-Test erfolgreich ist. Docker Desktop dokumentiert NVIDIA-GPU-Support unter Windows fuer den WSL2-Backend-Pfad.

Ist Docker Desktop nicht installiert oder die GPU nicht durchreichbar, verwendet `auto` weiterhin den bestehenden nativen Windows-Pfad.

Referenz:

- https://docs.docker.com/desktop/features/gpu/

## Persistente Daten

Die grossen Daten liegen **nicht im Image**:

```text
models/                 -> /workspace/models
results/                -> /workspace/results
benchmark.yaml          -> /workspace/benchmark.yaml
.cache/huggingface/     -> /workspace/.cache/huggingface
```

Dadurch bleiben Modelle und Resultate nach dem Entfernen eines Containers erhalten und muessen beim Image-Wechsel nicht neu geladen werden.

## GPU-Auswahl

Standardmaessig werden alle vom NVIDIA Runtime bereitgestellten GPUs sichtbar gemacht:

```text
LLMBENCH_GPU_DEVICES=all
```

Die Compose-Datei reserviert NVIDIA-GPUs mit `driver: nvidia`, `count: all` und `capabilities: [gpu]`.

## Image anpassen

Die Build-Defaults koennen ohne Aenderung am Dockerfile ueberschrieben werden, wenn ein lokaler Build erzwungen wird:

```bash
export LLMBENCH_DOCKER_BUILD_LOCAL=1
export LLMBENCH_CUDA_DEVEL_IMAGE=nvidia/cuda:13.2.1-devel-ubuntu24.04
export LLMBENCH_CUDA_RUNTIME_IMAGE=nvidia/cuda:13.2.1-runtime-ubuntu24.04
export LLMBENCH_LLAMA_CPP_COMMIT=64a155d242cb427766055ea9caea6f34df1ca94b
./setup.sh
```

Die Werte werden in das lokal gebaute Image und in die Benchmark-Metadaten uebernommen.

## Ergebnis-Metadaten

`hardware.json` und damit auch `summary.json` enthalten unter `hardware.execution` unter anderem:

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

Damit ist spaeter nachvollziehbar, ob ein Ergebnis nativ oder im Container erzeugt wurde und welches konkrete Image lokal ausgefuehrt wurde.

## CPU-Benchmarks im Container

Compose setzt absichtlich **keine CPU- oder RAM-Limits**. Dadurch sieht der Benchmark die Host-Ressourcen, statt versehentlich gegen ein kuenstliches Container-Limit zu messen. Auf Linux wird der Container mit der UID/GID des aufrufenden Nutzers gestartet, damit `results/` und `benchmark.yaml` nicht root gehoeren.

## Fehlerdiagnose

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

Wenn `LLMBENCH_EXECUTION_MODE=auto` gesetzt ist, bleibt bei einem fehlgeschlagenen Docker-Setup der native Benchmark als Fallback erhalten. Bei `docker` wird dagegen bewusst abgebrochen, damit ein vermeintlicher Docker-Test nicht unbemerkt nativ laeuft.
