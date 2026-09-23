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

# Exitcode 3010 = "Neustart erforderlich" (Windows-Installer-Konvention).
$RebootExitCode = 3010
$DockerDesktopDir = Join-Path $env:ProgramFiles 'Docker\Docker'
$DockerDesktopExe = Join-Path $DockerDesktopDir 'Docker Desktop.exe'
$DockerCliDir = Join-Path $DockerDesktopDir 'resources\bin'

class RebootRequiredException : System.Exception {
    RebootRequiredException([string]$Message) : base($Message) {}
}

function Confirm-Install {
    param([string]$What)
    # LLMBENCH_AUTO_INSTALL=1 beantwortet alle Rueckfragen automatisch mit Ja
    # (z. B. fuer unbeaufsichtigte Installationen), =0 immer mit Nein.
    if ($env:LLMBENCH_AUTO_INSTALL -eq '1') {
        Write-Host "[+] $What wird installiert (LLMBENCH_AUTO_INSTALL=1)." -ForegroundColor Cyan
        return $true
    }
    if ($env:LLMBENCH_AUTO_INSTALL -eq '0') { return $false }
    if ([Console]::IsInputRedirected) { return $false }
    $answer = Read-Host "[?] $What fehlt. Jetzt automatisch herunterladen und installieren? [J/n]"
    return ($answer -eq '' -or $answer -match '^[jJyY]')
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
    Write-Host '[+] Pruefe WSL und Ubuntu...' -ForegroundColor Cyan
    if (Test-RebootPending) {
        throw [RebootRequiredException]::new('Eine vorherige WSL-/Windows-Installation wartet noch auf einen Neustart.')
    }

    $hasWsl = [bool](Get-Command wsl -ErrorAction SilentlyContinue)
    if ($hasWsl -and ((Get-WslDistros) -match 'Ubuntu')) {
        Write-Host '[OK] WSL und Ubuntu sind vorhanden.' -ForegroundColor Green
        return
    }

    $what = if ($hasWsl) { 'Ubuntu fuer WSL2' } else { 'WSL2 (Windows-Subsystem fuer Linux) mit Ubuntu' }
    if (-not (Confirm-Install $what)) {
        throw "$what wird fuer den Docker-Modus benoetigt, die Installation wurde abgelehnt."
    }

    Write-Host "[+] Installiere $what..." -ForegroundColor Cyan
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
        throw [RebootRequiredException]::new("$what wurde installiert, wird aber erst nach einem Neustart aktiv.")
    }
    Write-Host '[OK] WSL und Ubuntu sind installiert.' -ForegroundColor Green
}

function Add-DockerCliToPath {
    if ((Test-Path (Join-Path $DockerCliDir 'docker.exe')) -and ($env:PATH -notlike "*$DockerCliDir*")) {
        $env:PATH = "$DockerCliDir;$env:PATH"
    }
}

function Install-DockerDesktop {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host '[+] Installiere Docker Desktop ueber winget...' -ForegroundColor Cyan
        $oldEap = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            & winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements --silent
        } finally {
            $ErrorActionPreference = $oldEap
        }
        if (Test-Path $DockerDesktopExe) { return }
        Write-Host "[!] winget-Installation nicht erfolgreich (Exitcode $LASTEXITCODE). Versuche direkten Download..." -ForegroundColor Yellow
    }

    $arch = if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString() -eq 'Arm64') { 'arm64' } else { 'amd64' }
    $url = "https://desktop.docker.com/win/main/$arch/Docker%20Desktop%20Installer.exe"
    $installer = Join-Path ([System.IO.Path]::GetTempPath()) 'DockerDesktopInstaller.exe'
    try {
        try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }
        Write-Host "[+] Download: $url" -ForegroundColor Cyan
        $oldProgress = $ProgressPreference
        $ProgressPreference = 'SilentlyContinue'
        try {
            Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
        } finally {
            $ProgressPreference = $oldProgress
        }
        Write-Host '[+] Docker Desktop wird installiert (das kann einige Minuten dauern)...' -ForegroundColor Cyan
        $proc = Start-Process -FilePath $installer -ArgumentList 'install', '--quiet', '--accept-license', '--backend=wsl-2' -Wait -PassThru
        if ($proc.ExitCode -eq $RebootExitCode) {
            throw [RebootRequiredException]::new('Docker Desktop wurde installiert, wird aber erst nach einem Neustart aktiv.')
        }
        if ($proc.ExitCode -ne 0) { throw "Docker-Desktop-Installer fehlgeschlagen (Exitcode $($proc.ExitCode))." }
    } finally {
        Remove-Item $installer -Force -ErrorAction SilentlyContinue
    }
}

