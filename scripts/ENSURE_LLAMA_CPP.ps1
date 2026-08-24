[CmdletBinding()]
param(
    [string]$LlamaCppTag = "",
    [switch]$ForceUpdateLlamaCpp
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Root = Split-Path -Parent $PSScriptRoot
$ToolsDir = Join-Path $Root "tools"
$LlamaDir = Join-Path $ToolsDir "llama.cpp"
$StateFile = Join-Path $LlamaDir ".llama-build.json"
$PinFile = Join-Path $Root "llama-cpp-version.txt"

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "=== $Text ===" -ForegroundColor Cyan
}

function Get-PinnedTag {
    if ($LlamaCppTag) { return $LlamaCppTag.Trim() }
    if ($env:LLMBENCH_LLAMACPP_TAG) { return $env:LLMBENCH_LLAMACPP_TAG.Trim() }
    if (Test-Path $PinFile) {
        foreach ($line in Get-Content $PinFile) {
            $value = $line.Trim()
            if ($value -and -not $value.StartsWith("#")) { return $value }
        }
    }
    return $null
}

function Get-NvidiaInfo {
    $cmd = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if (-not $cmd) { return $null }

    $driver = (& $cmd.Source --query-gpu=driver_version --format=csv,noheader 2>$null | Select-Object -First 1)
    if ($driver) { $driver = $driver.ToString().Trim() }

    $gpuName = (& $cmd.Source --query-gpu=name --format=csv,noheader 2>$null | Select-Object -First 1)
    if ($gpuName) { $gpuName = $gpuName.ToString().Trim() }

    $cudaText = $null
    try {
        $smiText = (& $cmd.Source 2>$null | Out-String)
        if ($smiText -match 'CUDA\s*Version\s*:?\s*([0-9]+(?:\.[0-9]+)?)') {
            $cudaText = $Matches[1]
        }
    } catch { }

    $supportedMajor = $null
    if ($driver -match '^([0-9]+)') {
        $driverMajor = [int]$Matches[1]
        if ($driverMajor -ge 580) { $supportedMajor = 13 }
        elseif ($driverMajor -ge 525) { $supportedMajor = 12 }
    }
    if (-not $supportedMajor -and $cudaText -match '^([0-9]+)') {
        $supportedMajor = [int]$Matches[1]
    }

    return [pscustomobject]@{
        Command = $cmd.Source
        Driver = $driver
        GpuName = $gpuName
        CudaText = $cudaText
        SupportedMajor = $supportedMajor
    }
}

function Invoke-LlamaProbe([string]$BenchExe, [int]$Retries = 1) {
    $last = $null
    foreach ($attempt in 1..([Math]::Max(1, $Retries))) {
        $outFile = [System.IO.Path]::GetTempFileName()
        $errFile = [System.IO.Path]::GetTempFileName()
        try {
            $proc = Start-Process -FilePath $BenchExe -ArgumentList "--list-devices" -NoNewWindow -Wait -PassThru `
                -RedirectStandardOutput $outFile -RedirectStandardError $errFile
            $stdout = Get-Content $outFile -Raw -ErrorAction SilentlyContinue
            $stderr = Get-Content $errFile -Raw -ErrorAction SilentlyContinue
            $combined = (($stdout + "`n" + $stderr).Trim())
            $last = [pscustomobject]@{
                Ok = ($proc.ExitCode -eq 0)
                ExitCode = $proc.ExitCode
                Output = $combined
                Attempt = $attempt
            }
        } catch {
            $last = [pscustomobject]@{
                Ok = $false
                ExitCode = $null
                Output = $_.Exception.Message
                Attempt = $attempt
            }
        } finally {
            Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue
        }

        if ($last.Ok) { return $last }
        if ($attempt -lt $Retries) { Start-Sleep -Milliseconds 400 }
    }
    return $last
}

function Test-ExistingLlama {
    $bench = Join-Path $LlamaDir "llama-bench.exe"
    $server = Join-Path $LlamaDir "llama-server.exe"
    if (-not (Test-Path $bench) -or -not (Test-Path $server)) { return $false }

    $state = $null
    if (Test-Path $StateFile) {
        try { $state = Get-Content $StateFile -Raw | ConvertFrom-Json } catch { }
    }

    if ($state -and $state.cuda_workaround -eq "GGML_CUDA_PDL=0") {
        $env:GGML_CUDA_PDL = "0"
        Write-Host "CUDA-Workaround aus Build-State aktiviert: GGML_CUDA_PDL=0" -ForegroundColor Yellow
    }

    $probe = Invoke-LlamaProbe $bench 3
    if ($probe.Ok) {
        Write-Host "Vorhandene llama.cpp-Installation ist startbar." -ForegroundColor Green
        if ($state) { Write-Host "Build: $($state.tag) / $($state.backend)" }
        return $true
    }

    Write-Warning "Vorhandene llama.cpp-Installation ist defekt (Exitcode $($probe.ExitCode)). Es wird automatisch ein anderer Build gesucht."
    return $false
}

