[CmdletBinding()]
param(
    [ValidateSet('Setup','Run','Check')]
    [string]$Action = 'Run',
    [string]$Config = 'benchmark.yaml'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $Root 'compose.yaml'
$Image = if ($env:LLMBENCH_DOCKER_IMAGE) { $env:LLMBENCH_DOCKER_IMAGE } else { 'ghcr.io/lautloserspieler/llm-server-benchmark:latest' }
$BuildLocal = ($env:LLMBENCH_DOCKER_BUILD_LOCAL -eq '1')
$SmokeImage = if ($env:LLMBENCH_CUDA_SMOKE_IMAGE) { $env:LLMBENCH_CUDA_SMOKE_IMAGE } else { 'nvidia/cuda:13.2.1-base-ubuntu24.04' }
$ConfigPath = if ([System.IO.Path]::IsPathRooted($Config)) { $Config } else { Join-Path $Root $Config }
$RuntimeDir = Join-Path $Root '.runtime'
$ReadyFile = Join-Path $RuntimeDir 'docker-ready'
$ImageFile = Join-Path $RuntimeDir 'docker-image'

Import-Module (Join-Path $PSScriptRoot 'lib\UI.psm1') -Force -DisableNameChecking
Initialize-LlmbenchUI

function Invoke-Docker {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)
    & docker @Args
    if ($LASTEXITCODE -ne 0) { throw (T 'docker.command_failed' "docker $($Args -join ' ')" $LASTEXITCODE) }
}

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)
    & docker compose -f $ComposeFile @Args
    if ($LASTEXITCODE -ne 0) { throw (T 'docker.command_failed' "docker compose $($Args -join ' ')" $LASTEXITCODE) }
}

# Exitcode 3010 = "Neustart erforderlich" (Windows-Installer-Konvention).
$RebootExitCode = 3010
$DockerDesktopDir = Join-Path $env:ProgramFiles 'Docker\Docker'
$DockerDesktopExe = Join-Path $DockerDesktopDir 'Docker Desktop.exe'
$DockerCliDir = Join-Path $DockerDesktopDir 'resources\bin'

class RebootRequiredException : System.Exception {
    RebootRequiredException([string]$Message) : base($Message) {}
}

function Test-RebootPending {
    # -IncludeSystem beruecksichtigt auch allgemeine Windows-Neustartmarker;
    # nur sinnvoll direkt nach einer eigenen Installation.
    param([switch]$IncludeSystem)
    foreach ($feature in 'Microsoft-Windows-Subsystem-Linux', 'VirtualMachinePlatform') {
        try {
            $state = (Get-WindowsOptionalFeature -Online -FeatureName $feature -ErrorAction Stop).State.ToString()
            if ($state -match 'Pending') { return $true }
        } catch { }
    }
    if (-not $IncludeSystem) { return $false }
    return (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending')
}

function Get-WslDistros {
    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        return ((& wsl -l -q 2>$null) -join ' ') -replace '\x00', ''
    } catch {
        return ''
    } finally {
        $ErrorActionPreference = $oldEap
    }
}

function Test-DockerDesktopReady {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { return $false }
    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & docker info *> $null
        if ($LASTEXITCODE -ne 0) { return $false }
        & docker compose version *> $null
        if ($LASTEXITCODE -ne 0) { return $false }
        $osType = (& docker info --format '{{.OSType}}' 2>$null | Out-String).Trim()
        return ($osType -eq 'linux')
    } finally {
        $ErrorActionPreference = $oldEap
    }
}

