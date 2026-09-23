param(
    [Parameter(Mandatory=$true, ValueFromRemainingArguments=$true)]
    [string[]]$Runs
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"

Import-Module (Join-Path $PSScriptRoot "lib\UI.psm1") -Force -DisableNameChecking
Initialize-LlmbenchUI

if (-not (Test-Path $Python)) {
    Write-UiFail (T 'compare.run_setup_first')
    exit 1
}

& $Python -m llmbench compare @Runs --out comparison
Write-UiOk (T 'compare.done' "$Root\comparison\comparison.html")