function Add-TagsFromText($List, [string]$Text) {
    if (-not $Text) { return }
    foreach ($match in [regex]::Matches($Text, '/releases/tag/(b[0-9]+)')) {
        $List.Add($match.Groups[1].Value)
    }
}

function Get-ReleaseTags {
    $pin = Get-PinnedTag
    if ($pin) {
        Write-Host "Festgelegter llama.cpp-Build: $pin"
        return @($pin)
    }

    try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }
    $rawTags = New-Object System.Collections.Generic.List[string]
    $sourceMessages = New-Object System.Collections.Generic.List[string]

    # Quelle 1: GitHub REST API. Schnellster Weg, aber auf Firmen-/Proxy-PCs
    # manchmal rate-limited oder gefiltert. Ein Fehler ist deshalb NICHT fatal.
    try {
        $headers = @{
            "User-Agent" = "llm-server-benchmark-installer"
            "Accept" = "application/vnd.github+json"
        }
        if ($env:GITHUB_TOKEN) { $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN" }
        $api = Invoke-RestMethod -Uri "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30&page=1" -Headers $headers -TimeoutSec 20
        foreach ($release in @($api)) {
            if ($release.tag_name -and ([string]$release.tag_name -match '^b[0-9]+$')) {
                $rawTags.Add([string]$release.tag_name)
            }
        }
        $sourceMessages.Add("GitHub API: $(@($api).Count) Antworten")
    } catch {
        $sourceMessages.Add("GitHub API fehlgeschlagen: $($_.Exception.Message)")
    }

    # Quelle 2: Releases-Atom-Feed. Braucht kein API-Limit und funktioniert
    # oft auch dann, wenn api.github.com im Netz eingeschraenkt ist.
    if ($rawTags.Count -lt 8) {
        try {
            $atom = Invoke-WebRequest -Uri "https://github.com/ggml-org/llama.cpp/releases.atom" -UseBasicParsing -TimeoutSec 20
            Add-TagsFromText $rawTags ([string]$atom.Content)
            $sourceMessages.Add("releases.atom geladen")
        } catch {
            $sourceMessages.Add("releases.atom fehlgeschlagen: $($_.Exception.Message)")
        }
    }

    # Quelle 3: normale GitHub-Releases-Seite.
    if ($rawTags.Count -lt 8) {
        try {
            $html = Invoke-WebRequest -Uri "https://github.com/ggml-org/llama.cpp/releases" -UseBasicParsing -TimeoutSec 20
            Add-TagsFromText $rawTags ([string]$html.Content)
            $sourceMessages.Add("Releases-HTML geladen")
        } catch {
            $sourceMessages.Add("Releases-HTML fehlgeschlagen: $($_.Exception.Message)")
        }
    }

    # Quelle 4: git ls-remote, falls Git vorhanden ist. Keine GitHub-API noetig.
    if ($rawTags.Count -lt 8) {
        $git = Get-Command git.exe -ErrorAction SilentlyContinue
        if ($git) {
            try {
                $lines = & $git.Source ls-remote --tags --refs https://github.com/ggml-org/llama.cpp.git 2>$null
                foreach ($line in @($lines)) {
                    if ($line -match 'refs/tags/(b[0-9]+)$') { $rawTags.Add($Matches[1]) }
                }
                $sourceMessages.Add("git ls-remote geladen")
            } catch {
                $sourceMessages.Add("git ls-remote fehlgeschlagen: $($_.Exception.Message)")
            }
        }
    }

    $unique = @{}
    $sortable = @()
    foreach ($tag in $rawTags) {
        if (-not $tag -or $unique.ContainsKey($tag)) { continue }
        $unique[$tag] = $true
        if ($tag -match '^b([0-9]+)$') {
            $sortable += [pscustomobject]@{ Tag = $tag; Build = [int64]$Matches[1] }
        }
    }

    $tags = @($sortable | Sort-Object Build -Descending | Select-Object -First 12 | ForEach-Object { $_.Tag })
    if ($tags.Count -eq 0) {
        Write-Host "Release-Ermittlung Diagnose:" -ForegroundColor Yellow
        foreach ($msg in $sourceMessages) { Write-Host "  - $msg" -ForegroundColor Yellow }
        throw "Keine llama.cpp-Build-Tags konnten ermittelt werden. Wahrscheinlich blockiert das Netzwerk GitHub-Releases/API."
    }

    Write-Host "llama.cpp-Builds gefunden: $($tags.Count) (neuester: $($tags[0]))" -ForegroundColor Green
    return $tags
}

