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

function Invoke-GitHubApi([string]$Url) {
    $headers = @{
        "User-Agent" = "llm-server-benchmark-installer"
        "Accept" = "application/vnd.github+json"
    }
    if ($env:GITHUB_TOKEN) { $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN" }
    return Invoke-RestMethod -Uri $Url -Headers $headers
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

    $cudaText = $null
    $smiText = (& $cmd.Source 2>$null | Out-String)
    if ($smiText -match 'CUDA\s*Version\s*:?\s*([0-9]+(?:\.[0-9]+)?)') {
        $cudaText = $Matches[1]
    }

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
        CudaText = $cudaText
        SupportedMajor = $supportedMajor
    }
}

function Invoke-LlamaProbe([string]$BenchExe) {
    $outFile = [System.IO.Path]::GetTempFileName()
    $errFile = [System.IO.Path]::GetTempFileName()
    try {
        $proc = Start-Process -FilePath $BenchExe -ArgumentList "--list-devices" -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput $outFile -RedirectStandardError $errFile
        $stdout = Get-Content $outFile -Raw -ErrorAction SilentlyContinue
        $stderr = Get-Content $errFile -Raw -ErrorAction SilentlyContinue
        $combined = (($stdout + "`n" + $stderr).Trim())
        return [pscustomobject]@{
            Ok = ($proc.ExitCode -eq 0)
            ExitCode = $proc.ExitCode
            Output = $combined
        }
    } catch {
        return [pscustomobject]@{
            Ok = $false
            ExitCode = $null
            Output = $_.Exception.Message
        }
    } finally {
        Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue
    }
}

function Test-ExistingLlama {
    $bench = Join-Path $LlamaDir "llama-bench.exe"
    $server = Join-Path $LlamaDir "llama-server.exe"
    if (-not (Test-Path $bench) -or -not (Test-Path $server)) { return $false }
    $probe = Invoke-LlamaProbe $bench
    if ($probe.Ok) {
        Write-Host "Vorhandene llama.cpp-Installation ist startbar." -ForegroundColor Green
        if (Test-Path $StateFile) {
            try {
                $state = Get-Content $StateFile -Raw | ConvertFrom-Json
                Write-Host "Build: $($state.tag) / $($state.backend)"
            } catch { }
        }
        return $true
    }
    Write-Warning "Vorhandene llama.cpp-Installation ist defekt (Exitcode $($probe.ExitCode)). Es wird automatisch ein anderer Build gesucht."
    return $false
}

function Get-Releases {
    $pin = Get-PinnedTag
    if ($pin) {
        Write-Host "Festgelegter llama.cpp-Build: $pin"
        return @((Invoke-GitHubApi "https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/$pin"))
    }

    $releases = @(Invoke-GitHubApi "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=12&page=1")
    return @($releases | Where-Object { -not $_.draft } | Select-Object -First 8)
}

function Get-CudaPackages($Release, [int]$PreferredMajor) {
    $main = @{}
    $runtime = @{}

    foreach ($asset in @($Release.assets)) {
        $name = [string]$asset.name
        if ($name -match '^llama-.*-bin-win-cuda-([0-9]+(?:\.[0-9]+)*)-x64\.zip$') {
            $main[$Matches[1]] = $asset
        } elseif ($name -match '^cudart-llama-bin-win-cuda-([0-9]+(?:\.[0-9]+)*)-x64\.zip$') {
            $runtime[$Matches[1]] = $asset
        }
    }

    $packages = @()
    foreach ($versionText in $main.Keys) {
        if (-not $runtime.ContainsKey($versionText)) { continue }
        try { $version = [version]$versionText } catch { continue }
        if ($PreferredMajor -and $version.Major -gt $PreferredMajor) { continue }
        $priority = if ($PreferredMajor -and $version.Major -eq $PreferredMajor) { 0 } else { 1 }
        $packages += [pscustomobject]@{
            Version = $version
            VersionText = $versionText
            Backend = "cuda-$versionText"
            MainAsset = $main[$versionText]
            RuntimeAsset = $runtime[$versionText]
            Priority = $priority
        }
    }

    return @($packages | Sort-Object Priority, @{Expression="Version";Descending=$true})
}

