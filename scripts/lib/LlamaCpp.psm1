# Auswahl, Installation und Startprobe der llama.cpp-Pakete unter Windows.
#
# Statt genau eines Pakets wird eine Kandidatenliste nacheinander probiert
# (passende CUDA-Version -> aeltere CUDA-Hauptversion -> Vulkan -> CPU). Stuerzt
# ein Build beim ersten Start ab (z. B. 0xC0000005), wird automatisch der
# naechste installiert - wie unter Linux (llmbench/llama_cpp_setup.py).
# Texte kommen ueber T aus scripts/lib/UI.psm1 (muss vorher importiert sein).

# CUDA 13 unterstuetzt nur noch GPUs ab Compute Capability 7.5 (Turing).
$script:MinComputeCapCuda13 = [version]'7.5'

function ConvertTo-LlamaVersion([string]$Value) {
    if (-not $Value) { return $null }
    $Value = $Value.Trim()
    if ($Value -notmatch '\.') { $Value = "$Value.0" }
    try { return [version]$Value } catch { return $null }
}

function Get-NvidiaInfo {
    # Auch als Funktion ersetzbar (Tests): Get-Command findet nvidia-smi.exe
    # im PATH ebenso wie eine gleichnamige Funktion.
    $nvsmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if (-not $nvsmi) { return $null }

    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $driver = (& $nvsmi --query-gpu=driver_version --format=csv,noheader 2>$null | Select-Object -First 1)
        $gpuLine = (& $nvsmi --query-gpu=name,compute_cap --format=csv,noheader 2>$null | Select-Object -First 1)
        $text = (& $nvsmi 2>$null | Out-String)
    } finally {
        $ErrorActionPreference = $oldEap
    }
    if ($driver) { $driver = $driver.ToString().Trim() }

    $gpuName = $null
    $computeCap = $null
    if ($gpuLine) {
        $parts = $gpuLine.ToString().Split(',')
        if ($parts.Count -ge 2) {
            $gpuName = ($parts[0..($parts.Count - 2)] -join ',').Trim()
            $computeCap = ConvertTo-LlamaVersion $parts[-1]
        }
    }

    $reportedCuda = $null
    $source = T 'core.unknown'
    if ($text -match 'CUDA\s*Version\s*:?\s*([0-9]+(?:\.[0-9]+)?)') {
        $reportedCuda = ConvertTo-LlamaVersion $Matches[1]
        if ($reportedCuda) { $source = 'nvidia-smi' }
    }

    $driverMajor = $null
    $supportedCudaMajor = $null
    if ($driver -match '^([0-9]+)') {
        $driverMajor = [int]$Matches[1]
        # NVIDIA minor-version compatibility:
        # CUDA 13.x => driver >= 580, CUDA 12.x => >= 525, CUDA 11.x => >= 450
        if ($driverMajor -ge 580) { $supportedCudaMajor = 13 }
        elseif ($driverMajor -ge 525) { $supportedCudaMajor = 12 }
        elseif ($driverMajor -ge 450) { $supportedCudaMajor = 11 }
    }

    if (-not $reportedCuda -and $supportedCudaMajor) {
        $reportedCuda = [version]("$supportedCudaMajor.0")
        $source = T 'core.driver_version' $driver
    }

    return @{
        Driver = $driver
        DriverMajor = $driverMajor
        Cuda = $reportedCuda
        CudaSource = $source
        SupportedCudaMajor = $supportedCudaMajor
        GpuName = $gpuName
        ComputeCap = $computeCap
    }
}

function Get-LlamaBuildPreference {
    # Wie unter Linux: LLMBENCH_LLAMACPP_BUILD_BACKEND=auto|cuda|vulkan|cpu
    $value = if ($env:LLMBENCH_LLAMACPP_BUILD_BACKEND) { $env:LLMBENCH_LLAMACPP_BUILD_BACKEND.Trim().ToLowerInvariant() } else { 'auto' }
    if (@('auto', 'cuda', 'vulkan', 'cpu') -notcontains $value) {
        throw (T 'core.invalid_build_backend' $value)
    }
    return $value
}

function Find-ReleaseAsset($Release, [string]$Pattern) {
    return (@($Release.assets) | Where-Object { [string]$_.name -match $Pattern } | Select-Object -First 1)
}