function Get-CudaVersions([int]$PreferredMajor) {
    if ($PreferredMajor -ge 13) { return @("13.3") }
    if ($PreferredMajor -eq 12) { return @("12.4") }
    # Unbekannte Familie: zuerst den konservativeren CUDA-12-Build testen.
    return @("12.4")
}

function New-Package([string]$Tag, [string]$CudaVersion) {
    $base = "https://github.com/ggml-org/llama.cpp/releases/download/$Tag"
    $mainName = "llama-$Tag-bin-win-cuda-$CudaVersion-x64.zip"
    $runtimeName = "cudart-llama-bin-win-cuda-$CudaVersion-x64.zip"
    return [pscustomobject]@{
        Tag = $Tag
        Backend = "cuda-$CudaVersion"
        MainName = $mainName
        RuntimeName = $runtimeName
        MainUrl = "$base/$mainName"
        RuntimeUrl = "$base/$runtimeName"
    }
}

function Invoke-Download([string]$Url, [string]$Path) {
    $lastError = $null
    foreach ($attempt in 1..3) {
        try {
            Invoke-WebRequest -Uri $Url -OutFile $Path -UseBasicParsing -TimeoutSec 180
            if ((Test-Path $Path) -and (Get-Item $Path).Length -gt 0) { return }
            throw "Download lieferte eine leere Datei."
        } catch {
            $lastError = $_.Exception.Message
            Remove-Item $Path -Force -ErrorAction SilentlyContinue
            if ($attempt -lt 3) { Start-Sleep -Seconds $attempt }
        }
    }
    throw "Download fehlgeschlagen: $Url - $lastError"
}

function Expand-LlamaPackage($Package, [string]$Destination, [string]$TempRoot) {
    if (Test-Path $Destination) { Remove-Item -Recurse -Force $Destination }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null

    $mainZip = Join-Path $TempRoot $Package.MainName
    $runtimeZip = Join-Path $TempRoot $Package.RuntimeName

    Write-Host "  Lade $($Package.MainName)"
    Invoke-Download $Package.MainUrl $mainZip
    Expand-Archive -Path $mainZip -DestinationPath $Destination -Force

    Write-Host "  Lade $($Package.RuntimeName)"
    Invoke-Download $Package.RuntimeUrl $runtimeZip
    Expand-Archive -Path $runtimeZip -DestinationPath $Destination -Force

    $bench = Join-Path $Destination "llama-bench.exe"
    if (-not (Test-Path $bench)) {
        $nested = Get-ChildItem -Path $Destination -Filter "llama-bench.exe" -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($nested) {
            $source = $nested.Directory.FullName
            Get-ChildItem -Path $source -Force | ForEach-Object {
                Copy-Item $_.FullName -Destination $Destination -Recurse -Force
            }
        }
    }
}