function Expand-LlamaPackage($Package, [string]$Destination, [string]$TempRoot) {
    if (Test-Path $Destination) { Remove-Item -Recurse -Force $Destination }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null

    $mainZip = Join-Path $TempRoot $Package.MainAsset.name
    $runtimeZip = Join-Path $TempRoot $Package.RuntimeAsset.name

    Write-Host "  Lade $($Package.MainAsset.name)"
    Invoke-WebRequest -Uri $Package.MainAsset.browser_download_url -OutFile $mainZip -UseBasicParsing
    Expand-Archive -Path $mainZip -DestinationPath $Destination -Force

    Write-Host "  Lade $($Package.RuntimeAsset.name)"
    Invoke-WebRequest -Uri $Package.RuntimeAsset.browser_download_url -OutFile $runtimeZip -UseBasicParsing
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
    if (-not $nvidia) {
        Write-Host "Keine NVIDIA-GPU über nvidia-smi erkannt. Der normale Core-Installer übernimmt den CPU-Fall."
        return $false
    }

    Write-Step "llama.cpp CUDA-Selbsttest"
    Write-Host "NVIDIA-Treiber: $($nvidia.Driver), nvidia-smi CUDA: $($nvidia.CudaText), bevorzugte CUDA-Familie: $($nvidia.SupportedMajor).x"

    $releases = @(Get-Releases)
    if ($releases.Count -eq 0) { throw "Keine llama.cpp-Releases gefunden." }

    $attempts = New-Object System.Collections.Generic.List[object]
    $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("llmbench-llama-heal-" + [guid]::NewGuid().ToString("N"))
    $stage = Join-Path $tempRoot "stage"
    New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null

    try {
        $maxAttempts = 8
        foreach ($release in $releases) {
            $packages = @(Get-CudaPackages $release $nvidia.SupportedMajor)
            foreach ($package in $packages) {
                if ($attempts.Count -ge $maxAttempts) { break }

                Write-Host ""
                Write-Host "Teste llama.cpp $($release.tag_name) / $($package.Backend)..." -ForegroundColor Cyan
                try {
                    Expand-LlamaPackage $package $stage $tempRoot
                    $bench = Join-Path $stage "llama-bench.exe"
                    $server = Join-Path $stage "llama-server.exe"
                    if (-not (Test-Path $bench) -or -not (Test-Path $server)) {
                        throw "llama-bench.exe oder llama-server.exe fehlt nach dem Entpacken."
                    }

                    $probe = Invoke-LlamaProbe $bench
                    $attempts.Add([pscustomobject]@{
                        Tag = $release.tag_name
                        Backend = $package.Backend
                        ExitCode = $probe.ExitCode
                        Output = $probe.Output
                    })

                    if (-not $probe.Ok) {
                        Write-Warning "Build startet nicht (Exitcode $($probe.ExitCode)). Nächster Kandidat..."
                        continue
                    }

                    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
                    if (Test-Path $LlamaDir) { Remove-Item -Recurse -Force $LlamaDir }
                    New-Item -ItemType Directory -Force -Path $LlamaDir | Out-Null
                    Get-ChildItem -Path $stage -Force | ForEach-Object {
                        Copy-Item $_.FullName -Destination $LlamaDir -Recurse -Force
                    }

                    $state = [ordered]@{
                        tag = $release.tag_name
                        backend = $package.Backend
                        installed_at = (Get-Date).ToString("o")
                        main_asset = $package.MainAsset.name
                        runtime_asset = $package.RuntimeAsset.name
                        nvidia_driver = $nvidia.Driver
                        cuda_compatibility = $nvidia.CudaText
                        installer = "self-healing"
                        attempts_before_success = $attempts.Count
                    }
                    $state | ConvertTo-Json | Set-Content -Path $StateFile -Encoding UTF8

                    $deviceLine = ($probe.Output -split "`r?`n" | Where-Object { $_ -match 'Device|CUDA' } | Select-Object -First 1)
                    Write-Host ""
                    Write-Host "Funktionierender llama.cpp-Build gefunden: $($release.tag_name) / $($package.Backend)" -ForegroundColor Green
                    if ($deviceLine) { Write-Host $deviceLine.Trim() -ForegroundColor Green }
                    return $true
                } catch {
                    $attempts.Add([pscustomobject]@{
                        Tag = $release.tag_name
                        Backend = $package.Backend
                        ExitCode = $null
                        Output = $_.Exception.Message
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
        throw "Keiner der getesteten offiziellen llama.cpp-CUDA-Builds konnte auf diesem System gestartet werden. CPU-Fallback wird bei erkannter NVIDIA-GPU bewusst nicht still verwendet, damit der Benchmark keine falschen GPU-Ergebnisse produziert."
    } finally {
        Remove-Item -Recurse -Force $tempRoot -ErrorAction SilentlyContinue
    }
}

if (-not $ForceUpdateLlamaCpp -and (Test-ExistingLlama)) {
    exit 0
}

$nvidia = Get-NvidiaInfo
if (-not $nvidia) {
    # Kein NVIDIA-System: Core-Skript übernimmt CPU-Installation.
    exit 0
}

[void](Install-WorkingCudaBuild)
exit 0
