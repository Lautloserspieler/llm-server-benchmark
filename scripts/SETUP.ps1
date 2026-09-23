# Einrichtung unter Windows (aufgerufen von setup.bat).
#
# Reihenfolge: Sprache waehlen -> Docker Desktop + WSL2 + CUDA (Modus auto/docker)
# -> sonst nativer Fallback mit Python, .venv, Modellauswahl und Setup-Wizard.
# LLMBENCH_EXECUTION_MODE = auto (Standard) | docker | native

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Import-Module (Join-Path $PSScriptRoot 'lib\UI.psm1') -Force -DisableNameChecking
Initialize-LlmbenchUI
Select-LlmbenchLanguage | Out-Null

$RebootExitCode = 3010
$PowerShellExe = (Get-Process -Id $PID).Path
$PythonPathFile = Join-Path $Root '.runtime\python-path.txt'

function Invoke-ChildScript([string]$Name, [string[]]$Arguments = @()) {
    # Eigener Prozess wie frueher aus setup.bat: jedes Skript behaelt seinen
    # Exitcode und seine eigene Fehlerbehandlung. Die Ausgabe wird bewusst
    # nicht abgefangen (kein `$x = ...`), sonst verliert das Kindskript die
    # Konsole samt Farben und Rueckfragen - der Exitcode kommt deshalb ueber
    # $script:ChildExitCode zurueck.
    & $PowerShellExe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot $Name) @Arguments
    $script:ChildExitCode = $LASTEXITCODE
}

function Invoke-Checked([string]$Exe, [string[]]$Arguments, [string]$ErrorKey) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw (T $ErrorKey $LASTEXITCODE) }
}

function Write-RebootNotice {
    Write-UiDone (T 'setup.reboot_title') @((T 'setup.reboot_hint'))
}

$mode = if ($env:LLMBENCH_EXECUTION_MODE) { $env:LLMBENCH_EXECUTION_MODE.ToLowerInvariant() } else { 'auto' }
if (@('auto', 'docker', 'native') -notcontains $mode) {
    Write-UiFail (T 'setup.invalid_mode')
    exit 1
}

Write-UiHeader (T 'setup.title') (T 'setup.mode' $mode)

try {
    if ($mode -ne 'native') {
        Write-UiSection 'Docker Desktop + WSL2 + NVIDIA CUDA'
        Invoke-ChildScript 'DOCKER_BENCHMARK.ps1' @('-Action', 'Setup')
        $rc = $script:ChildExitCode
        if ($rc -eq 0) {
            Write-UiDone (T 'setup.done_docker') @((T 'setup.done_hint'))
            exit 0
        }
        if ($rc -eq $RebootExitCode) {
            Write-RebootNotice
            exit $RebootExitCode
        }
        if ($mode -eq 'docker') { throw (T 'setup.docker_forced_failed') }
        Write-UiWarn (T 'setup.docker_fallback')
    }

    Write-UiSection 'Python'
    Invoke-ChildScript 'ENSURE_PYTHON.ps1'
    if ($script:ChildExitCode -ne 0) { throw (T 'setup.python_missing') }
    $python = if (Test-Path $PythonPathFile) { (Get-Content $PythonPathFile -Raw).Trim() } else { '' }
    if (-not $python) { throw (T 'setup.python_missing') }

    Write-UiSection (T 'setup.section_packages')
    if (-not (Test-Path (Join-Path $Root '.venv'))) {
        Write-UiStep (T 'setup.venv_create')
        Invoke-Checked $python @('-m', 'venv', '.venv') 'setup.step_failed'
    }
    $venvPython = Join-Path $Root '.venv\Scripts\python.exe'
    Write-UiStep (T 'setup.pip_install')
    Invoke-Checked $venvPython @('-m', 'pip', 'install', '--quiet', '--upgrade', 'pip') 'setup.step_failed'
    Invoke-Checked $venvPython @('-m', 'pip', 'install', '--quiet', '-e', '.') 'setup.step_failed'
    Write-UiOk (T 'setup.packages_ready')
    New-Item -ItemType Directory -Force -Path (Join-Path $Root 'models') | Out-Null

    Write-UiSection (T 'setup.section_models')
    Invoke-Checked $venvPython @('-m', 'llmbench.model_select', '--models-dir', 'models', '--select') 'setup.step_failed'

    # Der Setup-Wizard darf nur die gespeicherte Auswahl pruefen und niemals
    # stillschweigend die komplette Standard-Suite nachladen.
    $env:LLMBENCH_USE_SAVED_SELECTION = '1'

    Write-UiSection (T 'setup.section_config')
    Invoke-Checked $venvPython @('-m', 'llmbench', 'setup') 'setup.step_failed'

    Write-UiDone (T 'setup.done_native') @((T 'setup.done_hint'))
    exit 0
} catch {
    Write-Host ''
    Write-UiFail $_.Exception.Message
    Write-UiInfo (T 'setup.failed')
    exit 1
}
