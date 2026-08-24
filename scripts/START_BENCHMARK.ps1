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
$PrepareLlamaSource = Join-Path $PSScriptRoot "PREPARE_LLAMA_SOURCE.py"
$DiagnoseLlama = Join-Path $PSScriptRoot "DIAGNOSE_LLAMA_CRASH.ps1"
$CoreScript = Join-Path $PSScriptRoot "START_BENCHMARK_CORE.ps1"
$RuntimeRoot = Join-Path $Root ".runtime"
$LocalPythonDir = Join-Path $RuntimeRoot "python"
$PythonPathFile = Join-Path $RuntimeRoot "python-path.txt"
$BuildToolsVenv = Join-Path $RuntimeRoot "build-tools"
$PreparedRefFile = Join-Path $RuntimeRoot "llama-source-ref.txt"

# llama.cpp besitzt sehr tiefe Source-Pfade. Unter Windows darf der eigentliche
# Source-/Build-Workspace deshalb nicht unter einem langen Downloads-Pfad liegen.
if ($env:LOCALAPPDATA) {
    $ShortWorkRoot = Join-Path $env:LOCALAPPDATA "LLMBench"
} else {
    $ShortWorkRoot = Join-Path ([System.IO.Path]::GetTempPath()) "LLMBench"
}
New-Item -ItemType Directory -Force -Path $ShortWorkRoot | Out-Null
$env:LLMBENCH_WORK_ROOT = $ShortWorkRoot
Write-Host "Kurzer llama.cpp-Arbeitsordner: $ShortWorkRoot"

if (-not (Test-Path $EnsurePython)) {
    throw "Python-Bootstrap fehlt: $EnsurePython"
}
if (-not (Test-Path $EnsureLlama)) {
    throw "llama.cpp-Bootstrap fehlt: $EnsureLlama"
}
if (-not (Test-Path $PrepareLlamaSource)) {
    throw "llama.cpp-Source-Preparer fehlt: $PrepareLlamaSource"
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

Write-Host ""
Write-Host "=== llama.cpp Source vorbereiten ===" -ForegroundColor Cyan
$prepareArgs = @($PrepareLlamaSource, "--project-root", $Root)
if ($LlamaCppTag) {
    $prepareArgs += @("--ref", $LlamaCppTag)
}
if ($ForceUpdateLlamaCpp) {
    $prepareArgs += "--force"
}
& $ResolvedPython @prepareArgs
if ($LASTEXITCODE -ne 0) {
    throw "llama.cpp-Quellcode konnte nicht vorbereitet werden."
}

$PreparedRef = $null
if (Test-Path $PreparedRefFile) {
    $PreparedRef = (Get-Content $PreparedRefFile -Raw).Trim()
}
if (-not $PreparedRef) {
    throw "Source-Preparer war erfolgreich, hat aber keine Source-Ref hinterlegt."
}

$LlamaCppTag = $PreparedRef

if ($ForceUpdateLlamaCpp) {
    Remove-Item (Join-Path $Root "tools\llama.cpp") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $ShortWorkRoot "build") -Recurse -Force -ErrorAction SilentlyContinue
}

$llamaArgs = @{ LlamaCppTag = $LlamaCppTag }

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

& $CoreScript @forward
exit $LASTEXITCODE