function Get-CudaPackages($Release) {
    $result = @()
    foreach ($asset in @($Release.assets)) {
        $name = [string]$asset.name
        if ($name -notmatch '^llama-.*-bin-win-cuda-([0-9]+(?:\.[0-9]+)*)-x64\.zip$') { continue }
        $versionText = $Matches[1]
        $version = ConvertTo-LlamaVersion $versionText
        if (-not $version) { continue }
        $runtime = Find-ReleaseAsset $Release ('^cudart-llama-bin-win-cuda-' + [regex]::Escape($versionText) + '-x64\.zip$')
        if (-not $runtime) { continue }
        $result += [pscustomobject]@{
            Backend = "cuda-$versionText"
            Kind = 'cuda'
            Version = $version
            MainAsset = $asset
            RuntimeAsset = $runtime
        }
    }
    return $result
}

function Get-LlamaPackageCandidates {
    # Reihenfolge der Installationsversuche fuer ein Release.
    param($Release, $Nvidia, [string]$Preference = 'auto')
    $candidates = @()

    if ($Nvidia -and @('auto', 'cuda') -contains $Preference) {
        $family = if ($Nvidia.SupportedCudaMajor) { [int]$Nvidia.SupportedCudaMajor } elseif ($Nvidia.Cuda) { [int]$Nvidia.Cuda.Major } else { $null }
        $reported = $Nvidia.Cuda
        $cuda = @(Get-CudaPackages $Release | Where-Object {
                # Neuer als der Treiber: laeuft nicht. CUDA 13 auf GPUs < 7.5: nicht unterstuetzt.
                (-not $family -or $_.Version.Major -le $family) -and
                (-not $Nvidia.ComputeCap -or $_.Version.Major -lt 13 -or $Nvidia.ComputeCap -ge $script:MinComputeCapCuda13)
            })
        if ($family) {
            $same = @($cuda | Where-Object { $_.Version.Major -eq $family })
            # Zuerst die hoechste Version <= der vom Treiber gemeldeten, dann die uebrigen
            # derselben Hauptversion (naechsthoehere zuerst), dann aeltere Hauptversionen.
            $candidates += @($same | Where-Object { -not $reported -or $_.Version -le $reported } | Sort-Object Version -Descending)
            $candidates += @($same | Where-Object { $reported -and $_.Version -gt $reported } | Sort-Object Version)
            $candidates += @($cuda | Where-Object { $_.Version.Major -lt $family } | Sort-Object Version -Descending)
        } else {
            # CUDA-Familie unbekannt: konservativ mit dem aeltesten Build beginnen.
            $candidates += @($cuda | Sort-Object Version)
        }
    }

    if (($Nvidia -and $Preference -eq 'auto') -or $Preference -eq 'vulkan') {
        $vulkan = Find-ReleaseAsset $Release '^llama-.*-bin-win-vulkan-x64\.zip$'
        if ($vulkan) {
            $candidates += [pscustomobject]@{ Backend = 'vulkan'; Kind = 'vulkan'; Version = $null; MainAsset = $vulkan; RuntimeAsset = $null }
        }
    }

    if (@('auto', 'cpu') -contains $Preference) {
        $cpu = Find-ReleaseAsset $Release '^llama-.*-bin-win-cpu-x64\.zip$'
        if ($cpu) {
            $candidates += [pscustomobject]@{ Backend = 'cpu'; Kind = 'cpu'; Version = $null; MainAsset = $cpu; RuntimeAsset = $null }
        }
    }
    return $candidates
}

function Select-LlamaRelease {
    # Neuestes Release, das fuer diese Maschine das bevorzugte Paket enthaelt
    # (bei NVIDIA einen CUDA-Build); sonst das neueste mit ueberhaupt einem Paket.
    param($Releases, $Nvidia, [string]$Preference = 'auto')
    $fallback = $null
    foreach ($release in @($Releases)) {
        $candidates = @(Get-LlamaPackageCandidates -Release $release -Nvidia $Nvidia -Preference $Preference)
        if ($candidates.Count -eq 0) { continue }
        $result = [pscustomobject]@{ Release = $release; Candidates = $candidates }
        if (-not $Nvidia -or $Preference -ne 'auto' -or $candidates[0].Kind -eq 'cuda') { return $result }
        if (-not $fallback) { $fallback = $result }
    }
    if ($fallback) { return $fallback }
    throw (T 'core.no_package')
}

