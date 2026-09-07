[CmdletBinding()]
param(
    [ValidateSet('Setup','Run','Check')]
    [string]$Action = 'Run',
    [string]$Config = 'benchmark.yaml'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $Root 'compose.yaml'
$Image = if ($env:LLMBENCH_DOCKER_IMAGE) { $env:LLMBENCH_DOCKER_IMAGE } else { 'llm-server-benchmark:local' }
$SmokeImage = if ($env:LLMBENCH_CUDA_SMOKE_IMAGE) { $env:LLMBENCH_CUDA_SMOKE_IMAGE } else { 'nvidia/cuda:13.2.1-base-ubuntu24.04' }
$ConfigPath = if ([System.IO.Path]::IsPathRooted($Config)) { $Config } else { Join-Path $Root $Config }
$RuntimeDir = Join-Path $Root '.runtime'
$ReadyFile = Join-Path $RuntimeDir 'docker-ready'

function Invoke-Docker {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)
    & docker @Args
    if ($LASTEXITCODE -ne 0) { throw "docker $($Args -join ' ') ist fehlgeschlagen (Exitcode $LASTEXITCODE)." }
}

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)
    & docker compose -f $ComposeFile @Args
    if ($LASTEXITCODE -ne 0) { throw "docker compose $($Args -join ' ') ist fehlgeschlagen (Exitcode $LASTEXITCODE)." }
}

function Test-DockerDesktopReady {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { return $false }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) { return $false }
    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) { return $false }
    $osType = (& docker info --format '{{.OSType}}' 2>$null | Out-String).Trim()
    return ($osType -eq 'linux')
}

function Initialize-DockerEnvironment {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root 'models') | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $Root 'results') | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $Root '.cache\huggingface') | Out-Null
    New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
    if (-not (Test-Path $ConfigPath)) { New-Item -ItemType File -Path $ConfigPath | Out-Null }

    $env:LLMBENCH_UID = '0'
    $env:LLMBENCH_GID = '0'
    $env:LLMBENCH_HOSTNAME = if ($env:COMPUTERNAME) { $env:COMPUTERNAME } else { 'windows-docker' }
    $env:LLMBENCH_MODELS_DIR = Join-Path $Root 'models'
    $env:LLMBENCH_RESULTS_DIR = Join-Path $Root 'results'
    $env:LLMBENCH_CONFIG_FILE = $ConfigPath
    $env:LLMBENCH_HF_CACHE_DIR = Join-Path $Root '.cache\huggingface'
    $env:LLMBENCH_EXPECT_GPU = '1'
}

function Test-DockerGpu {
    Write-Host '[+] Pruefe NVIDIA-GPU in Docker Desktop / WSL2...' -ForegroundColor Cyan
    & docker run --rm --gpus all $SmokeImage nvidia-smi *> $null
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker Desktop kann die NVIDIA-GPU nicht an Linux-Container durchreichen. WSL2-Backend, WSL-Update und NVIDIA-Treiber pruefen.'
    }
}

function Set-ContainerImageId {
    $id = (& docker image inspect $Image --format '{{.Id}}' 2>$null | Out-String).Trim()
    if (-not $id) { throw "Docker-Image $Image wurde nicht gefunden." }
    $env:LLMBENCH_CONTAINER_IMAGE_ID = $id
    return $id
}

function Setup-DockerBenchmark {
    if (-not (Test-DockerDesktopReady)) {
        throw 'Docker Desktop mit Linux/WSL2-Backend ist nicht bereit.'
    }
    Initialize-DockerEnvironment
    Test-DockerGpu

    Write-Host '[+] Baue reproduzierbares CUDA-Benchmark-Image...' -ForegroundColor Cyan
    Invoke-Compose build llmbench
    $id = Set-ContainerImageId

    Invoke-Compose run --rm llmbench container-check
    Invoke-Compose run --rm llmbench container-setup
    Set-Content -Path $ReadyFile -Value $id -Encoding ascii
    Write-Host '[OK] Docker/CUDA Benchmark-Runtime ist bereit.' -ForegroundColor Green
}

function Test-DockerBenchmarkReady {
    if (-not (Test-Path $ReadyFile)) { return $false }
    if (-not (Test-DockerDesktopReady)) { return $false }
    try {
        Initialize-DockerEnvironment
        Set-ContainerImageId | Out-Null
        & docker compose -f $ComposeFile run --rm llmbench container-check *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Refresh-DockerConfig {
    Initialize-DockerEnvironment
    Set-ContainerImageId | Out-Null
    Invoke-Compose run --rm llmbench python -m llmbench bootstrap --config /workspace/benchmark.yaml --root /workspace --llama-dir /opt/llama.cpp --models-dir /workspace/models
    Invoke-Compose run --rm llmbench python -m llmbench doctor --config /workspace/benchmark.yaml
}

function Run-DockerBenchmark {
    if (-not (Test-DockerBenchmarkReady)) {
        throw 'Docker-Runtime ist nicht eingerichtet. Bitte zuerst setup.bat starten.'
    }
    Refresh-DockerConfig

    Write-Host ''
    Write-Host '=== Benchmark (Docker + CUDA) ===' -ForegroundColor Cyan
    Write-Host 'Wie lange soll der Test laufen?'
    Write-Host '  1: kurz (short)    - schnelle Ueberpruefung'
    Write-Host '  2: mittel (medium) - Standardwerte'
    Write-Host '  3: lang (long)     - praezise Ergebnisse'
    $choice = Read-Host 'Auswahl [1-3, Standard=2]'
    $duration = 'medium'
    if ($choice -eq '1') { $duration = 'short' }
    elseif ($choice -eq '3') { $duration = 'long' }

    Write-Host ''
    Write-Host 'Womit soll getestet werden?'
    Write-Host '  1: Nur CPU'
    Write-Host '  2: Nur GPU'
    Write-Host '  3: CPU und GPU (Standard, inkl. Dauerlast-Test)'
    $hwChoice = Read-Host 'Auswahl [1-3, Standard=3]'
    $hardware = 'both'
    if ($hwChoice -eq '1') { $hardware = 'cpu' }
    elseif ($hwChoice -eq '2') { $hardware = 'gpu' }

    $stressChoice = Read-Host 'Zusaetzliche V2-Stresstests (TTFT/Multi-Tenant/OOM/Quant) starten? [j/N]'
    $runArgs = @('run','--rm','llmbench','python','-m','llmbench','run','--config','/workspace/benchmark.yaml','--duration',$duration,'--hardware',$hardware)
    if ($stressChoice -match '^[jJyY]') { $runArgs += '--stress' }
    Set-ContainerImageId | Out-Null
    Invoke-Compose @runArgs
}

switch ($Action) {
    'Check' {
        if (Test-DockerBenchmarkReady) { exit 0 }
        exit 1
    }
    'Setup' { Setup-DockerBenchmark; exit 0 }
    'Run' { Run-DockerBenchmark; exit 0 }
}
