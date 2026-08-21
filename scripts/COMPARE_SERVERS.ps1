param(
    [Parameter(Mandatory=$true, ValueFromRemainingArguments=$true)]
    [string[]]$Runs
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Host "Bitte zuerst START_BENCHMARK.ps1 ausführen."
    exit 1
}

& $Python -m llmbench compare @Runs --out comparison
Write-Host "Vergleich: $Root\comparison\comparison.html"