function Install-WorkingCudaBuild {
    $nvidia = Get-NvidiaInfo
    if (-not $nvidia) { return $false }

    Write-Step "llama.cpp CUDA-Selbsttest"
    Write-Host "GPU: $($nvidia.GpuName)"
    Write-Host "NVIDIA-Treiber: $($nvidia.Driver), nvidia-smi CUDA: $($nvidia.CudaText), bevorzugte CUDA-Familie: $($nvidia.SupportedMajor).x"

    $tags = @(Get-ReleaseTags)
    $cudaVersions = @(Get-CudaVersions $nvidia.SupportedMajor)

    $attempts = New-Object System.Collections.Generic.List[object]
    $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("llmbench-llama-heal-" + [guid]::NewGuid().ToString("N"))
    $stage = Join-Path $tempRoot "stage"
    New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null

    try {
        $maxAttempts = 8
        foreach ($tag in $tags) {
            foreach ($cudaVersion in $cudaVersions) {
                if ($attempts.Count -ge $maxAttempts) { break }
                $package = New-Package $tag $cudaVersion

                Write-Host ""
                Write-Host "Teste llama.cpp $tag / $($package.Backend)..." -ForegroundColor Cyan
                try {
                    Expand-LlamaPackage $package $stage $tempRoot
                    $bench = Join-Path $stage "llama-bench.exe"
                    $server = Join-Path $stage "llama-server.exe"
                    if (-not (Test-Path $bench) -or -not (Test-Path $server)) {
                        throw "llama-bench.exe oder llama-server.exe fehlt nach dem Entpacken."
                    }

                    $workaround = $null
                    $oldPdl = $env:GGML_CUDA_PDL
                    Remove-Item Env:\GGML_CUDA_PDL -ErrorAction SilentlyContinue
                    $probe = Invoke-LlamaProbe $bench 3

                    if (-not $probe.Ok -and $nvidia.SupportedMajor -ge 13) {
                        Write-Host "  Normaler Start fehlgeschlagen. Teste GGML_CUDA_PDL=0..." -ForegroundColor Yellow
                        $env:GGML_CUDA_PDL = "0"
                        $pdlProbe = Invoke-LlamaProbe $bench 3
                        if ($pdlProbe.Ok) {
                            $probe = $pdlProbe
                            $workaround = "GGML_CUDA_PDL=0"
                        } else {
                            $probe = $pdlProbe
                            if ($null -eq $oldPdl) { Remove-Item Env:\GGML_CUDA_PDL -ErrorAction SilentlyContinue }
                            else { $env:GGML_CUDA_PDL = $oldPdl }
                        }
                    } elseif ($probe.Ok) {
                        if ($null -eq $oldPdl) { Remove-Item Env:\GGML_CUDA_PDL -ErrorAction SilentlyContinue }
                        else { $env:GGML_CUDA_PDL = $oldPdl }
                    }

                    $attempts.Add([pscustomobject]@{
                        Tag = $tag
                        Backend = $package.Backend
                        ExitCode = $probe.ExitCode
                        Output = $probe.Output
                        Workaround = $workaround
                    })

                    if (-not $probe.Ok) {
                        Write-Warning "Build startet nicht (Exitcode $($probe.ExitCode)). Naechster Release-Kandidat..."
                        continue
                    }

                    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
                    if (Test-Path $LlamaDir) { Remove-Item -Recurse -Force $LlamaDir }
                    New-Item -ItemType Directory -Force -Path $LlamaDir | Out-Null
                    Get-ChildItem -Path $stage -Force | ForEach-Object {
                        Copy-Item $_.FullName -Destination $LlamaDir -Recurse -Force
                    }

                    if ($workaround -eq "GGML_CUDA_PDL=0") { $env:GGML_CUDA_PDL = "0" }

                    $state = [ordered]@{
                        tag = $tag
                        backend = $package.Backend
                        installed_at = (Get-Date).ToString("o")
                        main_asset = $package.MainName
                        runtime_asset = $package.RuntimeName
                        nvidia_driver = $nvidia.Driver
                        gpu_name = $nvidia.GpuName
                        cuda_compatibility = $nvidia.CudaText
                        installer = "self-healing"
                        cuda_workaround = $workaround
                        attempts_before_success = $attempts.Count
                    }
                    $state | ConvertTo-Json | Set-Content -Path $StateFile -Encoding UTF8

                    $deviceLine = ($probe.Output -split "`r?`n" | Where-Object { $_ -match 'Device|CUDA' } | Select-Object -First 1)
                    Write-Host ""
                    Write-Host "Funktionierender llama.cpp-Build gefunden: $tag / $($package.Backend)" -ForegroundColor Green
                    if ($workaround) { Write-Host "Aktiver CUDA-Workaround: $workaround" -ForegroundColor Yellow }
                    if ($deviceLine) { Write-Host $deviceLine.Trim() -ForegroundColor Green }
                    return $true
                } catch {
                    $attempts.Add([pscustomobject]@{
                        Tag = $tag
                        Backend = $package.Backend
                        ExitCode = $null
                        Output = $_.Exception.Message
                        Workaround = $null
                    })
                    Write-Warning "Kandidat fehlgeschlagen: $($_.Exception.Message)"
                }
            }
            if ($attempts.Count -ge $maxAttempts) { break }
        }

        Write-Host ""
        Write-Host "Alle getesteten CUDA-Builds sind fehlgeschlagen:" -ForegroundColor Red
        foreach ($attempt in $attempts) {
            Write-Host "  $($attempt.Tag) / $($attempt.Backend) -> Exitcode $($attempt.ExitCode)"
        }
        throw "Keiner der getesteten offiziellen llama.cpp-CUDA-Builds konnte auf diesem System gestartet werden."
    } finally {
        Remove-Item -Recurse -Force $tempRoot -ErrorAction SilentlyContinue
    }
}

if (-not $ForceUpdateLlamaCpp -and (Test-ExistingLlama)) { exit 0 }

$nvidia = Get-NvidiaInfo
if (-not $nvidia) {
    # Kein NVIDIA-System: der Core-Installer uebernimmt den CPU-Fall.
    exit 0
}

[void](Install-WorkingCudaBuild)
exit 0