function Ensure-DockerDesktop {
    Write-Host '[+] Pruefe Docker Desktop...' -ForegroundColor Cyan
    Add-DockerCliToPath
    if (Test-DockerDesktopReady) {
        Write-Host '[OK] Docker Desktop laeuft mit Linux/WSL2-Backend.' -ForegroundColor Green
        return
    }

    $freshInstall = $false
    if (-not (Get-Command docker -ErrorAction SilentlyContinue) -and -not (Test-Path $DockerDesktopExe)) {
        if (-not (Confirm-Install 'Docker Desktop')) {
            throw 'Docker Desktop wird fuer den Docker-Modus benoetigt, die Installation wurde abgelehnt.'
        }
        Install-DockerDesktop
        Add-DockerCliToPath
        if (-not (Test-Path $DockerDesktopExe)) { throw 'Docker Desktop konnte nicht installiert werden.' }
        Write-Host '[OK] Docker Desktop wurde installiert.' -ForegroundColor Green
        $freshInstall = $true
    }

    if (Test-Path $DockerDesktopExe) {
        if (-not (Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)) {
            Write-Host '[+] Starte Docker Desktop...' -ForegroundColor Cyan
            Start-Process -FilePath $DockerDesktopExe | Out-Null
        }
        Write-Host '[+] Warte, bis Docker Desktop bereit ist (max. 5 Minuten)...' -ForegroundColor Cyan
        $deadline = (Get-Date).AddMinutes(5)
        $switched = $false
        while ((Get-Date) -lt $deadline) {
            if (Test-DockerDesktopReady) {
                Write-Host '[OK] Docker Desktop laeuft mit Linux/WSL2-Backend.' -ForegroundColor Green
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
                    Write-Host '[+] Docker Desktop nutzt Windows-Container; wechsle auf Linux/WSL2...' -ForegroundColor Yellow
                    & $cli -SwitchLinuxEngine
                    $switched = $true
                }
            }
            Start-Sleep -Seconds 5
        }
    }

    if ($freshInstall -or (Test-RebootPending -IncludeSystem)) {
        throw [RebootRequiredException]::new('Docker Desktop wurde eingerichtet, startet aber erst nach Neustart/Neuanmeldung korrekt.')
    }
    throw 'Docker Desktop mit Linux/WSL2-Backend ist nicht bereit. Bitte Docker Desktop oeffnen und Meldungen dort pruefen.'
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
    Write-Host '[+] Pruefe NVIDIA-GPU in Docker Desktop / WSL2...' -ForegroundColor Cyan
    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & docker run --rm --gpus all $SmokeImage nvidia-smi *> $null
    } finally {
        $ErrorActionPreference = $oldEap
    }
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker Desktop kann die NVIDIA-GPU nicht an Linux-Container durchreichen. WSL2-Backend, WSL-Update und NVIDIA-Treiber pruefen.'
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
    if (-not $id) { throw "Docker-Image $Image wurde nicht gefunden." }
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
        Write-Host "[+] Lade fertiges Benchmark-Image: $Image" -ForegroundColor Cyan
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
                Write-Host '[OK] GHCR-Image geladen und mit diesem Setup kompatibel; lokaler CUDA-Build wird uebersprungen.' -ForegroundColor Green
                return $id
            }
            Write-Host '[!] Das geladene GHCR-Image ist aelter als der lokale Setup-Code.' -ForegroundColor Yellow
            Write-Host '    Verhindere gemischte Versionen und baue das aktuelle Image lokal.' -ForegroundColor Yellow
        } else {
            Write-Host '[!] GHCR-Image konnte nicht geladen werden.' -ForegroundColor Yellow
            try {
                $id = Set-ContainerImageId
                if (Test-BenchmarkImageCompatible $Image) {
                    Write-Host "[+] Verwende bereits lokal vorhandenes kompatibles Image $Image." -ForegroundColor Yellow
                    return $id
                }
                Write-Host '[!] Lokal vorhandenes Image ist ebenfalls zu alt; lokaler Build wird verwendet.' -ForegroundColor Yellow
            } catch {
                Write-Host '[+] Kein lokales Image vorhanden; falle auf lokalen reproduzierbaren CUDA-Build zurueck.' -ForegroundColor Yellow
            }
        }
    } else {
        Write-Host '[+] LLMBENCH_DOCKER_BUILD_LOCAL=1: erzwinge lokalen CUDA-Build.' -ForegroundColor Yellow
    }

    Invoke-Compose build llmbench
    $id = Set-ContainerImageId
    if (-not (Test-BenchmarkImageCompatible $Image)) {
        throw 'Das frisch gebaute Docker-Image enthaelt die erwartete Modellauswahl nicht.'
    }
    return $id
}

function Setup-DockerBenchmark {
    Ensure-WslUbuntu
    Ensure-DockerDesktop
    Initialize-DockerEnvironment
    Test-DockerGpu

    $id = Ensure-BenchmarkImage
    Invoke-Compose run --rm llmbench container-check
    Invoke-Compose run --rm llmbench container-setup
    Set-Content -Path $ReadyFile -Value $id -Encoding ascii
    Set-Content -Path $ImageFile -Value $Image -Encoding ascii
    Write-Host '[OK] Docker/CUDA Benchmark-Runtime ist bereit.' -ForegroundColor Green
    Write-Host "     Image: $Image"
    Write-Host "     Image-ID: $id"
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
    Write-Host "[!] $($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host '[!] Bitte Windows neu starten und danach setup.bat erneut ausfuehren.' -ForegroundColor Yellow
    exit $RebootExitCode
} catch {
    Write-Host ''
    Write-Host "[!] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