function Format-LlamaExitCode($ExitCode) {
    # Windows-NTSTATUS-Codes verstaendlich machen (z. B. -1073741819 = 0xC0000005).
    if ($null -eq $ExitCode) { return (T 'core.exit_unknown') }
    $unsigned = [uint32]([int64]$ExitCode -band [int64]4294967295)
    $hex = '0x{0:X8}' -f $unsigned
    $meaning = switch ($hex) {
        '0xC0000005' { T 'core.exit_access_violation' }
        '0xC0000135' { T 'core.exit_dll_missing' }
        '0xC0000139' { T 'core.exit_dll_missing' }
        '0xC000001D' { T 'core.exit_illegal_instruction' }
        '0xC0000409' { T 'core.exit_fail_fast' }
        default { $null }
    }
    if ($meaning) { return "$hex – $meaning" }
    return (T 'core.exit_code' $ExitCode $hex)
}

function Invoke-ExeProbe([string]$Exe, [string]$Arguments) {
    # Programm kurz starten und Exitcode + gesamte Ausgabe einsammeln.
    $outFile = [System.IO.Path]::GetTempFileName()
    $errFile = [System.IO.Path]::GetTempFileName()
    $output = ''
    $exitCode = 1
    try {
        $proc = Start-Process -FilePath $Exe -ArgumentList $Arguments `
            -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput $outFile -RedirectStandardError $errFile
        $exitCode = $proc.ExitCode
        $output = ((Get-Content $outFile -Raw -ErrorAction SilentlyContinue) + "`n" +
                   (Get-Content $errFile -Raw -ErrorAction SilentlyContinue)).Trim()
    } catch {
        $output = $_.Exception.Message
    } finally {
        Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue
    }
    return [pscustomobject]@{ ExitCode = $exitCode; Output = $output }
}

function Invoke-LlamaBenchProbe([string]$BenchExe) {
    if (-not (Test-Path $BenchExe)) {
        return [pscustomobject]@{ Success = $false; ExitCode = $null; Output = (T 'core.exe_missing' 'llama-bench.exe'); DeviceLine = $null }
    }

    $bench = Invoke-ExeProbe $BenchExe '--list-devices'
    $backendsLoaded = $bench.Output -match 'load_backend|ggml_cuda_init|Device \d+:'
    $deviceLine = ($bench.Output -split "`r?`n" | Where-Object { $_ -match 'Device \d+:' } | Select-Object -First 1)
    if (-not ($bench.ExitCode -eq 0 -or $backendsLoaded)) {
        return [pscustomobject]@{ Success = $false; ExitCode = $bench.ExitCode; Output = "llama-bench: $($bench.Output)"; DeviceLine = $null }
    }

    # Auch llama-server muss starten: Dauerlast-, Endpoint- und Stresstests brauchen
    # ihn. Ein Build, dessen llama-server abstuerzt, loest ebenfalls den Fallback aus.
    $serverExe = Join-Path (Split-Path -Parent $BenchExe) 'llama-server.exe'
    if (-not (Test-Path $serverExe)) {
        return [pscustomobject]@{ Success = $false; ExitCode = $null; Output = (T 'core.exe_missing' 'llama-server.exe'); DeviceLine = $null }
    }
    $server = Invoke-ExeProbe $serverExe '--version'
    if ($server.ExitCode -ne 0) {
        return [pscustomobject]@{ Success = $false; ExitCode = $server.ExitCode; Output = "llama-server: $($server.Output)"; DeviceLine = $null }
    }

    return [pscustomobject]@{
        Success = $true
        ExitCode = 0
        Output = "llama-bench:`n$($bench.Output)`n`nllama-server --version:`n$($server.Output)"
        DeviceLine = $deviceLine
    }
}

function Expand-LlamaPackage([string]$Zip, [string]$Destination) {
    # $ProgressPreference des Aufrufers gilt im Modul nicht; der Fortschrittsbalken
    # von Expand-Archive macht Windows PowerShell 5.1 sehr langsam.
    $ProgressPreference = 'SilentlyContinue'
    Expand-Archive -Path $Zip -DestinationPath $Destination -Force
    # Manche Pakete liegen in einem Unterordner - die Programme muessen oben liegen,
    # damit die CUDA-Runtime-DLLs daneben gefunden werden.
    if (-not (Test-Path (Join-Path $Destination 'llama-bench.exe'))) {
        $bench = Get-ChildItem -Path $Destination -Filter 'llama-bench.exe' -Recurse -File | Select-Object -First 1
        if ($bench) {
            Get-ChildItem -Path $bench.Directory.FullName -Force | ForEach-Object {
                Copy-Item $_.FullName -Destination $Destination -Recurse -Force
            }
        }
    }
}

