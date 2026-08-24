[CmdletBinding()]
param(
    [string]$LlamaCppTag = "",
    [switch]$ForceUpdateLlamaCpp
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Root = Split-Path -Parent $PSScriptRoot
$RuntimeRoot = Join-Path $Root ".runtime"
$ToolsDir = Join-Path $Root "tools"
$LlamaDir = Join-Path $ToolsDir "llama.cpp"
$StateFile = Join-Path $LlamaDir ".llama-build.json"
$PinFile = Join-Path $Root "llama-cpp-version.txt"
$PythonPathFile = Join-Path $RuntimeRoot "python-path.txt"
$BuildToolsVenv = Join-Path $RuntimeRoot "build-tools"
$CacheDir = Join-Path $RuntimeRoot "cache"
$SourceBase = Join-Path $RuntimeRoot "llama-source"
$BuildBase = Join-Path $RuntimeRoot "llama-build"
$DiagScript = Join-Path $PSScriptRoot "DIAGNOSE_LLAMA_CRASH.ps1"

New-Item -ItemType Directory -Force -Path $RuntimeRoot, $CacheDir, $SourceBase, $BuildBase, $ToolsDir | Out-Null

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "=== $Text ===" -ForegroundColor Cyan
}

function Get-PythonExe {
    if (Test-Path $PythonPathFile) {
        $p = (Get-Content $PythonPathFile -Raw).Trim()
        if ($p -and (Test-Path $p)) { return $p }
    }
    foreach ($name in @("python.exe", "python")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    throw "Python wurde vom Bootstrap nicht bereitgestellt."
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

    $name = (& $cmd.Source --query-gpu=name --format=csv,noheader 2>$null | Select-Object -First 1)
    $driver = (& $cmd.Source --query-gpu=driver_version --format=csv,noheader 2>$null | Select-Object -First 1)
    $cap = (& $cmd.Source --query-gpu=compute_cap --format=csv,noheader 2>$null | Select-Object -First 1)
    if ($name) { $name = $name.ToString().Trim() }
    if ($driver) { $driver = $driver.ToString().Trim() }
    if ($cap) { $cap = $cap.ToString().Trim() }

    if (-not $cap -and $name -match 'Blackwell') { $cap = "12.0" }

    $arch = $null
    if ($cap -match '^([0-9]+)\.([0-9]+)$') {
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        if ($major -ge 12) { $arch = ("{0}{1}a-real" -f $major, $minor) }
        else { $arch = ("{0}{1}-real" -f $major, $minor) }
    }

    return [pscustomobject]@{
        Command = $cmd.Source
        Name = $name
        Driver = $driver
        ComputeCapability = $cap
        CMakeArchitecture = $arch
        IsBlackwell = [bool](($cap -match '^12\.') -or ($name -match 'Blackwell'))
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
        return [pscustomobject]@{
            Ok = ($proc.ExitCode -eq 0)
            ExitCode = $proc.ExitCode
            Output = (($stdout + "`n" + $stderr).Trim())
        }
    } catch {
        return [pscustomobject]@{ Ok = $false; ExitCode = $null; Output = $_.Exception.Message }
    } finally {
        Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue
    }
}

function Add-ToPath([string]$Path) {
    if (-not $Path -or -not (Test-Path $Path)) { return }
    $parts = @($env:PATH -split ';')
    if (-not ($parts | Where-Object { $_ -ieq $Path })) {
        $env:PATH = "$Path;$env:PATH"
    }
}

function Test-ExistingSourceBuild {
    if ($ForceUpdateLlamaCpp) { return $false }
    $bench = Join-Path $LlamaDir "llama-bench.exe"
    $server = Join-Path $LlamaDir "llama-server.exe"
    if (-not (Test-Path $bench) -or -not (Test-Path $server) -or -not (Test-Path $StateFile)) { return $false }

    try { $state = Get-Content $StateFile -Raw | ConvertFrom-Json } catch { return $false }
    if ($state.build_kind -ne "source") { return $false }

    if ($state.cuda_root) {
        $cudaBin = Join-Path ([string]$state.cuda_root) "bin"
        Add-ToPath $cudaBin
        $env:CUDA_PATH = [string]$state.cuda_root
    }
    if ($state.cuda_workaround -eq "GGML_CUDA_PDL=0") { $env:GGML_CUDA_PDL = "0" }

    $probe = Invoke-LlamaProbe $bench
    if (-not $probe.Ok) {
        Write-Warning "Vorhandener Source-Build ist nicht mehr startbar (Exitcode $($probe.ExitCode)). Er wird neu gebaut."
        return $false
    }

    Write-Host "llama.cpp Source-Build ist bereits vorhanden und startbar." -ForegroundColor Green
    Write-Host "Build: $($state.source_ref), CUDA $($state.cuda_toolkit), Architektur $($state.cuda_architecture)"
    return $true
}

function Ensure-CMakeAndNinja {
    Write-Step "CMake und Ninja"
    $python = Get-PythonExe
    $venvPython = Join-Path $BuildToolsVenv "Scripts\python.exe"
    $cmake = Join-Path $BuildToolsVenv "Scripts\cmake.exe"
    $ninja = Join-Path $BuildToolsVenv "Scripts\ninja.exe"

    if (-not (Test-Path $venvPython)) {
        Write-Host "Erstelle projektlokale Build-Tool-Umgebung..."
        & $python -m venv $BuildToolsVenv
        if ($LASTEXITCODE -ne 0) { throw "Build-Tool-Venv konnte nicht erstellt werden." }
    }

    if (-not (Test-Path $cmake) -or -not (Test-Path $ninja)) {
        Write-Host "Installiere CMake und Ninja projektlokal..."
        & $venvPython -m pip install --disable-pip-version-check --upgrade "cmake>=3.31.8" "ninja>=1.11"
        if ($LASTEXITCODE -ne 0) { throw "CMake/Ninja konnten nicht installiert werden." }
    }

    Write-Host (& $cmake --version | Select-Object -First 1)
    Write-Host (& $ninja --version | Select-Object -First 1)
    return [pscustomobject]@{ CMake = $cmake; Ninja = $ninja; Python = $venvPython }
}

function Get-VsInstallation {
    $vswhereCandidates = @(
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe",
        "$env:ProgramFiles\Microsoft Visual Studio\Installer\vswhere.exe"
    )
    foreach ($vswhere in $vswhereCandidates) {
        if (-not $vswhere -or -not (Test-Path $vswhere)) { continue }
        $path = (& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null | Select-Object -First 1)
        if ($path) {
            $path = $path.ToString().Trim()
            $vcvars = Join-Path $path "VC\Auxiliary\Build\vcvars64.bat"
            if (Test-Path $vcvars) { return [pscustomobject]@{ Root = $path; VcVars = $vcvars } }
        }
    }

    $roots = @(
        "$env:ProgramFiles\Microsoft Visual Studio",
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio"
    )
    foreach ($base in $roots) {
        if (-not $base -or -not (Test-Path $base)) { continue }
        $vcvars = Get-ChildItem -Path $base -Filter "vcvars64.bat" -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($vcvars) {
            $root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $vcvars.FullName)))
            return [pscustomobject]@{ Root = $root; VcVars = $vcvars.FullName }
        }
    }
    return $null
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Ensure-VisualCppBuildTools {
    Write-Step "Visual C++ Build Tools"
    $vs = Get-VsInstallation
    if (-not $vs) {
        if (-not (Test-IsAdministrator)) {
            throw "Visual C++ Build Tools fehlen. Starte START_BENCHMARK.bat einmal als Administrator, damit die Toolchain automatisch installiert werden kann."
        }

        $installer = Join-Path $CacheDir "vs_BuildTools.exe"
        if (-not (Test-Path $installer)) {
            Write-Host "Lade Microsoft Visual Studio Build Tools..."
            Invoke-WebRequest -Uri "https://aka.ms/vs/17/release/vs_BuildTools.exe" -OutFile $installer -UseBasicParsing
        }

        Write-Host "Installiere C++-Compiler und Windows SDK. Das kann einige Minuten dauern..." -ForegroundColor Yellow
        $args = @(
            "--quiet", "--wait", "--norestart", "--nocache",
            "--add", "Microsoft.VisualStudio.Workload.VCTools",
            "--includeRecommended"
        )
        $proc = Start-Process -FilePath $installer -ArgumentList $args -Wait -PassThru
        if ($proc.ExitCode -ne 0 -and $proc.ExitCode -ne 3010) {
            throw "Visual Studio Build Tools Installation fehlgeschlagen (Exitcode $($proc.ExitCode))."
        }
        $vs = Get-VsInstallation
        if (-not $vs) { throw "Visual C++ Build Tools wurden installiert, aber vcvars64.bat wurde nicht gefunden." }
    }

    Write-Host "MSVC Toolchain: $($vs.Root)"
    return $vs
}