function Ensure-WslUbuntu {
    Write-UiStep (T 'wsl.check')
    if (Test-RebootPending) {
        throw [RebootRequiredException]::new((T 'wsl.reboot_pending'))
    }

    $hasWsl = [bool](Get-Command wsl -ErrorAction SilentlyContinue)
    if ($hasWsl -and ((Get-WslDistros) -match 'Ubuntu')) {
        Write-UiOk (T 'wsl.present')
        return
    }

    $what = if ($hasWsl) { T 'wsl.name_ubuntu' } else { T 'wsl.name_full' }
    if (-not (Confirm-Install $what)) {
        throw (T 'docker.declined' $what)
    }

    Write-UiStep (T 'ui.installing' $what)
    # Direkter Aufruf ohne Umleitung: Ubuntu fragt beim ersten Start ggf.
    # interaktiv nach Benutzername und Passwort.
    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & wsl --install -d Ubuntu
    } finally {
        $ErrorActionPreference = $oldEap
    }
    # Ist Ubuntu danach noch nicht registriert, wurden die Windows-Features
    # gerade erst aktiviert ("Aenderungen werden erst nach einem Neustart wirksam").
    if ((Test-RebootPending -IncludeSystem) -or -not ((Get-WslDistros) -match 'Ubuntu')) {
        throw [RebootRequiredException]::new((T 'ui.installed_needs_reboot' $what))
    }
    Write-UiOk (T 'wsl.installed')
}

function Add-DockerCliToPath {
    if ((Test-Path (Join-Path $DockerCliDir 'docker.exe')) -and ($env:PATH -notlike "*$DockerCliDir*")) {
        $env:PATH = "$DockerCliDir;$env:PATH"
    }
}

function Install-DockerDesktop {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-UiStep (T 'docker.install_winget')
        $oldEap = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            & winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements --silent
        } finally {
            $ErrorActionPreference = $oldEap
        }
        if (Test-Path $DockerDesktopExe) { return }
        Write-UiWarn (T 'docker.winget_failed' $LASTEXITCODE)
    }

    $arch = if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString() -eq 'Arm64') { 'arm64' } else { 'amd64' }
    $url = "https://desktop.docker.com/win/main/$arch/Docker%20Desktop%20Installer.exe"
    $installer = Join-Path ([System.IO.Path]::GetTempPath()) 'DockerDesktopInstaller.exe'
    try {
        Invoke-UiDownload $url $installer 'Docker Desktop'
        Write-UiStep (T 'docker.installing')
        $proc = Start-Process -FilePath $installer -ArgumentList 'install', '--quiet', '--accept-license', '--backend=wsl-2' -Wait -PassThru
        if ($proc.ExitCode -eq $RebootExitCode) {
            throw [RebootRequiredException]::new((T 'ui.installed_needs_reboot' 'Docker Desktop'))
        }
        if ($proc.ExitCode -ne 0) { throw (T 'docker.installer_failed' $proc.ExitCode) }
    } finally {
        Remove-Item $installer -Force -ErrorAction SilentlyContinue
    }
}

# Das CUDA-13-Image braucht einen NVIDIA-Treiber ab Version 580.
$MinNvidiaDriverMajor = 580
$NvidiaDriverUrl = 'https://www.nvidia.com/Download/index.aspx'

function Get-NvidiaSmiCommand {
    $cmd = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd }
    $fallback = Join-Path $env:SystemRoot 'System32\nvidia-smi.exe'
    if ($env:SystemRoot -and (Test-Path -LiteralPath $fallback)) { return (Get-Command $fallback) }
    return $null
}

function Test-NvidiaGpuPresent {
    try {
        return @(Get-CimInstance Win32_VideoController -ErrorAction Stop | Where-Object { $_.Name -match 'NVIDIA' }).Count -gt 0
    } catch {
        return $false
    }
}

function Request-NvidiaDriverDownload {
    # Treiber werden nie still installiert - nur die offizielle Downloadseite
    # wird auf Wunsch geoeffnet.
    Write-UiInfo $NvidiaDriverUrl
    if ((Test-UiInteractive) -and (Confirm-UiYesNo (T 'nvidia.open_download') -DefaultYes)) {
        Start-Process $NvidiaDriverUrl | Out-Null
    }
}