function Install-LlamaFromCandidates {
    # Probiert die Kandidaten der Reihe nach: herunterladen, in einen
    # Staging-Ordner entpacken, Startprobe. Der erste lauffaehige Build wird
    # nach $LlamaDir verschoben. Download/Probe sind fuer Tests ersetzbar.
    param(
        [object[]]$Candidates,
        [string]$LlamaDir,
        [string]$ProbeLog,
        [scriptblock]$Downloader,
        [scriptblock]$Prober
    )
    if (-not $Downloader) { $Downloader = { param($Url, $OutFile, $Label) Invoke-UiDownload $Url $OutFile $Label } }
    if (-not $Prober) { $Prober = { param($BenchExe) Invoke-LlamaBenchProbe $BenchExe } }

    $parent = Split-Path -Parent $LlamaDir
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    if ($ProbeLog) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ProbeLog) | Out-Null
        Set-Content -Path $ProbeLog -Value "llama.cpp start probes $(Get-Date -Format o)" -Encoding UTF8
    }
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('llmbench-llama-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    $attempts = @()

    try {
        for ($i = 0; $i -lt $Candidates.Count; $i++) {
            $candidate = $Candidates[$i]
            if ($i -gt 0) { Write-UiStep (T 'core.trying_candidate' $candidate.Backend) }
            # Staging neben dem Zielordner: gleiches Laufwerk, damit Move-Item klappt.
            $staging = Join-Path $parent ".llama-staging-$i"
            Remove-Item -Recurse -Force $staging -ErrorAction SilentlyContinue
            New-Item -ItemType Directory -Force -Path $staging | Out-Null

            try {
                foreach ($asset in @($candidate.MainAsset, $candidate.RuntimeAsset)) {
                    if (-not $asset) { continue }
                    $zip = Join-Path $tmp ([string]$asset.name)
                    if (-not (Test-Path $zip)) { & $Downloader ([string]$asset.browser_download_url) $zip ([string]$asset.name) }
                    Expand-LlamaPackage $zip $staging
                }
                foreach ($exe in 'llama-bench.exe', 'llama-server.exe') {
                    if (-not (Test-Path (Join-Path $staging $exe))) { throw (T 'core.exe_missing' $exe) }
                }
                $probe = & $Prober (Join-Path $staging 'llama-bench.exe')
            } catch {
                $probe = [pscustomobject]@{ Success = $false; ExitCode = $null; Output = $_.Exception.Message; DeviceLine = $null }
            }

            if ($ProbeLog) {
                Add-Content -Path $ProbeLog -Encoding UTF8 -Value @(
                    '', "=== $($candidate.Backend) ===",
                    $(if ($probe.Success) { 'ok' } else { "exit: $($probe.ExitCode) ($(Format-LlamaExitCode $probe.ExitCode))" }),
                    [string]$probe.Output
                )
            }

            if ($probe.Success) {
                if (Test-Path $LlamaDir) { Remove-Item -Recurse -Force $LlamaDir }
                Move-Item -Path $staging -Destination $LlamaDir
                return [pscustomobject]@{ Candidate = $candidate; Probe = $probe; Attempts = $attempts }
            }

            $reason = if ($null -ne $probe.ExitCode) { Format-LlamaExitCode $probe.ExitCode } else { [string]$probe.Output }
            $attempts += [pscustomobject]@{ Backend = $candidate.Backend; Reason = $reason }
            Write-UiWarn (T 'core.candidate_failed' $candidate.Backend $reason)
            Remove-Item -Recurse -Force $staging -ErrorAction SilentlyContinue
        }
    } finally {
        Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    }

    $summary = ($attempts | ForEach-Object { "  - $($_.Backend): $($_.Reason)" }) -join "`n"
    throw ((T 'core.all_candidates_failed' $ProbeLog) + "`n" + $summary)
}

Export-ModuleMember -Function ConvertTo-LlamaVersion, Get-NvidiaInfo, Get-LlamaBuildPreference, Get-LlamaPackageCandidates,
    Select-LlamaRelease, Format-LlamaExitCode, Invoke-LlamaBenchProbe, Install-LlamaFromCandidates
