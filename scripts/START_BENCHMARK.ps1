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

if (-not (Test-Path $EnsurePython)) { throw "Python-Bootstrap fehlt: $EnsurePython" }
if (-not (Test-Path $CoreScript)) { throw "Benchmark-Core fehlt: $CoreScript" }

# --- Automatisches Update via git pull (falls git vorhanden und .git-Verzeichnis existiert) ---
$GitDir = Join-Path $Root ".git"
if ((Test-Path $GitDir) -and (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Pruefe auf Updates..." -ForegroundColor Cyan
    try {
        $fetchResult = & git -C $Root fetch --quiet 2>&1
        $status = & git -C $Root status -uno --short 2>&1
        if ($status -match "behind") {
            Write-Host "Neues Update verfuegbar - aktualisiere..." -ForegroundColor Yellow
            & git -C $Root pull --ff-only --quiet 2>&1 | Out-Null
            Write-Host "Update abgeschlossen." -ForegroundColor Green
        }
    } catch {
        Write-Host "Git-Update uebersprungen: $($_.Exception.Message)" -ForegroundColor DarkGray
    }
} elseif (-not (Test-Path $GitDir)) {
    Write-Host "" -ForegroundColor Yellow
    Write-Host "HINWEIS: Das Projekt wurde als ZIP heruntergeladen, nicht per git clone." -ForegroundColor Yellow
    Write-Host "         Automatische Updates sind dadurch nicht moeglich." -ForegroundColor Yellow
    Write-Host "         Bitte klone das Repository stattdessen mit:" -ForegroundColor Yellow
    Write-Host "         git clone https://github.com/Lautloserspieler/llm-server-benchmark.git" -ForegroundColor Cyan
    Write-Host ""
}

& $EnsurePython
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

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
        & $VenvPython -c "import llmbench, yaml, pydantic, psutil, rich, huggingface_hub" *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Get-DoctorData {
    $doctorJsonText = (& $VenvPython -m llmbench doctor --config $Config --json | Out-String).Trim()
    if (-not $doctorJsonText) { throw "Vorpruefung lieferte keine auswertbaren Daten." }
    try {
        return ($doctorJsonText | ConvertFrom-Json)
    } catch {
        throw "Vorpruefung konnte nicht ausgewertet werden: $($_.Exception.Message)"
    }
}

function Ensure-V2ModelSuite {
    New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null

    & $VenvPython -m llmbench download --suite all --models-dir $ModelsDir --verify-only *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "V2-Standard-Suite: vollstaendig vorhanden." -ForegroundColor Green
        return
    }

    Write-Host ""
    Write-Host "=== V2 Standard-Suite unvollstaendig - Auto-Download ===" -ForegroundColor Cyan
    Write-Host "Fehlende Modelle oder GGUF-Shards werden automatisch von HuggingFace geladen."
    Write-Host "Vorhandene Dateien und HuggingFace-Cache werden wiederverwendet."
    & $VenvPython -m llmbench download --suite all --models-dir $ModelsDir
    if ($LASTEXITCODE -ne 0) {
        throw "Automatischer Modell-Download ist fehlgeschlagen (Exitcode $LASTEXITCODE)."
    }

    & $VenvPython -m llmbench download --suite all --models-dir $ModelsDir --verify-only
    if ($LASTEXITCODE -ne 0) {
        throw "Die V2-Standard-Suite ist nach dem Download weiterhin unvollstaendig."
    }
}

