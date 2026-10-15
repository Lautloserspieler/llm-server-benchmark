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

function Invoke-CheckedQuiet([string]$Exe, [string[]]$Arguments, [string]$ErrorKey) {
    & $Exe @Arguments *> $null
    if ($LASTEXITCODE -ne 0) { throw (T $ErrorKey $LASTEXITCODE) }
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
        $dockerAction = if ($mode -eq 'docker') { 'Setup' } else { 'Host' }
        Invoke-ChildScript 'DOCKER_BENCHMARK.ps1' @('-Action', $dockerAction)
        $rc = $script:ChildExitCode
        if ($rc -eq 0) {
            if ($mode -eq 'docker') {
                Invoke-ChildScript 'DOCKER_BENCHMARK.ps1' @('-Action', 'Configure')
                if ($script:ChildExitCode -ne 0) { throw (T 'setup.step_failed' $script:ChildExitCode) }
                Write-UiDone (T 'setup.done_docker') @((T 'setup.done_hint'))
                exit 0
            }
            Write-UiOk (T 'setup.docker_host_ready')
        } elseif ($rc -eq $RebootExitCode) {
            Invoke-RebootFlow 'setup.bat'
            exit $RebootExitCode
        } else {
            if ($mode -eq 'docker') { throw (T 'setup.docker_forced_failed') }
            Write-UiWarn (T 'setup.docker_fallback')
        }
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

    # Zuerst eine minimale Konfiguration erzeugen, damit die Backend-Auswahl
    # direkt in benchmark.yaml gespeichert werden kann.
    Invoke-CheckedQuiet $venvPython @('-m', 'llmbench', 'bootstrap', '--config', 'benchmark.yaml', '--root', $Root, '--llama-dir', 'tools/llama.cpp', '--models-dir', 'models') 'setup.step_failed'

    Write-UiSection (T 'start.backend_title')
    Invoke-Checked $venvPython @('-m', 'llmbench', 'select-backend', '--root', $Root, '--config', 'benchmark.yaml') 'setup.step_failed'

    Write-UiSection (T 'setup.section_models')
    Invoke-Checked $venvPython @('-m', 'llmbench', 'select-models', '--config', 'benchmark.yaml', '--models-dir', 'models') 'setup.step_failed'

    # Nur llama.cpp benoetigt lokale Windows-Binaries. Kein zweiter Setup-Wizard:
    # Backend- und Modellauswahl wurden bereits oben abgeschlossen.
    $selectedBackend = (& $venvPython -c "import yaml; c=yaml.safe_load(open('benchmark.yaml',encoding='utf-8')) or {}; print((c.get('tools') or {}).get('backend','llama_cpp'))").Trim()
    if ($selectedBackend -eq 'llama_cpp') {
        Invoke-ChildScript 'START_BENCHMARK_CORE.ps1' @('-LlamaCppOnly')
        if ($script:ChildExitCode -ne 0) { throw (T 'setup.step_failed' $script:ChildExitCode) }
    }

    $doneKey = if ($mode -eq 'auto') { 'setup.done_host' } else { 'setup.done_native' }
    Write-UiDone (T $doneKey) @((T 'setup.done_hint'))
    exit 0
} catch {
    Write-Host ''
    Write-UiFail $_.Exception.Message
    Write-UiInfo (T 'setup.failed')
    exit 1
}
