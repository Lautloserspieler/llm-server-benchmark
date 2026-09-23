[CmdletBinding()]
param(
    [string]$Config = "benchmark.yaml",
    [string]$LlamaCppTag = "",
    [switch]$SetupOnly,
    [switch]$ForceUpdateLlamaCpp
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$EnsurePython = Join-Path $PSScriptRoot "ENSURE_PYTHON.ps1"
$CoreScript = Join-Path $PSScriptRoot "START_BENCHMARK_CORE.ps1"
$RuntimeRoot = Join-Path $Root ".runtime"
$LocalPythonDir = Join-Path $RuntimeRoot "python"
$PythonPathFile = Join-Path $RuntimeRoot "python-path.txt"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$LlamaDir = Join-Path $Root "tools\llama.cpp"
$LlamaBench = Join-Path $LlamaDir "llama-bench.exe"
$LlamaServer = Join-Path $LlamaDir "llama-server.exe"
$LlamaState = Join-Path $LlamaDir ".llama-build.json"
$ModelsDir = Join-Path $Root "models"
$ConfigPath = if ([System.IO.Path]::IsPathRooted($Config)) { $Config } else { Join-Path $Root $Config }

Import-Module (Join-Path $PSScriptRoot "lib\UI.psm1") -Force -DisableNameChecking
Initialize-LlmbenchUI
Select-LlmbenchLanguage | Out-Null
$PowerShellExe = (Get-Process -Id $PID).Path
$DockerScript = Join-Path $PSScriptRoot "DOCKER_BENCHMARK.ps1"

if (-not (Test-Path $EnsurePython)) { throw (T 'start.missing_file' $EnsurePython) }
if (-not (Test-Path $CoreScript)) { throw (T 'start.missing_file' $CoreScript) }

# Wenn im Setup eine Modellauswahl gespeichert wurde, pruefen/nachladen wir
# spaeter nur diese Modelle statt wieder die komplette Standard-Suite.
if (Test-Path (Join-Path $ModelsDir ".llmbench-model-selection.json")) { $env:LLMBENCH_USE_SAVED_SELECTION = "1" }

Write-UiHeader "LLM Server Benchmark" (T 'start.subtitle')

# --- Docker-Modus (auto/docker) --------------------------------------------
$Mode = if ($env:LLMBENCH_EXECUTION_MODE) { $env:LLMBENCH_EXECUTION_MODE.ToLowerInvariant() } else { "auto" }
if (@("auto", "docker", "native") -notcontains $Mode) {
    Write-UiFail (T 'setup.invalid_mode')
    exit 1
}
if ($Mode -ne "native") {
    & $PowerShellExe -NoProfile -ExecutionPolicy Bypass -File $DockerScript -Action Check *> $null
    $dockerReady = ($LASTEXITCODE -eq 0)
    if (-not $dockerReady -and $Mode -eq "docker") {
        Write-UiWarn (T 'start.docker_setup_now')
        & $PowerShellExe -NoProfile -ExecutionPolicy Bypass -File $DockerScript -Action Setup
        $rc = $LASTEXITCODE
        if ($rc -eq 3010) { Invoke-RebootFlow 'START_BENCHMARK.bat' }
        if ($rc -ne 0) { exit $rc }
        $dockerReady = $true
    }
    if ($dockerReady) {
        & $PowerShellExe -NoProfile -ExecutionPolicy Bypass -File $DockerScript -Action Run
        exit $LASTEXITCODE
    }
}
# Nativer Windows-Fallback. Dieser Pfad bleibt fuer Systeme ohne Docker Desktop
# bzw. ohne WSL2-GPU-Unterstuetzung voll funktionsfaehig.

# --- Automatisches Update via git pull (falls git vorhanden und .git-Verzeichnis existiert) ---
$GitDir = Join-Path $Root ".git"
if ((Test-Path $GitDir) -and (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-UiStep (T 'start.update_check')
    try {
        $fetchResult = & git -C $Root fetch --quiet 2>&1
        $status = & git -C $Root status -uno --short 2>&1
        if ($status -match "behind") {
            Write-UiStep (T 'start.update_available')
            & git -C $Root pull --ff-only --quiet 2>&1 | Out-Null
            Write-UiOk (T 'start.update_done')
        }
    } catch {
        Write-UiInfo (T 'start.update_skipped' $_.Exception.Message)
    }
} elseif (-not (Test-Path $GitDir)) {
    Write-UiWarn (T 'start.zip_hint')
    Write-UiInfo "git clone https://github.com/Lautloserspieler/llm-server-benchmark.git"
}

& $EnsurePython
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$ResolvedPython = $null
if (Test-Path $PythonPathFile) {
    $ResolvedPython = (Get-Content $PythonPathFile -Raw).Trim()
}

if ($ResolvedPython -and (Test-Path $ResolvedPython)) {
    $PythonDir = Split-Path -Parent $ResolvedPython
    $env:PATH = "$PythonDir;$PythonDir\Scripts;$env:PATH"
    Write-UiInfo (T 'start.python_used' $ResolvedPython)
} elseif (Test-Path (Join-Path $LocalPythonDir "python.exe")) {
    $ResolvedPython = Join-Path $LocalPythonDir "python.exe"
    $env:PATH = "$LocalPythonDir;$LocalPythonDir\Scripts;$env:PATH"
    Write-UiInfo (T 'start.python_used' $ResolvedPython)
} else {
    throw (T 'start.python_path_missing')
}

function Test-BenchmarkInstallationReady {
    if (-not (Test-Path $VenvPython -PathType Leaf)) { return $false }
    if (-not (Test-Path $ConfigPath -PathType Leaf)) { return $false }
    if (-not (Test-Path $LlamaBench -PathType Leaf)) { return $false }
    if (-not (Test-Path $LlamaServer -PathType Leaf)) { return $false }
    if (-not (Test-Path $LlamaState -PathType Leaf)) { return $false }

    try {
        & $VenvPython -c "import llmbench, yaml, pydantic, psutil, rich, huggingface_hub" *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Get-DoctorData {
    $doctorJsonText = (& $VenvPython -m llmbench doctor --config $Config --json | Out-String).Trim()
    if (-not $doctorJsonText) { throw (T 'start.doctor_no_data') }
    try {
        return ($doctorJsonText | ConvertFrom-Json)
    } catch {
        throw (T 'start.doctor_parse_failed' $_.Exception.Message)
    }
}

function Ensure-V2ModelSuite {
    New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null

    & $VenvPython -m llmbench download --suite all --models-dir $ModelsDir --verify-only *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-UiOk (T 'start.suite_complete')
        return
    }

    Write-UiSection (T 'start.suite_incomplete')
    Write-UiInfo (T 'start.suite_download_hint')
    & $VenvPython -m llmbench download --suite all --models-dir $ModelsDir
    if ($LASTEXITCODE -ne 0) {
        throw (T 'start.download_failed' $LASTEXITCODE)
    }

    & $VenvPython -m llmbench download --suite all --models-dir $ModelsDir --verify-only
    if ($LASTEXITCODE -ne 0) {
        throw (T 'start.suite_still_incomplete')
    }
}

function Invoke-BenchmarkRun {
    Write-UiOk (T 'start.installation_found')

    Ensure-V2ModelSuite

    # Bootstrap entfernt auch alte, versehentlich eingetragene Folge-Shards und
    # bindet gesplittete GGUFs nur ueber 00001-of-XXXXX ein.
    & $VenvPython -m llmbench bootstrap --config $Config --root $Root --llama-dir $LlamaDir --models-dir $ModelsDir
    if ($LASTEXITCODE -ne 0) { throw (T 'start.bootstrap_failed') }

    $doctorData = Get-DoctorData
    $configuredModels = @($doctorData.models)
    if ($configuredModels.Count -eq 0) {
        throw (T 'start.no_models_configured')
    }

    Write-UiSection (T 'start.models_title' $configuredModels.Count)
    foreach ($model in $configuredModels) {
        if ($model.exists) { Write-UiOk "$($model.name)" } else { Write-UiFail (T 'start.model_missing' $model.name $model.path) }
    }

    Write-UiSection (T 'start.doctor_title')
    & $VenvPython -m llmbench doctor --config $Config
    if ($LASTEXITCODE -ne 0) { throw (T 'start.doctor_failed') }

    $options = Read-BenchmarkOptions
    $hardware = $options.Hardware
    if ($hardware -eq "cpu") {
        # Pruefen ob ein GPU-Backend installiert ist - CUDA-Builds schlagen bei reinen CPU-Tests fehl
        $backendFile = Join-Path $PSScriptRoot "..\llama_cpp_state.json"
        $isCudaBuild = $false
        if (Test-Path $backendFile) {
            try {
                $state = Get-Content $backendFile -Raw | ConvertFrom-Json
                if ($state.backend -match "cuda|hip|vulkan") { $isCudaBuild = $true }
            } catch {}
        }
        if ($isCudaBuild) {
            Write-UiWarn (T 'start.cpu_on_gpu_build' $state.backend)
            Write-UiInfo (T 'start.cpu_on_gpu_build_hint')
            if (-not (Confirm-UiYesNo (T 'start.cpu_only_anyway'))) {
                Write-UiInfo (T 'start.hardware_changed')
                $hardware = "both"
            }
        }
    }

    $runArgs = @("-m", "llmbench", "run", "--config", $Config, "--duration", $options.Duration, "--hardware", $hardware)
    if ($options.Stress) {
        $runArgs += "--stress"
    }

    & $VenvPython @runArgs
    if ($LASTEXITCODE -ne 0) { throw (T 'start.benchmark_failed' $LASTEXITCODE) }
}

if (-not $SetupOnly -and -not $ForceUpdateLlamaCpp -and (Test-BenchmarkInstallationReady)) {
    try {
        Invoke-BenchmarkRun
        exit 0
    } catch {
        Write-Host ""
        Write-UiFail $_.Exception.Message
        exit 1
    }
}

Write-UiStep (T 'start.core_needed')

$forward = @{ Config = $Config }
if ($LlamaCppTag) { $forward["LlamaCppTag"] = $LlamaCppTag }
if ($SetupOnly) { $forward["SetupOnly"] = $true }
if ($ForceUpdateLlamaCpp) { $forward["ForceUpdateLlamaCpp"] = $true }

try {
    & $CoreScript @forward
    $rc = $LASTEXITCODE
    if ($rc -ne 0) { throw (T 'start.core_failed' $rc) }
    exit 0
} catch {
    Write-Host ""
    Write-UiFail $_.Exception.Message
    Write-UiInfo (T 'start.llama_dir_hint' $LlamaDir)
    exit 1
}
