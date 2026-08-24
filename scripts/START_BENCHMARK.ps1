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
$EnsureLlama = Join-Path $PSScriptRoot "ENSURE_LLAMA_CPP.ps1"
$DiagnoseLlama = Join-Path $PSScriptRoot "DIAGNOSE_LLAMA_CRASH.ps1"
$CoreScript = Join-Path $PSScriptRoot "START_BENCHMARK_CORE.ps1"
$RuntimeRoot = Join-Path $Root ".runtime"
$LocalPythonDir = Join-Path $RuntimeRoot "python"
$PythonPathFile = Join-Path $RuntimeRoot "python-path.txt"
$BuildToolsVenv = Join-Path $RuntimeRoot "build-tools"

if (-not (Test-Path $EnsurePython)) {
    throw "Python-Bootstrap fehlt: $EnsurePython"
}
if (-not (Test-Path $EnsureLlama)) {
    throw "llama.cpp-Bootstrap fehlt: $EnsureLlama"
}
if (-not (Test-Path $CoreScript)) {
    throw "Benchmark-Core fehlt: $CoreScript"
}

& $EnsurePython
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$ResolvedPython = $null
if (Test-Path $PythonPathFile) {
    $ResolvedPython = (Get-Content $PythonPathFile -Raw).Trim()
}

if ($ResolvedPython -and (Test-Path $ResolvedPython)) {
    $PythonDir = Split-Path -Parent $ResolvedPython
    $env:PATH = "$PythonDir;$PythonDir\Scripts;$env:PATH"
    Write-Host "Python für Benchmark: $ResolvedPython"
} elseif (Test-Path (Join-Path $LocalPythonDir "python.exe")) {
    $ResolvedPython = Join-Path $LocalPythonDir "python.exe"
    $env:PATH = "$LocalPythonDir;$LocalPythonDir\Scripts;$env:PATH"
} else {
    throw "Python-Bootstrap war erfolgreich, aber es wurde kein nutzbarer Interpreterpfad übergeben."
}

# Source-Build-Toolchain vorab projektlokal bereitstellen.
# CMake 3.31.8 ist nicht als PyPI-Wheel für alle Windows/Python-Kombinationen
# verfügbar. llama.cpp benötigt für Blackwell einen ausreichend neuen CMake;
# daher verwenden wir die verfügbare 3.31.x-Serie ab 3.31.10.
$BuildToolsPython = Join-Path $BuildToolsVenv "Scripts\python.exe"
$BuildToolsCMake = Join-Path $BuildToolsVenv "Scripts\cmake.exe"
$BuildToolsNinja = Join-Path $BuildToolsVenv "Scripts\ninja.exe"

if (-not (Test-Path $BuildToolsPython)) {
    Write-Host ""
    Write-Host "=== Projektlokale Build-Tools ===" -ForegroundColor Cyan
    Write-Host "Erstelle .runtime\build-tools ..."
    & $ResolvedPython -m venv $BuildToolsVenv
    if ($LASTEXITCODE -ne 0) {
        throw "Build-Tool-Venv konnte nicht erstellt werden."
    }
}

if (-not (Test-Path $BuildToolsCMake) -or -not (Test-Path $BuildToolsNinja)) {
    Write-Host ""
    Write-Host "=== Projektlokale Build-Tools ===" -ForegroundColor Cyan
    Write-Host "Installiere CMake >=3.31.10,<4 und Ninja projektlokal..."
    & $BuildToolsPython -m pip install --disable-pip-version-check --upgrade "cmake>=3.31.10,<4" "ninja>=1.11"
    if ($LASTEXITCODE -ne 0) {
        throw "CMake/Ninja konnten nicht installiert werden."
    }
}

if (-not (Test-Path $BuildToolsCMake) -or -not (Test-Path $BuildToolsNinja)) {
    throw "Projektlokale Build-Tools wurden installiert, aber cmake.exe oder ninja.exe fehlen."
}

$BuildToolsBin = Split-Path -Parent $BuildToolsCMake
$env:PATH = "$BuildToolsBin;$env:PATH"
Write-Host "CMake: $((& $BuildToolsCMake --version | Select-Object -First 1))"
Write-Host "Ninja: $(& $BuildToolsNinja --version)"

# CUDA-/llama.cpp-Setup separat vor dem Core ausführen. Bei einem nativen
# Windows-Crash automatisch Eventlog, Exitcode, DLLs und CUDA-Umgebung sammeln.
$llamaArgs = @{}
if ($LlamaCppTag) { $llamaArgs["LlamaCppTag"] = $LlamaCppTag }
if ($ForceUpdateLlamaCpp) { $llamaArgs["ForceUpdateLlamaCpp"] = $true }

try {
    & $EnsureLlama @llamaArgs
    if ($LASTEXITCODE -ne 0) {
        throw "llama.cpp-Setup wurde mit Fehlercode $LASTEXITCODE beendet."
    }
} catch {
    $setupError = $_.Exception.Message
    Write-Host ""
    Write-Host "llama.cpp-Setup fehlgeschlagen: $setupError" -ForegroundColor Red

    if (Test-Path $DiagnoseLlama) {
        try {
            & $DiagnoseLlama
        } catch {
            Write-Warning "Die automatische Crash-Diagnose ist ebenfalls fehlgeschlagen: $($_.Exception.Message)"
        }
    }

    Write-Host ""
    Write-Host "Das Setup wurde beendet. Die Diagnose unter .runtime\diagnostics enthält die Details für die Fehleranalyse." -ForegroundColor Red
    exit 1
}

$forward = @{ Config = $Config }
if ($LlamaCppTag) { $forward["LlamaCppTag"] = $LlamaCppTag }
if ($SetupOnly) { $forward["SetupOnly"] = $true }

# ForceUpdateLlamaCpp wird absichtlich nicht ein zweites Mal an den Core
# weitergereicht: ENSURE_LLAMA_CPP hat bereits einen startbaren Build gewählt.
& $CoreScript @forward
exit $LASTEXITCODE
