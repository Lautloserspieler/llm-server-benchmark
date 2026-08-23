# CmdletBinding schaltet die positionale Parameterbindung ab. Ein falsch
# uebergebenes Argument bricht damit sofort mit klarer Meldung ab, statt
# still im naechsten Parameter zu landen.
[CmdletBinding()]
param(
    [string]$Config = "benchmark.yaml",
    [string]$LlamaCppTag = "",
    [switch]$SetupOnly,
    [switch]$ForceUpdateLlamaCpp
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$ToolsDir = Join-Path $Root "tools"
$LlamaDir = Join-Path $ToolsDir "llama.cpp"
$ModelsDir = Join-Path $Root "models"
$VenvDir = Join-Path $Root ".venv"
$StateFile = Join-Path $LlamaDir ".llama-build.json"
$PinFile = Join-Path $Root "llama-cpp-version.txt"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "=== $Message ===" -ForegroundColor Cyan
}

function Get-PythonCommand {
    $candidates = @(
        @{ Exe = "py"; Args = @("-3.12") },
        @{ Exe = "py"; Args = @("-3") },
        @{ Exe = "python"; Args = @() }
    )
    foreach ($candidate in $candidates) {
        try {
            $cmd = Get-Command $candidate.Exe -ErrorAction Stop
            $pyArgs = @($candidate.Args) + @("-c", "import sys; assert sys.version_info >= (3,10); print(sys.executable)")
            $path = & $cmd.Source @pyArgs 2>$null
            if ($LASTEXITCODE -eq 0 -and $path) {
                return ($path | Select-Object -Last 1).Trim()
            }
        } catch { }
    }
    return $null
}

function Install-Python {
    Write-Step "Python wird installiert"
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        throw "Python 3.10+ fehlt und winget ist nicht verfügbar. Installiere Python 3.12 von python.org und starte erneut."
    }
    & winget.exe install --id Python.Python.3.12 -e --scope user --accept-package-agreements --accept-source-agreements --silent
    if ($LASTEXITCODE -ne 0) {
        throw "Die automatische Python-Installation über winget ist fehlgeschlagen (Exitcode $LASTEXITCODE)."
    }

    $known = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:ProgramFiles\Python312\python.exe"
    )
    foreach ($candidate in $known) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    $python = Get-PythonCommand
    if (-not $python) {
        throw "Python wurde installiert, konnte in dieser Sitzung aber nicht gefunden werden. Starte START_BENCHMARK.bat erneut."
    }
    return $python
}

function ConvertTo-Version([string]$Value) {
    if (-not $Value) { return $null }
    if ($Value -notmatch '\.') { $Value = "$Value.0" }
    try { return [version]$Value } catch { return $null }
}

function Get-NvidiaInfo {
    $nvsmi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if (-not $nvsmi) {
        return $null
    }

    $driver = (& $nvsmi.Source --query-gpu=driver_version --format=csv,noheader 2>$null | Select-Object -First 1)
    if ($driver) { $driver = $driver.ToString().Trim() }

    $cuda = $null
    $source = "nicht ermittelbar"

    # 1. Bevorzugt die Angabe aus dem nvidia-smi-Kopf. Die Schreibweise hat
    #    sich zwischen Treiberversionen geaendert, daher toleranter Ausdruck.
    $text = (& $nvsmi.Source 2>$null | Out-String)
    if ($text -match 'CUDA\s*Version\s*:?\s*([0-9]+(?:\.[0-9]+)?)') {
        $cuda = ConvertTo-Version $Matches[1]
        if ($cuda) { $source = "nvidia-smi" }
    }

    # 2. Sonst aus der Treiberversion ableiten. CUDA 13 kam mit dem Treiberzweig
    #    r580, CUDA 12 mit r525; neuere Treiber unterstuetzen den jeweiligen Stand.
    if (-not $cuda -and $driver -match '^([0-9]+)') {
        $major = [int]$Matches[1]
        if ($major -ge 580) { $cuda = [version]"13.0"; $source = "Treiberversion $driver" }
        elseif ($major -ge 525) { $cuda = [version]"12.0"; $source = "Treiberversion $driver" }
    }

    return @{ Command = $nvsmi.Source; Driver = $driver; Cuda = $cuda; CudaSource = $source }
}