function Import-VsEnvironment([string]$VcVars) {
    $commandLine = "`"$VcVars`" >nul && set"
    $lines = & $env:ComSpec /s /c $commandLine
    if ($LASTEXITCODE -ne 0) { throw "Visual-Studio-Entwicklungsumgebung konnte nicht geladen werden." }

    foreach ($line in $lines) {
        if ($line -match '^([^=]+)=(.*)$') {
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], "Process")
        }
    }
    if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
        throw "cl.exe wurde nach vcvars64.bat nicht gefunden."
    }
    $clVersion = (& cl.exe 2>&1 | Select-Object -First 1)
    if ($clVersion) { Write-Host $clVersion }
}

function Get-CudaToolkits {
    $roots = New-Object System.Collections.Generic.List[string]
    if ($env:CUDA_PATH) { $roots.Add($env:CUDA_PATH) }
    $defaultRoot = Join-Path $env:ProgramFiles "NVIDIA GPU Computing Toolkit\CUDA"
    if (Test-Path $defaultRoot) {
        Get-ChildItem -Path $defaultRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object { $roots.Add($_.FullName) }
    }

    $seen = @{}
    $result = @()
    foreach ($rootPath in $roots) {
        if (-not $rootPath) { continue }
        $key = $rootPath.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true

        $nvcc = Join-Path $rootPath "bin\nvcc.exe"
        if (-not (Test-Path $nvcc)) { continue }
        $text = (& $nvcc --version 2>&1 | Out-String)
        if ($text -notmatch 'release\s+([0-9]+\.[0-9]+)') { continue }
        try { $version = [version]$Matches[1] } catch { continue }
        $result += [pscustomobject]@{ Root = $rootPath; Nvcc = $nvcc; Version = $version }
    }
    return @($result)
}

function Install-Cuda128Toolkit {
    if (-not (Test-IsAdministrator)) {
        throw "CUDA Toolkit 12.8 fehlt. Starte START_BENCHMARK.bat einmal als Administrator, damit CUDA 12.8 automatisch installiert werden kann."
    }

    Write-Step "CUDA Toolkit 12.8 fuer Blackwell"
    $installer = Join-Path $CacheDir "cuda_12.8.1_572.61_windows.exe"
    $url = "https://developer.download.nvidia.com/compute/cuda/12.8.1/local_installers/cuda_12.8.1_572.61_windows.exe"

    if (-not (Test-Path $installer)) {
        Write-Host "Lade CUDA Toolkit 12.8.1 von NVIDIA. Der Download ist gross und kann dauern..." -ForegroundColor Yellow
        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($curl) {
            & $curl.Source -L --fail --retry 3 -o $installer $url
            if ($LASTEXITCODE -ne 0) { throw "CUDA-12.8-Download fehlgeschlagen." }
        } else {
            Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
        }
    }

    Write-Host "Installiere nur CUDA-Toolkit-Komponenten; der NVIDIA-Grafiktreiber wird NICHT ersetzt." -ForegroundColor Yellow
    $components = @(
        "-n", "-s",
        "nvcc_12.8", "cudart_12.8",
        "cublas_12.8", "cublas_dev_12.8",
        "nvrtc_12.8", "nvrtc_dev_12.8",
        "nvjitlink_12.8", "thrust_12.8",
        "visual_studio_integration_12.8"
    )
    $proc = Start-Process -FilePath $installer -ArgumentList $components -Wait -PassThru
    if ($proc.ExitCode -ne 0 -and $proc.ExitCode -ne 3010) {
        throw "CUDA Toolkit 12.8 Installation fehlgeschlagen (Exitcode $($proc.ExitCode))."
    }
}

function Select-CudaToolkit($Nvidia) {
    $kits = @(Get-CudaToolkits)

    if ($Nvidia -and $Nvidia.IsBlackwell) {
        # Blackwell (sm_120) braucht laut llama.cpp mindestens CUDA 12.8.
        # 12.8/12.9 werden bewusst vor 13.x bevorzugt, weil sie fuer sm_120
        # die derzeit konservativste native Windows-Toolchain darstellen.
        $preferred = @($kits | Where-Object { $_.Version.Major -eq 12 -and $_.Version -ge [version]"12.8" } | Sort-Object Version -Descending)
        if ($preferred.Count -gt 0) { return $preferred[0] }

        Write-Host "Kein CUDA-12.8/12.9-Toolkit fuer Blackwell gefunden. CUDA 12.8.1 wird eingerichtet."
        Install-Cuda128Toolkit
        $kits = @(Get-CudaToolkits)
        $preferred = @($kits | Where-Object { $_.Version.Major -eq 12 -and $_.Version -ge [version]"12.8" } | Sort-Object Version -Descending)
        if ($preferred.Count -gt 0) { return $preferred[0] }

        # Falls eine Installation durch lokale Richtlinien nicht moeglich war,
        # ist ein vorhandenes >=13-Toolkit immer noch besser als gar kein nvcc.
        $newer = @($kits | Where-Object { $_.Version.Major -ge 13 } | Sort-Object Version -Descending)
        if ($newer.Count -gt 0) { return $newer[0] }
        throw "Fuer Blackwell wurde kein CUDA Toolkit >=12.8 mit nvcc gefunden."
    }

    if ($kits.Count -eq 0) {
        throw "CUDA Toolkit mit nvcc wurde nicht gefunden. Installiere ein zur NVIDIA-GPU passendes CUDA Toolkit und starte erneut."
    }
    return ($kits | Sort-Object Version -Descending | Select-Object -First 1)
}

function Resolve-SourceRef {
    $pin = Get-PinnedTag
    if ($pin) {
        if ($pin -notmatch '^[A-Za-z0-9._-]+$') { throw "Ungueltige llama.cpp-Source-Kennung '$pin'." }
        Write-Host "Festgelegter llama.cpp-Source-Stand: $pin"
        return $pin
    }

    try {
        $atom = Invoke-WebRequest -Uri "https://github.com/ggml-org/llama.cpp/releases.atom" -UseBasicParsing -TimeoutSec 20
        $matches = [regex]::Matches([string]$atom.Content, '/releases/tag/(b[0-9]+)')
        $builds = @()
        foreach ($m in $matches) {
            $tag = $m.Groups[1].Value
            if ($tag -match '^b([0-9]+)$') { $builds += [pscustomobject]@{ Tag = $tag; Number = [int64]$Matches[1] } }
        }
        if ($builds.Count -gt 0) {
            return (($builds | Sort-Object Number -Descending | Select-Object -First 1).Tag)
        }
    } catch {
        Write-Warning "Release-Feed nicht erreichbar: $($_.Exception.Message)"
    }

    Write-Warning "Kein Release-Tag ermittelbar; es wird der aktuelle master-Quellcode verwendet."
    return "master"
}

function Get-SourceTree([string]$Ref) {
    Write-Step "llama.cpp Quellcode"
    $safeRef = $Ref -replace '[^A-Za-z0-9._-]', '_'
    $zip = Join-Path $CacheDir "llama-source-$safeRef.zip"
    $sourceDir = Join-Path $SourceBase $safeRef

    if ($ForceUpdateLlamaCpp -and (Test-Path $zip)) { Remove-Item $zip -Force }
    if ($ForceUpdateLlamaCpp -and (Test-Path $sourceDir)) { Remove-Item $sourceDir -Recurse -Force }

    if (-not (Test-Path $zip)) {
        if ($Ref -eq "master") {
            $url = "https://codeload.github.com/ggml-org/llama.cpp/zip/refs/heads/master"
        } else {
            $url = "https://codeload.github.com/ggml-org/llama.cpp/zip/refs/tags/$Ref"
        }
        Write-Host "Lade offiziellen llama.cpp-Quellcode ($Ref)..."
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    }

    if (-not (Test-Path $sourceDir)) {
        $tmpExtract = Join-Path $SourceBase ("extract-" + [guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Force -Path $tmpExtract | Out-Null
        try {
            Expand-Archive -Path $zip -DestinationPath $tmpExtract -Force
            $tree = Get-ChildItem -Path $tmpExtract -Directory | Where-Object { Test-Path (Join-Path $_.FullName "CMakeLists.txt") } | Select-Object -First 1
            if (-not $tree) { throw "CMakeLists.txt wurde im llama.cpp-Archiv nicht gefunden." }
            Move-Item -Path $tree.FullName -Destination $sourceDir
        } finally {
            Remove-Item $tmpExtract -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    $hash = (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    return [pscustomobject]@{ Path = $sourceDir; Zip = $zip; Sha256 = $hash }
}

function Copy-BuildOutput([string]$BuildDir) {
    $bench = Get-ChildItem -Path $BuildDir -Filter "llama-bench.exe" -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
    $server = Get-ChildItem -Path $BuildDir -Filter "llama-server.exe" -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $bench -or -not $server) { throw "Build war erfolgreich, aber llama-bench.exe/llama-server.exe wurden nicht gefunden." }

    $binDir = $bench.Directory.FullName
    if ($server.Directory.FullName -ne $binDir) { throw "llama-bench und llama-server liegen in unterschiedlichen Build-Verzeichnissen." }

    if (Test-Path $LlamaDir) { Remove-Item $LlamaDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $LlamaDir | Out-Null
    Get-ChildItem -Path $binDir -Force | ForEach-Object {
        Copy-Item $_.FullName -Destination $LlamaDir -Recurse -Force
    }
}

function Invoke-SourceBuild($Tools, $Vs, $Cuda, $Nvidia, [string]$Ref, $Source, [switch]$Conservative) {
    Import-VsEnvironment $Vs.VcVars
    $env:CUDA_PATH = $Cuda.Root
    Add-ToPath (Join-Path $Cuda.Root "bin")

    $profile = if ($Conservative) { "conservative" } else { "optimized" }
    $safeRef = $Ref -replace '[^A-Za-z0-9._-]', '_'
    $safeCuda = $Cuda.Version.ToString() -replace '\.', '_'
    $buildDir = Join-Path $BuildBase ("$safeRef-cuda-$safeCuda-$profile")
    if (Test-Path $buildDir) { Remove-Item $buildDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $buildDir | Out-Null

    Write-Step "llama.cpp wird lokal kompiliert ($profile)"
    Write-Host "Source:        $Ref"
    Write-Host "GPU:           $($Nvidia.Name)"
    Write-Host "Compute Cap.:  $($Nvidia.ComputeCapability)"
    Write-Host "CUDA Toolkit:  $($Cuda.Version)"
    Write-Host "nvcc:          $($Cuda.Nvcc)"
    if ($Nvidia.CMakeArchitecture) { Write-Host "CUDA Arch.:     $($Nvidia.CMakeArchitecture)" }
    Write-Host "Build-Ordner:  $buildDir"
    Write-Host "Der erste CUDA-Build kann mehrere Minuten dauern." -ForegroundColor Yellow

    $configure = @(
        "-S", $Source.Path,
        "-B", $buildDir,
        "-G", "Ninja",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_MAKE_PROGRAM=$($Tools.Ninja)",
        "-DCMAKE_CUDA_COMPILER=$($Cuda.Nvcc)",
        "-DGGML_CUDA=ON",
        "-DGGML_NATIVE=OFF",
        "-DBUILD_SHARED_LIBS=ON",
        "-DLLAMA_BUILD_TESTS=OFF",
        "-DLLAMA_BUILD_EXAMPLES=OFF",
        "-DLLAMA_BUILD_TOOLS=ON",
        "-DLLAMA_BUILD_SERVER=ON",
        "-DLLAMA_BUILD_UI=OFF",
        "-DLLAMA_BUILD_APP=OFF",
        "-DLLAMA_OPENSSL=OFF"
    )
    if ($Nvidia.CMakeArchitecture) {
        $configure += "-DCMAKE_CUDA_ARCHITECTURES=$($Nvidia.CMakeArchitecture)"
    }
    if ($Conservative) {
        $configure += "-DGGML_CUDA_GRAPHS=OFF"
        $configure += "-DGGML_CUDA_NO_VMM=ON"
        $configure += "-DGGML_CUDA_FA=OFF"
    }

    & $Tools.CMake @configure
    if ($LASTEXITCODE -ne 0) { throw "CMake-Konfiguration fuer llama.cpp ist fehlgeschlagen." }

    $jobs = [Math]::Max(1, [Environment]::ProcessorCount)
    & $Tools.CMake --build $buildDir --config Release --target llama-bench llama-server --parallel $jobs
    if ($LASTEXITCODE -ne 0) { throw "llama.cpp-Kompilierung ist fehlgeschlagen." }

    Copy-BuildOutput $buildDir
    $benchExe = Join-Path $LlamaDir "llama-bench.exe"

    Remove-Item Env:\GGML_CUDA_PDL -ErrorAction SilentlyContinue
    $probe = Invoke-LlamaProbe $benchExe
    $workaround = $null
    if (-not $probe.Ok -and $Nvidia.IsBlackwell) {
        Write-Warning "Source-Build startet noch nicht. Teste GGML_CUDA_PDL=0..."
        $env:GGML_CUDA_PDL = "0"
        $probe = Invoke-LlamaProbe $benchExe
        if ($probe.Ok) { $workaround = "GGML_CUDA_PDL=0" }
    }

    return [pscustomobject]@{
        Ok = $probe.Ok
        ExitCode = $probe.ExitCode
        Output = $probe.Output
        Workaround = $workaround
        BuildDir = $buildDir
        Profile = $profile
        ConfigureArgs = $configure
    }
}

if (Test-ExistingSourceBuild) { exit 0 }

$nvidia = Get-NvidiaInfo
if (-not $nvidia) {
    throw "Keine NVIDIA-GPU über nvidia-smi erkannt. Der Windows-Benchmark erwartet fuer den CUDA-Source-Build eine NVIDIA-GPU."
}

Write-Step "llama.cpp Source-Build Setup"
Write-Host "GPU: $($nvidia.Name)"
Write-Host "Treiber: $($nvidia.Driver)"
Write-Host "Compute Capability: $($nvidia.ComputeCapability)"
if ($nvidia.IsBlackwell) {
    Write-Host "Blackwell erkannt: llama.cpp wird nativ fuer $($nvidia.CMakeArchitecture) mit CUDA >=12.8 gebaut." -ForegroundColor Green
}

$tools = Ensure-CMakeAndNinja
$vs = Ensure-VisualCppBuildTools
$cuda = Select-CudaToolkit $nvidia
$ref = Resolve-SourceRef
$source = Get-SourceTree $ref

$result = $null
try {
    $result = Invoke-SourceBuild $tools $vs $cuda $nvidia $ref $source
    if (-not $result.Ok) {
        Write-Warning "Optimierter Source-Build ist nicht startbar (Exitcode $($result.ExitCode)). Baue konservatives CUDA-Profil..."
        $result = Invoke-SourceBuild $tools $vs $cuda $nvidia $ref $source -Conservative
    }

    if (-not $result.Ok) {
        if (Test-Path $DiagScript) {
            try { & $DiagScript -LlamaDir $LlamaDir -ExitCode $result.ExitCode -Backend "source-cuda-$($cuda.Version)" | Out-Null } catch { }
        }
        throw "Der lokal kompilierte llama.cpp-Build konnte nicht gestartet werden (Exitcode $($result.ExitCode)). Ausgabe: $($result.Output)"
    }

    if ($result.Workaround -eq "GGML_CUDA_PDL=0") { $env:GGML_CUDA_PDL = "0" }

    $cmakeVersion = (& $tools.CMake --version | Select-Object -First 1)
    $ninjaVersion = (& $tools.Ninja --version | Select-Object -First 1)
    $clVersion = (& cl.exe 2>&1 | Select-Object -First 1)

    $state = [ordered]@{
        build_kind = "source"
        source_ref = $ref
        source_archive_sha256 = $source.Sha256
        backend = "cuda-source"
        cuda_toolkit = $cuda.Version.ToString()
        cuda_root = $cuda.Root
        nvcc = $cuda.Nvcc
        cuda_architecture = $nvidia.CMakeArchitecture
        compute_capability = $nvidia.ComputeCapability
        gpu_name = $nvidia.Name
        nvidia_driver = $nvidia.Driver
        build_profile = $result.Profile
        cuda_workaround = $result.Workaround
        cmake = $cmakeVersion
        ninja = $ninjaVersion
        compiler = $clVersion
        installed_at = (Get-Date).ToString("o")
    }
    $state | ConvertTo-Json -Depth 4 | Set-Content -Path $StateFile -Encoding UTF8

    $deviceLine = ($result.Output -split "`r?`n" | Where-Object { $_ -match 'Device|CUDA' } | Select-Object -First 1)
    Write-Host ""
    Write-Host "llama.cpp wurde erfolgreich aus dem Quellcode kompiliert." -ForegroundColor Green
    Write-Host "Source: $ref | CUDA $($cuda.Version) | $($nvidia.CMakeArchitecture) | Profil $($result.Profile)" -ForegroundColor Green
    if ($result.Workaround) { Write-Host "Aktiver Runtime-Workaround: $($result.Workaround)" -ForegroundColor Yellow }
    if ($deviceLine) { Write-Host $deviceLine.Trim() -ForegroundColor Green }
    exit 0
} catch {
    Write-Host ""
    Write-Host "llama.cpp Source-Build fehlgeschlagen: $($_.Exception.Message)" -ForegroundColor Red
    throw
}