function Assert-NvidiaDriver {
    Write-UiStep (T 'nvidia.check')
    $smi = Get-NvidiaSmiCommand
    if (-not $smi) {
        if (-not (Test-NvidiaGpuPresent)) { throw (T 'nvidia.no_gpu') }
        Write-UiWarn (T 'nvidia.driver_missing')
        Request-NvidiaDriverDownload
        throw (T 'nvidia.driver_required' $MinNvidiaDriverMajor)
    }

    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $driver = (& $smi --query-gpu=driver_version --format=csv,noheader 2>$null | Select-Object -First 1)
    } finally {
        $ErrorActionPreference = $oldEap
    }
    $driver = if ($driver) { $driver.ToString().Trim() } else { '' }
    $major = 0
    if (-not ($driver -match '^(\d+)') -or -not [int]::TryParse($Matches[1], [ref]$major)) {
        Write-UiWarn (T 'nvidia.driver_unreadable')
        Request-NvidiaDriverDownload
        throw (T 'nvidia.driver_required' $MinNvidiaDriverMajor)
    }
    if ($major -lt $MinNvidiaDriverMajor) {
        Write-UiWarn (T 'nvidia.driver_old' $driver $MinNvidiaDriverMajor)
        Request-NvidiaDriverDownload
        throw (T 'nvidia.driver_required' $MinNvidiaDriverMajor)
    }
    Write-UiOk (T 'nvidia.driver_ok' $driver)
}

function Ensure-DockerDesktop {
    Write-UiStep (T 'docker.check')
    Add-DockerCliToPath
    if (Test-DockerDesktopReady) {
        Write-UiOk (T 'docker.ready')
        return
    }

    $freshInstall = $false
    if (-not (Get-Command docker -ErrorAction SilentlyContinue) -and -not (Test-Path $DockerDesktopExe)) {
        if (-not (Confirm-Install 'Docker Desktop')) {
            throw (T 'docker.declined' 'Docker Desktop')
        }
        Install-DockerDesktop
        Add-DockerCliToPath
        if (-not (Test-Path $DockerDesktopExe)) { throw (T 'docker.install_failed') }
        Write-UiOk (T 'docker.installed')
        $freshInstall = $true
    }

    if (Test-Path $DockerDesktopExe) {
        if (-not (Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)) {
            Write-UiStep (T 'docker.starting')
            Start-Process -FilePath $DockerDesktopExe | Out-Null
        }
        Write-UiStep (T 'docker.waiting')
        $deadline = (Get-Date).AddMinutes(5)
        $switched = $false
        while ((Get-Date) -lt $deadline) {
            if (Test-DockerDesktopReady) {
                Write-UiOk (T 'docker.ready')
                return
            }
            $cli = Join-Path $DockerDesktopDir 'DockerCli.exe'
            if (-not $switched -and (Test-Path $cli)) {
                $oldEap = $ErrorActionPreference
                $ErrorActionPreference = 'Continue'
                try {
                    $osType = (& docker info --format '{{.OSType}}' 2>$null | Out-String).Trim()
                } finally {
                    $ErrorActionPreference = $oldEap
                }
                if ($osType -eq 'windows') {
                    Write-UiWarn (T 'docker.switch_linux')
                    & $cli -SwitchLinuxEngine
                    $switched = $true
                }
            }
            Start-Sleep -Seconds 5
        }
    }

    if ($freshInstall -or (Test-RebootPending -IncludeSystem)) {
        throw [RebootRequiredException]::new((T 'docker.needs_relogin'))
    }
    throw (T 'docker.not_ready')
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
    $env:LLMBENCH_DOCKER_IMAGE = $Image
}

function Test-DockerGpu {
    Write-UiStep (T 'docker.gpu_check')
    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & docker run --rm --gpus all $SmokeImage nvidia-smi *> $null
    } finally {
        $ErrorActionPreference = $oldEap
    }
    if ($LASTEXITCODE -ne 0) {
        throw (T 'docker.gpu_failed')
    }
}

function Set-ContainerImageId {
    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $id = (& docker image inspect $Image --format '{{.Id}}' 2>$null | Out-String).Trim()
    } finally {
        $ErrorActionPreference = $oldEap
    }
    if (-not $id) { throw (T 'docker.image_missing' $Image) }
    $env:LLMBENCH_CONTAINER_IMAGE_ID = $id
    return $id
}