function Invoke-GitHubApi([string]$Url, [switch]$AllowMissing) {
    $headers = @{ "User-Agent" = "llm-server-benchmark-installer"; "Accept" = "application/vnd.github+json" }
    if ($env:GITHUB_TOKEN) { $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN" }
    try {
        return Invoke-RestMethod -Uri $Url -Headers $headers
    } catch {
        $status = $null
        if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
        if ($status -eq 404 -and $AllowMissing) { return $null }
        if ($status -eq 403) {
            throw "GitHub hat die Anfrage abgelehnt (403). Das ist meist das Anfragelimit fuer nicht angemeldete Zugriffe. Entweder spaeter erneut versuchen oder die Umgebungsvariable GITHUB_TOKEN mit einem persoenlichen Zugriffstoken setzen."
        }
        throw "GitHub-Anfrage fehlgeschlagen ($Url): $($_.Exception.Message)"
    }
}

function Assert-LlamaTag([string]$Value, [string]$Origin) {
    # llama.cpp-Tags sehen aus wie "b10456" oder "v0.2.0". Alles andere ist
    # fast sicher ein versehentlich hier gelandeter Wert.
    if ($Value -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$' -or $Value -match '\.(ya?ml|txt|json|exe|bat|ps1)$') {
        throw "'$Value' ist keine gueltige llama.cpp-Release-Kennung (Quelle: $Origin). Erwartet wird ein Tag wie 'b10456'. Die verfuegbaren Tags stehen unter https://github.com/ggml-org/llama.cpp/releases"
    }
    return $Value
}

function Get-PinnedLlamaTag {
    if ($LlamaCppTag) { return Assert-LlamaTag $LlamaCppTag.Trim() "Parameter -LlamaCppTag" }
    if ($env:LLMBENCH_LLAMACPP_TAG) { return Assert-LlamaTag $env:LLMBENCH_LLAMACPP_TAG.Trim() "Umgebungsvariable LLMBENCH_LLAMACPP_TAG" }
    if (Test-Path $PinFile) {
        foreach ($line in (Get-Content $PinFile)) {
            $value = $line.Trim()
            if ($value -and -not $value.StartsWith("#")) {
                return Assert-LlamaTag $value "Datei llama-cpp-version.txt"
            }
        }
    }
    return $null
}

function Test-ReleaseHasAssets($Release, [string]$MainPattern, [string]$RuntimePattern) {
    if (-not $Release -or -not $Release.assets) { return $false }
    $names = @($Release.assets | ForEach-Object { $_.name })
    if (-not ($names | Where-Object { $_ -match $MainPattern })) { return $false }
    if ($RuntimePattern -and -not ($names | Where-Object { $_ -match $RuntimePattern })) { return $false }
    return $true
}

function Resolve-LlamaCppRelease([string]$MainPattern, [string]$RuntimePattern) {
    # Ein fest vorgegebener Tag hat Vorrang. Nur so bekommen alle Server
    # denselben Build - ohne ihn haengt die Version davon ab, wann jemand
    # das Setup gestartet hat.
    $pinned = Get-PinnedLlamaTag
    if ($pinned) {
        Write-Host "Vorgegebener llama.cpp-Build: $pinned"
        $release = Invoke-GitHubApi "https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/$pinned" -AllowMissing
        if (-not $release) {
            throw "Das llama.cpp-Release '$pinned' existiert nicht. Verfuegbare Tags: https://github.com/ggml-org/llama.cpp/releases"
        }
        if (-not (Test-ReleaseHasAssets $release $MainPattern $RuntimePattern)) {
            $names = ($release.assets | ForEach-Object { $_.name }) -join "`n  - "
            throw "Im vorgegebenen Release $pinned gibt es kein passendes Windows-Paket.`nVorhandene Dateien:`n  - $names"
        }
        return $release
    }

    # llama.cpp veroeffentlicht fortlaufende Builds (b10456, b10455, ...).
    # /releases/latest liefert dabei nicht den neuesten Build, sondern das
    # neueste als "stabil" markierte Release - und das kann ein alter Tag
    # ohne jedes Windows-Paket sein. Deshalb wird die Liste durchgegangen
    # und das neueste Release genommen, das die noetigen Dateien enthaelt.
    foreach ($page in 1..3) {
        $releases = Invoke-GitHubApi "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30&page=$page"
        if (-not $releases -or @($releases).Count -eq 0) { break }
        foreach ($release in @($releases)) {
            if ($release.draft) { continue }
            if (Test-ReleaseHasAssets $release $MainPattern $RuntimePattern) { return $release }
        }
    }

    throw "In den letzten 90 llama.cpp-Releases wurde kein Paket gefunden, das zu '$MainPattern' passt. Bitte llama-bench.exe und llama-server.exe von Hand nach tools\llama.cpp kopieren."
}

function Install-LlamaCpp {
    if ((Test-Path (Join-Path $LlamaDir "llama-bench.exe")) -and (Test-Path (Join-Path $LlamaDir "llama-server.exe")) -and -not $ForceUpdateLlamaCpp) {
        Write-Host "llama.cpp ist bereits installiert: $LlamaDir"
        if (Test-Path $StateFile) {
            try {
                $state = Get-Content $StateFile -Raw | ConvertFrom-Json
                Write-Host "Build: $($state.tag) / $($state.backend)"
            } catch { }
        }
        return
    }

    Write-Step "llama.cpp wird automatisch eingerichtet"
    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null

    $nvidia = Get-NvidiaInfo
    $backend = "cpu"
    $mainPattern = '^llama-.*-bin-win-cpu-x64\.zip$'
    $runtimePattern = $null

    if ($nvidia) {
        if ($nvidia.Cuda -and $nvidia.Cuda.Major -ge 13) {
            $backend = "cuda-13.3"
        } else {
            $backend = "cuda-12.4"
        }
        $escaped = [regex]::Escape($backend)
        $mainPattern = "^llama-.*-bin-win-$escaped-x64\.zip$"
        $runtimePattern = "^cudart-llama-bin-win-$escaped-x64\.zip$"
        if ($nvidia.Cuda) {
            Write-Host "NVIDIA erkannt: Treiber $($nvidia.Driver), CUDA-Kompatibilität $($nvidia.Cuda) (ermittelt über $($nvidia.CudaSource))"
        } else {
            Write-Warning "NVIDIA erkannt (Treiber $($nvidia.Driver)), die unterstützte CUDA-Version war nicht ermittelbar. Es wird der konservative Build cuda-12.4 verwendet, der auch auf neueren Treibern läuft."
        }
        Write-Host "Ausgewähltes llama.cpp-Paket: $backend"
    } else {
        Write-Warning "nvidia-smi wurde nicht gefunden. Es wird automatisch der CPU-Build installiert."
    }

    $release = Resolve-LlamaCppRelease $mainPattern $runtimePattern
    Write-Host "Verwendetes llama.cpp-Release: $($release.tag_name)"

    $main = $release.assets | Where-Object { $_.name -match $mainPattern } | Select-Object -First 1
    $runtime = $null
    if ($runtimePattern) {
        $runtime = $release.assets | Where-Object { $_.name -match $runtimePattern } | Select-Object -First 1
    }

    if (-not $main) {
        $names = ($release.assets | ForEach-Object { $_.name }) -join "`n  - "
        throw "Kein passendes llama.cpp-Asset für '$backend' in Release $($release.tag_name) gefunden.`nVerfügbare Assets:`n  - $names"
    }
    if ($runtimePattern -and -not $runtime) {
        throw "CUDA-Runtime-Asset für '$backend' in Release $($release.tag_name) nicht gefunden."
    }

    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("llmbench-llama-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    try {
        $mainZip = Join-Path $tmp $main.name
        Write-Host "Lade $($main.name)..."
        Invoke-WebRequest -Uri $main.browser_download_url -OutFile $mainZip -UseBasicParsing

        if (Test-Path $LlamaDir) {
            Remove-Item -Recurse -Force $LlamaDir
        }
        New-Item -ItemType Directory -Force -Path $LlamaDir | Out-Null
        Expand-Archive -Path $mainZip -DestinationPath $LlamaDir -Force

        if ($runtime) {
            $runtimeZip = Join-Path $tmp $runtime.name
            Write-Host "Lade $($runtime.name)..."
            Invoke-WebRequest -Uri $runtime.browser_download_url -OutFile $runtimeZip -UseBasicParsing
            Expand-Archive -Path $runtimeZip -DestinationPath $LlamaDir -Force
        }

        if (-not (Test-Path (Join-Path $LlamaDir "llama-bench.exe"))) {
            $bench = Get-ChildItem -Path $LlamaDir -Filter "llama-bench.exe" -Recurse -File | Select-Object -First 1
            if ($bench) {
                $sourceDir = $bench.Directory.FullName
                Get-ChildItem -Path $sourceDir -Force | ForEach-Object {
                    Copy-Item $_.FullName -Destination $LlamaDir -Recurse -Force
                }
            }
        }

        if (-not (Test-Path (Join-Path $LlamaDir "llama-bench.exe"))) {
            throw "llama-bench.exe wurde nach dem Entpacken nicht gefunden."
        }
        if (-not (Test-Path (Join-Path $LlamaDir "llama-server.exe"))) {
            throw "llama-server.exe wurde nach dem Entpacken nicht gefunden."
        }

        # Sofort ausprobieren, ob der Build auf diesem Rechner ueberhaupt
        # startet. Ein zum Treiber unpassendes CUDA-Paket faellt sonst erst
        # nach dem Modell-Laden auf, also womoeglich erst Stunden spaeter.
        # Startprobe: laedt der Build auf diesem Rechner seine Backends?
        # Ein zum Treiber unpassendes CUDA-Paket faellt sonst erst beim
        # ersten Benchmark auf, also womoeglich erst Stunden spaeter.
        # --list-devices statt --version: llama-bench kennt kein --version.
        $benchExe = Join-Path $LlamaDir "llama-bench.exe"
        $outFile = [System.IO.Path]::GetTempFileName()
        $errFile = [System.IO.Path]::GetTempFileName()
        $probe = ""
        $probeExit = 1
        try {
            # Start-Process statt 2>&1: PowerShell macht aus stderr sonst
            # NativeCommandError-Objekte, die die Ausgabe unlesbar machen.
            $proc = Start-Process -FilePath $benchExe -ArgumentList "--list-devices" `
                -NoNewWindow -Wait -PassThru `
                -RedirectStandardOutput $outFile -RedirectStandardError $errFile
            $probeExit = $proc.ExitCode
            $probe = ((Get-Content $outFile -Raw -ErrorAction SilentlyContinue) + "`n" +
                      (Get-Content $errFile -Raw -ErrorAction SilentlyContinue)).Trim()
        } catch {
            $probe = $_.Exception.Message
        } finally {
            Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue
        }

        # Erfolg, wenn der Prozess sauber endet oder die Backends erkennbar
        # geladen wurden. Damit bleibt die Probe gueltig, falls llama.cpp
        # das Flag spaeter umbenennt.
        $backendsLoaded = $probe -match 'load_backend|ggml_cuda_init|Device \d+:'
        if ($probeExit -ne 0 -and -not $backendsLoaded) {
            $hint = ""
            if ($probe -match 'invalid parameter|unknown argument') {
                $hint = "`nDer Build kennt die Option --list-devices nicht. Das ist kein Installationsfehler; bitte melden."
            } elseif ($backend -like "cuda-*") {
                $hint = "`nVermutlich passt das Paket '$backend' nicht zum Treiber ($($nvidia.Driver)). Mit -LlamaCppTag einen anderen Build waehlen oder den CPU-Build verwenden."
            }
            throw "llama-bench.exe laesst sich nach der Installation nicht starten (Exitcode $probeExit).$hint`nAusgabe:`n$probe"
        }

        $deviceLine = ($probe -split "`r?`n" | Where-Object { $_ -match 'Device \d+:' } | Select-Object -First 1)
        if (-not $deviceLine) {
            $deviceLine = "Backends geladen, keine GPU gemeldet (CPU-Betrieb)"
        }
        Write-Host "Startprobe erfolgreich: $($deviceLine.Trim())"

        $state = [ordered]@{
            tag = $release.tag_name
            backend = $backend
            installed_at = (Get-Date).ToString("o")
            main_asset = $main.name
            runtime_asset = if ($runtime) { $runtime.name } else { $null }
            nvidia_driver = if ($nvidia) { $nvidia.Driver } else { $null }
            cuda_compatibility = if ($nvidia -and $nvidia.Cuda) { $nvidia.Cuda.ToString() } else { $null }
        }
        $state | ConvertTo-Json | Set-Content -Path $StateFile -Encoding UTF8
        Write-Host "llama.cpp $($release.tag_name) wurde installiert."
        if (-not (Get-PinnedLlamaTag)) {
            Write-Host ""
            Write-Host "Fuer den Serververgleich: alle weiteren Server auf denselben Build festlegen." -ForegroundColor Yellow
            Write-Host "Dazu diese Zeile in llama-cpp-version.txt im Projektordner speichern:" -ForegroundColor Yellow
            Write-Host "  $($release.tag_name)" -ForegroundColor Yellow
        }
    } finally {
        Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    }
}

Write-Step "Systemprüfung"
$PythonExe = Get-PythonCommand
if (-not $PythonExe) {
    $PythonExe = Install-Python
}
Write-Host "Python: $PythonExe"

Write-Step "Python-Umgebung und Pakete"
if (-not (Test-Path $VenvDir)) {
    & $PythonExe -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "Virtuelle Python-Umgebung konnte nicht erstellt werden." }
}
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $VenvPython)) { throw "Python in .venv wurde nicht gefunden." }
& $VenvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "pip konnte nicht aktualisiert werden." }
& $VenvPython -m pip install -e ".[web]"
if ($LASTEXITCODE -ne 0) { throw "Projektabhängigkeiten konnten nicht installiert werden." }

