param(
    [string]$Config = "benchmark.yaml",
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
            $args = @($candidate.Args) + @("-c", "import sys; assert sys.version_info >= (3,10); print(sys.executable)")
            $path = & $cmd.Source @args 2>$null
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

function Get-NvidiaInfo {
    $nvsmi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if (-not $nvsmi) {
        return $null
    }
    $text = (& $nvsmi.Source 2>$null | Out-String)
    $driver = (& $nvsmi.Source --query-gpu=driver_version --format=csv,noheader 2>$null | Select-Object -First 1)
    $cuda = $null
    if ($text -match 'CUDA Version:\s*([0-9]+(?:\.[0-9]+)?)') {
        $cuda = [version]$Matches[1]
    }
    return @{ Command = $nvsmi.Source; Driver = $driver; Cuda = $cuda }
}

function Get-LlamaCppRelease {
    $headers = @{ "User-Agent" = "llm-server-benchmark-installer"; "Accept" = "application/vnd.github+json" }
    return Invoke-RestMethod -Uri "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest" -Headers $headers
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
    $release = Get-LlamaCppRelease
    if (-not $release -or -not $release.assets) {
        throw "Die aktuelle llama.cpp-Version konnte nicht von GitHub ermittelt werden."
    }

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
        Write-Host "NVIDIA erkannt: Treiber $($nvidia.Driver), gemeldete CUDA-Kompatibilität $($nvidia.Cuda)"
        Write-Host "Ausgewähltes llama.cpp-Paket: $backend"
    } else {
        Write-Warning "nvidia-smi wurde nicht gefunden. Es wird automatisch der CPU-Build installiert."
    }

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
& $VenvPython -m pip install -e .
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
& $VenvPython -m llmbench run --config $Config
if ($LASTEXITCODE -ne 0) {
    throw "Benchmark fehlgeschlagen (Exitcode $LASTEXITCODE)."
}