function Test-BenchmarkImageCompatible {
    param([string]$CandidateImage = $Image)

    # Der Setup-Flow benoetigt die selektive Modellauswahl. Dieser Probe verhindert,
    # dass ein neuer lokaler Entrypoint mit einem noch alten GHCR-Python-Paket gemischt wird.
    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & docker run --rm -e LLMBENCH_EXPECT_GPU=0 $CandidateImage `
            python -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('llmbench.model_select') else 42)" *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $oldEap
    }
}

function Ensure-BenchmarkImage {
    if (-not $BuildLocal) {
        Write-UiStep (T 'docker.image_pull' $Image)
        $oldEap = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            & docker pull $Image
        } finally {
            $ErrorActionPreference = $oldEap
        }
        if ($LASTEXITCODE -eq 0) {
            $id = Set-ContainerImageId
            if (Test-BenchmarkImageCompatible $Image) {
                Write-UiOk (T 'docker.image_ok')
                return $id
            }
            Write-UiWarn (T 'docker.image_old')
            Write-UiInfo (T 'docker.image_old_hint')
        } else {
            Write-UiWarn (T 'docker.image_pull_failed')
            try {
                $id = Set-ContainerImageId
                if (Test-BenchmarkImageCompatible $Image) {
                    Write-UiStep (T 'docker.image_local' $Image)
                    return $id
                }
                Write-UiWarn (T 'docker.image_local_old')
            } catch {
                Write-UiStep (T 'docker.image_build_fallback')
            }
        }
    } else {
        Write-UiStep (T 'docker.image_build_forced')
    }

    Invoke-Compose build llmbench
    $id = Set-ContainerImageId
    if (-not (Test-BenchmarkImageCompatible $Image)) {
        throw (T 'docker.image_build_incompatible')
    }
    return $id
}

function Setup-DockerBenchmark {
    # Zuerst: ohne passenden NVIDIA-Treiber ist der Docker-GPU-Modus sinnlos -
    # dann gar nicht erst WSL/Docker installieren, sondern nativ weitermachen.
    Assert-NvidiaDriver
    Ensure-WslUbuntu
    Ensure-DockerDesktop
    Initialize-DockerEnvironment
    Test-DockerGpu

    $id = Ensure-BenchmarkImage
    Invoke-Compose run --rm llmbench container-check
    Invoke-Compose run --rm llmbench container-setup
    Set-Content -Path $ReadyFile -Value $id -Encoding ascii
    Set-Content -Path $ImageFile -Value $Image -Encoding ascii
    Write-UiOk (T 'docker.runtime_ready')
    Write-UiInfo "Image: $Image"
    Write-UiInfo "Image-ID: $id"
}

function Test-DockerBenchmarkReady {
    if (-not (Test-Path $ReadyFile)) { return $false }
    if (-not (Test-DockerDesktopReady)) { return $false }
    try {
        Initialize-DockerEnvironment
        Set-ContainerImageId | Out-Null
        if (-not (Test-BenchmarkImageCompatible $Image)) { return $false }
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
        throw (T 'docker.runtime_missing')
    }
    Refresh-DockerConfig

    Write-UiHeader 'LLM Server Benchmark' (T 'run.subtitle_docker')
    $options = Read-BenchmarkOptions
    $runArgs = @('run','--rm','llmbench','python','-m','llmbench','run','--config','/workspace/benchmark.yaml','--duration',$options.Duration,'--hardware',$options.Hardware)
    if ($options.Stress) { $runArgs += '--stress' }
    Set-ContainerImageId | Out-Null
    Invoke-Compose @runArgs
}

if ($Action -eq 'Check') {
    Add-DockerCliToPath
    if (Test-DockerBenchmarkReady) { exit 0 }
    exit 1
}

try {
    switch ($Action) {
        'Setup' { Setup-DockerBenchmark }
        'Run' { Add-DockerCliToPath; Run-DockerBenchmark }
    }
    exit 0
} catch [RebootRequiredException] {
    Write-Host ''
    # Den Neustart-Dialog (automatisch fortsetzen?) zeigt der Aufrufer
    # (SETUP.ps1 bzw. START_BENCHMARK.ps1) ueber Invoke-RebootFlow.
    Write-UiWarn $_.Exception.Message
    exit $RebootExitCode
} catch {
    Write-Host ''
    Write-UiFail $_.Exception.Message
    exit 1
}