function Invoke-BenchmarkRun {
    Write-Host ""
    Write-Host "=== Vorhandene Installation erkannt ===" -ForegroundColor Green
    Write-Host "Setup wird uebersprungen. Pruefe Modelle und starte den Benchmark."

    Ensure-V2ModelSuite

    # Bootstrap entfernt auch alte, versehentlich eingetragene Folge-Shards und
    # bindet gesplittete GGUFs nur ueber 00001-of-XXXXX ein.
    & $VenvPython -m llmbench bootstrap --config $Config --root $Root --llama-dir $LlamaDir --models-dir $ModelsDir
    if ($LASTEXITCODE -ne 0) { throw "benchmark.yaml konnte nicht aktualisiert werden." }

    $doctorData = Get-DoctorData
    $configuredModels = @($doctorData.models)
    if ($configuredModels.Count -eq 0) {
        throw "Trotz vollstaendiger Standard-Suite wurde kein GGUF-Modell konfiguriert."
    }

    Write-Host "Gefundene/konfigurierte Modelle: $($configuredModels.Count)"
    foreach ($model in $configuredModels) {
        $status = if ($model.exists) { "OK" } else { "FEHLT" }
        Write-Host "  [$status] $($model.name): $($model.path)"
    }

    Write-Host ""
    Write-Host "=== Vorpruefung ===" -ForegroundColor Cyan
    & $VenvPython -m llmbench doctor --config $Config
    if ($LASTEXITCODE -ne 0) { throw "Vorpruefung fehlgeschlagen. Siehe Ausgabe oben." }

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
    Write-Host "  3: CPU und GPU (Standard, inkl. Dauerlast-Test)"
    $hwChoice = Read-Host "Auswahl [1-3, Standard=3]"

    $hardware = "both"
    if ($hwChoice -eq "1") {
        $hardware = "cpu"
        # Pruefen ob ein GPU-Backend installiert ist – CUDA-Builds schlagen bei reinen CPU-Tests fehl
        $backendFile = Join-Path $PSScriptRoot "..\llama_cpp_state.json"
        $isCudaBuild = $false
        if (Test-Path $backendFile) {
            try {
                $state = Get-Content $backendFile -Raw | ConvertFrom-Json
                if ($state.backend -match "cuda|hip|vulkan") { $isCudaBuild = $true }
            } catch {}
        }
        if ($isCudaBuild) {
            Write-Host ""
            Write-Host "HINWEIS: Das installierte llama.cpp ist ein GPU-Build ($($state.backend))." -ForegroundColor Yellow
            Write-Host "         Reine CPU-Tests schlagen bei diesem Build haeufig mit Fehlercode 1 fehl." -ForegroundColor Yellow
            Write-Host "         Empfehlung: Waehle stattdessen Option 3 (CPU+GPU) oder Option 2 (Nur GPU)." -ForegroundColor Yellow
            Write-Host ""
            $confirm = Read-Host "Trotzdem nur CPU testen? [j/N]"
            if ($confirm -notmatch "^[jJyY]") {
                Write-Host "Aenderung auf 'both' (CPU + GPU)."
                $hardware = "both"
            }
        }
    }
    elseif ($hwChoice -eq "2") { $hardware = "gpu" }
    Write-Host "Verwende Hardware-Auswahl: $hardware"

    Write-Host ""
    $stressChoice = Read-Host "Zusaetzliche V2-Stresstests (TTFT/Multi-Tenant/OOM/Quant) starten? [j/N]"
    $runArgs = @("-m", "llmbench", "run", "--config", $Config, "--duration", $duration, "--hardware", $hardware)
    if ($stressChoice -match "^[jJyY]") {
        $runArgs += "--stress"
    }

    & $VenvPython @runArgs
    if ($LASTEXITCODE -ne 0) { throw "Benchmark fehlgeschlagen (Exitcode $LASTEXITCODE)." }
}

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

$forward = @{ Config = $Config }
if ($LlamaCppTag) { $forward["LlamaCppTag"] = $LlamaCppTag }
if ($SetupOnly) { $forward["SetupOnly"] = $true }
if ($ForceUpdateLlamaCpp) { $forward["ForceUpdateLlamaCpp"] = $true }

try {
    & $CoreScript @forward
    $rc = $LASTEXITCODE
    if ($rc -ne 0) { throw "Benchmark-Core wurde mit Fehlercode $rc beendet." }
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
