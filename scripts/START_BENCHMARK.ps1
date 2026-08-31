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

function Test-BenchmarkInstallationReady {
    if (-not (Test-Path $VenvPython -PathType Leaf)) { return $false }
    if (-not (Test-Path $ConfigPath -PathType Leaf)) { return $false }
    if (-not (Test-Path $LlamaBench -PathType Leaf)) { return $false }
    if (-not (Test-Path $LlamaServer -PathType Leaf)) { return $false }
    if (-not (Test-Path $LlamaState -PathType Leaf)) { return $false }

    try {
        & $VenvPython -c "import llmbench, yaml, pydantic, psutil" *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Invoke-BenchmarkRun {
    Write-Host ""
    Write-Host "=== Vorhandene Installation erkannt ===" -ForegroundColor Green
    Write-Host "Setup wird uebersprungen. Starte direkt mit Modellerkennung und Vorpruefung."

    # Bootstrap ist absichtlich leichtgewichtig und bleibt bei jedem Start aktiv:
    # neue GGUF-Dateien unter models\ werden dadurch automatisch in eine bestehende
    # benchmark.yaml aufgenommen, ohne Python/llama.cpp erneut einzurichten.
    New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null
    & $VenvPython -m llmbench bootstrap --config $Config --root $Root --llama-dir $LlamaDir --models-dir $ModelsDir
    if ($LASTEXITCODE -ne 0) {
        throw "benchmark.yaml konnte nicht aktualisiert werden."
    }

    # Nicht nur models\ pruefen: benchmark.yaml darf bewusst auch GGUF-Dateien
    # ausserhalb des Projektordners referenzieren. Der alte Launcher brach in
    # diesem Fall faelschlich mit 'Setup abgeschlossen' ab.
    $doctorJsonText = (& $VenvPython -m llmbench doctor --config $Config --json | Out-String).Trim()
    if (-not $doctorJsonText) {
        throw "Vorpruefung lieferte keine auswertbaren Daten."
    }
    try {
        $doctorData = $doctorJsonText | ConvertFrom-Json
    } catch {
        throw "Vorpruefung konnte nicht ausgewertet werden: $($_.Exception.Message)"
    }

    $configuredModels = @($doctorData.models)
    if ($configuredModels.Count -eq 0) {
        Write-Host ""
        Write-Host "Kein Modell konfiguriert." -ForegroundColor Yellow
        Write-Host "Lege eine .gguf-Datei unter folgendem Ordner ab oder trage einen externen Pfad in benchmark.yaml ein:"
        Write-Host "  $ModelsDir" -ForegroundColor Yellow
        exit 0
    }

    Write-Host "Gefundene/konfigurierte Modelle: $($configuredModels.Count)"
    foreach ($model in $configuredModels) {
        $status = if ($model.exists) { "OK" } else { "FEHLT" }
        Write-Host "  [$status] $($model.name): $($model.path)"
    }

    Write-Host ""
    Write-Host "=== Vorpruefung ===" -ForegroundColor Cyan
    & $VenvPython -m llmbench doctor --config $Config
    if ($LASTEXITCODE -ne 0) {
        throw "Vorpruefung fehlgeschlagen. Siehe Ausgabe oben."
    }

    Write-Host ""
    Write-Host "=== Benchmark ===" -ForegroundColor Cyan
    Write-Host "Wie lange soll der Test laufen?"
    Write-Host "  1: kurz (short)    - schnelle Ueberpruefung"
    Write-Host "  2: mittel (medium) - Standardwerte"
    Write-Host "  3: lang (long)     - praezise Ergebnisse"
    $choice = Read-Host "Auswahl [1-3, Standard=2]"

    $duration = "medium"
    if ($choice -eq "1") { $duration = "short" }
    elseif ($choice -eq "3") { $duration = "long" }
    Write-Host "Verwende Dauer: $duration"

    Write-Host ""
    Write-Host "Womit soll getestet werden?"
    Write-Host "  1: Nur CPU"
    Write-Host "  2: Nur GPU"
    Write-Host "  3: CPU und GPU gleichzeitig (Standard, inkl. Dauerlast-Test)"
    $hwChoice = Read-Host "Auswahl [1-3, Standard=3]"

    $hardware = "both"
    if ($hwChoice -eq "1") { $hardware = "cpu" }
    elseif ($hwChoice -eq "2") { $hardware = "gpu" }
    Write-Host "Verwende Hardware-Auswahl: $hardware"

    & $VenvPython -m llmbench run --config $Config --duration $duration --hardware $hardware
    if ($LASTEXITCODE -ne 0) {
        throw "Benchmark fehlgeschlagen (Exitcode $LASTEXITCODE)."
    }
}

# Normaler Start: Wenn die Installation bereits vollstaendig vorhanden ist,
# darf der Launcher NICHT wieder in den Setup-Core springen.
# -SetupOnly und -ForceUpdateLlamaCpp erzwingen weiterhin bewusst den Core-Pfad.
if (-not $SetupOnly -and -not $ForceUpdateLlamaCpp -and (Test-BenchmarkInstallationReady)) {
    try {
        Invoke-BenchmarkRun
        exit 0
    } catch {
        Write-Host ""
        Write-Host "Benchmark fehlgeschlagen: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "Installation ist noch nicht vollstaendig oder ein Setup wurde explizit angefordert."
Write-Host "Starte einmalig den Setup-Core..." -ForegroundColor Yellow

# Der Setup-Core installiert nur dann Komponenten, wenn sie fehlen oder explizit
# aktualisiert werden sollen. Nach erfolgreichem Setup nimmt der naechste normale
# Start automatisch den Fast-Start oben.
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
    Write-Host $LlamaDir
    Write-Host "Dort muessen llama-bench.exe und llama-server.exe liegen."
    exit 1
}
