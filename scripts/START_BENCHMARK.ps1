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
$LocalPythonDir = Join-Path $Root ".runtime\python"

if (-not (Test-Path $EnsurePython)) {
    throw "Python-Bootstrap fehlt: $EnsurePython"
}
if (-not (Test-Path $CoreScript)) {
    throw "Benchmark-Core fehlt: $CoreScript"
}

& $EnsurePython
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

# Falls Python projektlokal installiert wurde, für den Benchmark-Prozess sichtbar machen.
if (Test-Path (Join-Path $LocalPythonDir "python.exe")) {
    $env:PATH = "$LocalPythonDir;$LocalPythonDir\Scripts;$env:PATH"
}

# Hashtable-Splatting, nicht Array-Splatting: nur so werden die Werte
# garantiert an die Parameternamen gebunden. Mit einem Array konnte
# "-Config" als Wert durchrutschen und der Dateiname im naechsten
# Parameter landen.
$forward = @{ Config = $Config }
if ($LlamaCppTag) { $forward["LlamaCppTag"] = $LlamaCppTag }
if ($SetupOnly) { $forward["SetupOnly"] = $true }
if ($ForceUpdateLlamaCpp) { $forward["ForceUpdateLlamaCpp"] = $true }

& $CoreScript @forward
exit $LASTEXITCODE
