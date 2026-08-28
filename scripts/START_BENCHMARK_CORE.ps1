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

function ConvertTo-Version([string]$Value) {
    if (-not $Value) { return $null }
    if ($Value -notmatch '\.') { $Value = "$Value.0" }
    try { return [version]$Value } catch { return $null }
}

function Get-NvidiaInfo {
    $nvsmi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if (-not $nvsmi) { return $null }

    $driver = (& $nvsmi.Source --query-gpu=driver_version --format=csv,noheader 2>$null | Select-Object -First 1)
    if ($driver) { $driver = $driver.ToString().Trim() }

    $reportedCuda = $null
    $source = "nicht ermittelbar"
    $text = (& $nvsmi.Source 2>$null | Out-String)
    if ($text -match 'CUDA\s*Version\s*:?\s*([0-9]+(?:\.[0-9]+)?)') {
        $reportedCuda = ConvertTo-Version $Matches[1]
        if ($reportedCuda) { $source = "nvidia-smi" }
    }

    $driverMajor = $null
    $supportedCudaMajor = $null
    if ($driver -match '^([0-9]+)') {
        $driverMajor = [int]$Matches[1]
        # NVIDIA minor-version compatibility:
        # CUDA 13.x => driver >= 580
        # CUDA 12.x => driver >= 525
        # CUDA 11.x => driver >= 450
        if ($driverMajor -ge 580) { $supportedCudaMajor = 13 }
        elseif ($driverMajor -ge 525) { $supportedCudaMajor = 12 }
        elseif ($driverMajor -ge 450) { $supportedCudaMajor = 11 }
    }

    if (-not $reportedCuda -and $supportedCudaMajor) {
        $reportedCuda = [version]("$supportedCudaMajor.0")
        $source = "Treiberversion $driver"
    }

    return @{
        Command = $nvsmi.Source
        Driver = $driver
        DriverMajor = $driverMajor
        Cuda = $reportedCuda
        CudaSource = $source
        SupportedCudaMajor = $supportedCudaMajor
    }
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
            throw "GitHub hat die Anfrage abgelehnt (403). Meist ist das API-Limit erreicht. Spaeter erneut versuchen oder GITHUB_TOKEN setzen."
        }
        throw "GitHub-Anfrage fehlgeschlagen ($Url): $($_.Exception.Message)"
    }
}

function Assert-LlamaTag([string]$Value, [string]$Origin) {
    if ($Value -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$' -or $Value -match '\.(ya?ml|txt|json|exe|bat|ps1)$') {
        throw "'$Value' ist keine gueltige llama.cpp-Release-Kennung (Quelle: $Origin). Erwartet wird z.B. b10604."
    }
    return $Value
}

