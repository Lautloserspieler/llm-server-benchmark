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

if (-not (Test-Path $EnsurePython)) {
    throw "Python-Bootstrap fehlt: $EnsurePython"
}
if (-not (Test-Path $CoreScript)) {
    throw "Benchmark-Core fehlt: $CoreScript"
}

# Python zuerst sicherstellen. ENSURE_PYTHON.ps1 kann Python projektlokal
# bereitstellen, wenn auf dem Rechner kein nutzbarer Interpreter gefunden wird.
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
    Write-Host "Python fuer Benchmark: $ResolvedPython"
} elseif (Test-Path (Join-Path $LocalPythonDir "python.exe")) {
    $ResolvedPython = Join-Path $LocalPythonDir "python.exe"
    $env:PATH = "$LocalPythonDir;$LocalPythonDir\Scripts;$env:PATH"
    Write-Host "Python fuer Benchmark: $ResolvedPython"
} else {
    throw "Python-Bootstrap war erfolgreich, aber es wurde kein nutzbarer Interpreterpfad uebergeben."
}

# WICHTIG:
# Der normale Windows-Startpfad baut llama.cpp NICHT mehr aus dem Quellcode.
# START_BENCHMARK_CORE.ps1 ermittelt den passenden offiziellen Windows-x64
# Release-Build (CUDA bei NVIDIA, sonst CPU), laedt die ZIP-Dateien direkt von
# GitHub herunter, entpackt sie nach tools\llama.cpp und prueft anschliessend
# llama-bench.exe/llama-server.exe mit --list-devices.
#
# Der alte Source-Build bleibt nur als separates Diagnose-/Fallback-Werkzeug im
# Repository erhalten und wird durch START_BENCHMARK.bat nicht mehr aufgerufen.

$forward = @{ Config = $Config }
if ($LlamaCppTag) { $forward["LlamaCppTag"] = $LlamaCppTag }
if ($SetupOnly) { $forward["SetupOnly"] = $true }
if ($ForceUpdateLlamaCpp) { $forward["ForceUpdateLlamaCpp"] = $true }

try {
    & $CoreScript @forward
    $rc = $LASTEXITCODE
    if ($rc -ne 0) {
        throw "Benchmark-Core wurde mit Fehlercode $rc beendet."
    }
    exit 0
} catch {
    Write-Host ""
    Write-Host "Setup/Benchmark fehlgeschlagen: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    Write-Host "Erwarteter llama.cpp-Zielordner:" -ForegroundColor Yellow
    Write-Host (Join-Path $Root "tools\llama.cpp")
    Write-Host "Dort muessen nach dem Download llama-bench.exe und llama-server.exe liegen."
    exit 1
}