Install-LlamaCpp

Write-Step "Konfiguration und Modellerkennung"
New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null
& $VenvPython -m llmbench bootstrap --config $Config --root $Root --llama-dir $LlamaDir --models-dir $ModelsDir
if ($LASTEXITCODE -ne 0) { throw "benchmark.yaml konnte nicht automatisch konfiguriert werden." }

$Models = Get-ChildItem -Path $ModelsDir -Filter "*.gguf" -Recurse -File -ErrorAction SilentlyContinue
if (-not $Models -or $Models.Count -eq 0) {
    Write-Host ""
    Write-Host "Setup abgeschlossen." -ForegroundColor Green
    Write-Host "Es wurde noch kein GGUF-Modell gefunden."
    Write-Host "Lege eine oder mehrere .gguf-Dateien in folgenden Ordner und starte erneut:"
    Write-Host "  $ModelsDir" -ForegroundColor Yellow
    exit 0
}

Write-Host "Gefundene Modelle: $($Models.Count)"
$Models | ForEach-Object { Write-Host "  - $($_.Name)" }

Write-Step "Vorprüfung"
& $VenvPython -m llmbench doctor --config $Config
if ($LASTEXITCODE -ne 0) {
    throw "Vorprüfung fehlgeschlagen. Siehe Ausgabe oben."
}

if ($SetupOnly) {
    Write-Host ""
    Write-Host "Setup erfolgreich abgeschlossen." -ForegroundColor Green
    exit 0
}

Write-Step "Benchmark"
Write-Host "Wie lange soll der Test laufen?"
Write-Host "  1: kurz (short)   - schnelle Überprüfung"
Write-Host "  2: mittel (medium) - Standardwerte"
Write-Host "  3: lang (long)    - präzise Ergebnisse"
$choice = Read-Host "Auswahl [1-3, Standard=2]"

$duration = "medium"
if ($choice -eq "1") { $duration = "short" }
elseif ($choice -eq "3") { $duration = "long" }

Write-Host "Verwende Dauer: $duration"
& $VenvPython -m llmbench run --config $Config --duration $duration
if ($LASTEXITCODE -ne 0) {
    throw "Benchmark fehlgeschlagen (Exitcode $LASTEXITCODE)."
}