function Get-PinnedLlamaTag {
    if ($LlamaCppTag) { return Assert-LlamaTag $LlamaCppTag.Trim() "Parameter -LlamaCppTag" }
    if ($env:LLMBENCH_LLAMACPP_TAG) { return Assert-LlamaTag $env:LLMBENCH_LLAMACPP_TAG.Trim() "LLMBENCH_LLAMACPP_TAG" }
    if (Test-Path $PinFile) {
        foreach ($line in (Get-Content $PinFile)) {
            $value = $line.Trim()
            if ($value -and -not $value.StartsWith("#")) {
                return Assert-LlamaTag $value "llama-cpp-version.txt"
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

function Get-AvailableCudaBackends($Release) {
    if (-not $Release -or -not $Release.assets) { return @() }

    $mainVersions = @{}
    $runtimeVersions = @{}
    foreach ($asset in @($Release.assets)) {
        $name = [string]$asset.name
        if ($name -match '^llama-.*-bin-win-cuda-([0-9]+(?:\.[0-9]+)*)-x64\.zip$') {
            $mainVersions[$Matches[1]] = $true
        } elseif ($name -match '^cudart-llama-bin-win-cuda-([0-9]+(?:\.[0-9]+)*)-x64\.zip$') {
            $runtimeVersions[$Matches[1]] = $true
        }
    }

    $result = foreach ($versionText in $mainVersions.Keys) {
        if (-not $runtimeVersions.ContainsKey($versionText)) { continue }
        $parsed = ConvertTo-Version $versionText
        if (-not $parsed) { continue }
        [pscustomobject]@{
            Version = $parsed
            VersionText = $versionText
            Backend = "cuda-$versionText"
        }
    }
    return @($result | Sort-Object Version -Descending)
}

function Select-CompatibleCudaBackend($Release, $Nvidia) {
    $available = @(Get-AvailableCudaBackends $Release)
    if ($available.Count -eq 0) { return $null }

    # Wichtig: nvidia-smi kann z.B. "CUDA 13.0" anzeigen, obwohl ein
    # CUDA-13.3-Runtime-Build auf demselben Treiber lauffaehig ist.
    # CUDA minor-version compatibility gilt innerhalb der Major-Familie.
    # Daher NICHT 13.3 <= 13.0 vergleichen, sondern nach Major-Familie waehlen.
    $targetMajor = $null
    if ($Nvidia -and $Nvidia.SupportedCudaMajor) {
        $targetMajor = [int]$Nvidia.SupportedCudaMajor
    } elseif ($Nvidia -and $Nvidia.Cuda) {
        $targetMajor = [int]$Nvidia.Cuda.Major
    }

    if ($targetMajor) {
        $sameMajor = @($available | Where-Object { $_.Version.Major -eq $targetMajor })
        if ($sameMajor.Count -gt 0) {
            return ($sameMajor | Sort-Object Version -Descending | Select-Object -First 1)
        }

        # Falls llama.cpp fuer diese Major-Familie gerade kein Paket anbietet,
        # ist ein aelterer CUDA-Major-Build auf neueren Treibern zulaessig.
        $older = @($available | Where-Object { $_.Version.Major -lt $targetMajor })
        if ($older.Count -gt 0) {
            return ($older | Sort-Object Version -Descending | Select-Object -First 1)
        }
        return $null
    }

    # CUDA-Familie unbekannt: konservativ den aeltesten Build nehmen.
    return ($available | Sort-Object Version | Select-Object -First 1)
}

function Get-ReleaseCandidates {
    $pinned = Get-PinnedLlamaTag
    if ($pinned) {
        Write-Host "Vorgegebener llama.cpp-Build: $pinned"
        $release = Invoke-GitHubApi "https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/$pinned" -AllowMissing
        if (-not $release) { throw "Das llama.cpp-Release '$pinned' existiert nicht." }
        return @($release)
    }

    $all = @()
    foreach ($page in 1..3) {
        $releases = Invoke-GitHubApi "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30&page=$page"
        if (-not $releases -or @($releases).Count -eq 0) { break }
        $all += @($releases | Where-Object { -not $_.draft })
    }
    return @($all)
}

function Resolve-LlamaCppPackage($Nvidia) {
    $releases = @(Get-ReleaseCandidates)
    if ($releases.Count -eq 0) { throw "Keine llama.cpp-Releases konnten von GitHub geladen werden." }

    foreach ($release in $releases) {
        if ($Nvidia) {
            $cuda = Select-CompatibleCudaBackend $release $Nvidia
            if ($cuda) {
                $escaped = [regex]::Escape($cuda.Backend)
                $mainPattern = "^llama-.*-bin-win-$escaped-x64\.zip$"
                $runtimePattern = "^cudart-llama-bin-win-$escaped-x64\.zip$"
                if (Test-ReleaseHasAssets $release $mainPattern $runtimePattern) {
                    return [pscustomobject]@{
                        Release = $release
                        Backend = $cuda.Backend
                        MainPattern = $mainPattern
                        RuntimePattern = $runtimePattern
                    }
                }
            }
        }

        $cpuPattern = '^llama-.*-bin-win-cpu-x64\.zip$'
        if (Test-ReleaseHasAssets $release $cpuPattern $null) {
            return [pscustomobject]@{
                Release = $release
                Backend = "cpu"
                MainPattern = $cpuPattern
                RuntimePattern = $null
            }
        }
    }

    throw "Kein passendes Windows-x64 llama.cpp-Paket gefunden."
}

function Invoke-LlamaBenchProbe([string]$BenchExe) {
    if (-not (Test-Path $BenchExe)) {
        return [pscustomobject]@{ Success = $false; ExitCode = $null; Output = "llama-bench.exe fehlt"; DeviceLine = $null }
    }

    $outFile = [System.IO.Path]::GetTempFileName()
    $errFile = [System.IO.Path]::GetTempFileName()
    $probe = ""
    $probeExit = 1
    try {
        $proc = Start-Process -FilePath $BenchExe -ArgumentList "--list-devices" `
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

    $backendsLoaded = $probe -match 'load_backend|ggml_cuda_init|Device \d+:'
    $success = ($probeExit -eq 0 -or $backendsLoaded)
    $deviceLine = ($probe -split "`r?`n" | Where-Object { $_ -match 'Device \d+:' } | Select-Object -First 1)
    return [pscustomobject]@{
        Success = $success
        ExitCode = $probeExit
        Output = $probe
        DeviceLine = $deviceLine
    }
}

function Test-ExistingLlamaInstall($Nvidia) {
    $benchExe = Join-Path $LlamaDir "llama-bench.exe"
    $serverExe = Join-Path $LlamaDir "llama-server.exe"
    if (-not (Test-Path $benchExe) -or -not (Test-Path $serverExe) -or -not (Test-Path $StateFile)) {
        return $false
    }

    try { $state = Get-Content $StateFile -Raw | ConvertFrom-Json } catch { return $false }

    # Wenn ein moderner CUDA-13-faehiger Treiber vorhanden ist, einen alten
    # cuda-12-Build nicht dauerhaft festhalten. Neu installieren und CUDA 13 nutzen.
    if ($Nvidia -and $Nvidia.SupportedCudaMajor -ge 13 -and $state.backend -like "cuda-12*") {
        Write-Host "Vorhandener Build $($state.backend) wird durch CUDA-13-Build ersetzt."
        return $false
    }

    $probe = Invoke-LlamaBenchProbe $benchExe
    if (-not $probe.Success) {
        Write-Warning "Vorhandene llama.cpp-Installation ist nicht startbar und wird automatisch neu installiert (Exitcode $($probe.ExitCode))."
        return $false
    }

    Write-Host "llama.cpp ist bereits installiert: $LlamaDir"
    Write-Host "Build: $($state.tag) / $($state.backend)"
    if ($probe.DeviceLine) { Write-Host "Startprobe: $($probe.DeviceLine.Trim())" }
    return $true
}

function Install-LlamaCpp {
    $nvidia = Get-NvidiaInfo

    if (-not $ForceUpdateLlamaCpp -and (Test-ExistingLlamaInstall $nvidia)) { return }

    Write-Step "llama.cpp wird automatisch eingerichtet"
    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null

    if ($nvidia) {
        $family = if ($nvidia.SupportedCudaMajor) { "CUDA-$($nvidia.SupportedCudaMajor).x" } else { "unbekannt" }
        Write-Host "NVIDIA erkannt: Treiber $($nvidia.Driver), nvidia-smi CUDA $($nvidia.Cuda), unterstuetzte Familie $family"
    } else {
        Write-Warning "nvidia-smi wurde nicht gefunden. Es wird ein CPU-Build installiert."
    }

    $package = Resolve-LlamaCppPackage $nvidia
    $release = $package.Release
    $backend = $package.Backend
    $mainPattern = $package.MainPattern
    $runtimePattern = $package.RuntimePattern

    Write-Host "Ausgewaehltes llama.cpp-Paket: $backend"
    Write-Host "Verwendetes llama.cpp-Release: $($release.tag_name)"

    $main = $release.assets | Where-Object { $_.name -match $mainPattern } | Select-Object -First 1
    $runtime = $null
    if ($runtimePattern) {
        $runtime = $release.assets | Where-Object { $_.name -match $runtimePattern } | Select-Object -First 1
    }
    if (-not $main) { throw "Kein passendes llama.cpp-Asset fuer '$backend' gefunden." }
    if ($runtimePattern -and -not $runtime) { throw "CUDA-Runtime-Asset fuer '$backend' nicht gefunden." }

    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("llmbench-llama-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    try {
        $mainZip = Join-Path $tmp $main.name
        Write-Host "Lade $($main.name)..."
        Invoke-WebRequest -Uri $main.browser_download_url -OutFile $mainZip -UseBasicParsing

        if (Test-Path $LlamaDir) { Remove-Item -Recurse -Force $LlamaDir }
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

        $benchExe = Join-Path $LlamaDir "llama-bench.exe"
        $serverExe = Join-Path $LlamaDir "llama-server.exe"
        if (-not (Test-Path $benchExe)) { throw "llama-bench.exe wurde nach dem Entpacken nicht gefunden." }
        if (-not (Test-Path $serverExe)) { throw "llama-server.exe wurde nach dem Entpacken nicht gefunden." }

        $probe = Invoke-LlamaBenchProbe $benchExe
        if (-not $probe.Success) {
            $hex = ""
            if ($null -ne $probe.ExitCode) {
                try { $hex = ('0x{0:X8}' -f ([uint32]$probe.ExitCode)) } catch { }
            }
            throw "llama-bench.exe ist nach der Installation nicht startbar. Backend: $backend, Exitcode: $($probe.ExitCode) $hex`nAusgabe:`n$($probe.Output)"
        }

        if ($probe.DeviceLine) {
            Write-Host "Startprobe erfolgreich: $($probe.DeviceLine.Trim())" -ForegroundColor Green
        } else {
            Write-Host "Startprobe erfolgreich." -ForegroundColor Green
        }

        $state = [ordered]@{
            tag = $release.tag_name
            backend = $backend
            installed_at = (Get-Date).ToString("o")
            main_asset = $main.name
            runtime_asset = if ($runtime) { $runtime.name } else { $null }
            nvidia_driver = if ($nvidia) { $nvidia.Driver } else { $null }
            cuda_compatibility = if ($nvidia -and $nvidia.Cuda) { $nvidia.Cuda.ToString() } else { $null }
            cuda_family = if ($nvidia) { $nvidia.SupportedCudaMajor } else { $null }
        }
        $state | ConvertTo-Json | Set-Content -Path $StateFile -Encoding UTF8
        Write-Host "llama.cpp $($release.tag_name) wurde installiert."

        if (-not (Get-PinnedLlamaTag)) {
            Write-Host "Fuer Serververgleiche denselben llama.cpp-Build auf allen Systemen verwenden:" -ForegroundColor Yellow
            Write-Host "  $($release.tag_name)" -ForegroundColor Yellow
        }
    } finally {
        Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    }
}

Write-Step "Systempruefung"
$PythonExe = Get-PythonCommand
if (-not $PythonExe) {
    throw "Python 3.10+ wurde vom Bootstrap nicht in PATH bereitgestellt."
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
& $VenvPython -m pip install -e "."
if ($LASTEXITCODE -ne 0) { throw "Projektabhaengigkeiten konnten nicht installiert werden." }

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

Write-Step "Vorpruefung"
& $VenvPython -m llmbench doctor --config $Config
if ($LASTEXITCODE -ne 0) { throw "Vorpruefung fehlgeschlagen. Siehe Ausgabe oben." }

if ($SetupOnly) {
    Write-Host ""
    Write-Host "Setup erfolgreich abgeschlossen." -ForegroundColor Green
    exit 0
}

Write-Step "Benchmark"
Write-Host "Wie lange soll der Test laufen?"
Write-Host "  1: kurz (short)    - schnelle Ueberpruefung"
Write-Host "  2: mittel (medium) - Standardwerte"
Write-Host "  3: lang (long)     - praezise Ergebnisse"
$choice = Read-Host "Auswahl [1-3, Standard=2]"

$duration = "medium"
if ($choice -eq "1") { $duration = "short" }
elseif ($choice -eq "3") { $duration = "long" }

Write-Host "Verwende Dauer: $duration"
& $VenvPython -m llmbench run --config $Config --duration $duration
if ($LASTEXITCODE -ne 0) { throw "Benchmark fehlgeschlagen (Exitcode $LASTEXITCODE)." }
