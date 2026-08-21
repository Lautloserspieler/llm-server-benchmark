param(
    [string]$Config = "benchmark.yaml"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".venv")) {
    Write-Host "Virtuelle Python-Umgebung wird erstellt..."
    py -3 -m venv .venv
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install -e .

if (-not (Test-Path $Config)) {
    Copy-Item "benchmark.example.yaml" $Config
    Write-Host ""
    Write-Host "benchmark.yaml wurde aus dem Beispiel erstellt."
    Write-Host "Bitte zuerst Modell- und llama.cpp-Pfade eintragen und das Skript erneut starten."
    exit 0
}

Write-Host ""
Write-Host "=== Vorprüfung ==="
& $Python -m llmbench doctor --config $Config
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Vorprüfung fehlgeschlagen. Bitte Pfade in $Config korrigieren."
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "=== Benchmark ==="
& $Python -m llmbench run --config $Config
