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
$PythonPathFile = Join-Path $RuntimeRoot "python-path.txt"
$BuildToolsVenv = Join-Path $RuntimeRoot "build-tools"
$PreparedRefFile = Join-Path $RuntimeRoot "llama-source-ref.txt"
$PreparedPathFile = Join-Path $RuntimeRoot "llama-source-path.txt"
$PrepareSource = Join-Path $PSScriptRoot "PREPARE_LLAMA_SOURCE.py"
$CacheDir = Join-Path $RuntimeRoot "cache"
$LogRoot = Join-Path $RuntimeRoot "build-logs"
$DiagScript = Join-Path $PSScriptRoot "DIAGNOSE_LLAMA_CRASH.ps1"

if ($env:LLMBENCH_WORK_ROOT) {
    $WorkRoot = $env:LLMBENCH_WORK_ROOT
} elseif ($env:LOCALAPPDATA) {
    $WorkRoot = Join-Path $env:LOCALAPPDATA "LLMBench"
} else {
    $WorkRoot = Join-Path ([System.IO.Path]::GetTempPath()) "LLMBench"
}
$SourceRoot = Join-Path $WorkRoot "src"
$BuildRoot = Join-Path $WorkRoot "build"

New-Item -ItemType Directory -Force -Path $RuntimeRoot,$ToolsDir,$CacheDir,$LogRoot,$WorkRoot,$SourceRoot,$BuildRoot | Out-Null

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "=== $Text ===" -ForegroundColor Cyan
}

function Add-ToPath([string]$Dir) {
    if (-not $Dir -or -not (Test-Path $Dir)) { return }
    if (-not (($env:PATH -split ';') | Where-Object { $_ -ieq $Dir })) {
        $env:PATH = "$Dir;$env:PATH"
    }
}

function Invoke-NativeLogged {
    param(
        [Parameter(Mandatory=$true)][string]$Exe,
        [Parameter(Mandatory=$true)][object[]]$Arguments,
        [Parameter(Mandatory=$true)][string]$LogFile
    )

    $previousErrorAction = $ErrorActionPreference
    $rc = 1
    try {
        $ErrorActionPreference = "Continue"
        & $Exe @Arguments 2>&1 | Tee-Object -FilePath $LogFile
        $rc = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
    return $rc
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-PythonExe {
    if (Test-Path $PythonPathFile) {
        $p = (Get-Content $PythonPathFile -Raw).Trim()
        if ($p -and (Test-Path $p)) { return $p }
    }
    foreach ($name in @("py.exe","python.exe","python")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        try {
            if ($name -eq "py.exe") {
                $p = (& $cmd.Source -3 -c "import sys; print(sys.executable)" 2>$null | Select-Object -Last 1)
                if ($LASTEXITCODE -eq 0 -and $p -and (Test-Path $p.Trim())) { return $p.Trim() }
            } else {
                return $cmd.Source
            }
        } catch { }
    }
    throw "Python wurde vom Bootstrap nicht bereitgestellt."
}

function Ensure-CMakeNinja {
    Write-Step "Projektlokale Build-Tools"
    $python = Get-PythonExe
    $venvPython = Join-Path $BuildToolsVenv "Scripts\python.exe"
    $cmake = Join-Path $BuildToolsVenv "Scripts\cmake.exe"
    $ninja = Join-Path $BuildToolsVenv "Scripts\ninja.exe"

    if (-not (Test-Path $venvPython)) {
        Write-Host "Erstelle .runtime\build-tools ..."
        & $python -m venv $BuildToolsVenv
        if ($LASTEXITCODE -ne 0) { throw "Build-Tool-Venv konnte nicht erstellt werden." }
    }

    if (-not (Test-Path $cmake) -or -not (Test-Path $ninja)) {
        Write-Host "Installiere CMake >=3.31.10,<4 und Ninja projektlokal..."
        & $venvPython -m pip install --disable-pip-version-check --upgrade "cmake>=3.31.10,<4" "ninja>=1.11"
        if ($LASTEXITCODE -ne 0) { throw "CMake/Ninja konnten nicht installiert werden." }
    }

    Add-ToPath (Split-Path -Parent $cmake)
    Write-Host (& $cmake --version | Select-Object -First 1)
    Write-Host "Ninja $(& $ninja --version)"
    return [pscustomobject]@{ CMake=$cmake; Ninja=$ninja }
}

function Find-VisualStudio {
    $vswhereCandidates = @(
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe",
        "$env:ProgramFiles\Microsoft Visual Studio\Installer\vswhere.exe"
    )
    foreach ($vswhere in $vswhereCandidates) {
        if (-not $vswhere -or -not (Test-Path $vswhere)) { continue }
        $root = (& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null | Select-Object -First 1)
        if ($root) {
            $root = $root.ToString().Trim()
            $vcvars = Join-Path $root "VC\Auxiliary\Build\vcvars64.bat"
            if (Test-Path $vcvars) { return [pscustomobject]@{ Root=$root; VcVars=$vcvars } }
        }
    }

    foreach ($base in @("$env:ProgramFiles\Microsoft Visual Studio","${env:ProgramFiles(x86)}\Microsoft Visual Studio")) {
        if (-not $base -or -not (Test-Path $base)) { continue }
        $vcvars = Get-ChildItem -Path $base -Filter vcvars64.bat -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($vcvars) {
            return [pscustomobject]@{ Root=$vcvars.Directory.Parent.Parent.Parent.Parent.FullName; VcVars=$vcvars.FullName }
        }
    }
    return $null
}

function Ensure-VisualStudio {
    Write-Step "Visual C++ Build Tools"
    $vs = Find-VisualStudio
    if (-not $vs) {
        if (-not (Test-IsAdministrator)) {
            throw "Visual C++ Build Tools fehlen. START_BENCHMARK.bat muss fuer die automatische Erstinstallation als Administrator laufen."
        }
        $installer = Join-Path $CacheDir "vs_BuildTools.exe"
        if (-not (Test-Path $installer)) {
            Write-Host "Lade Visual Studio 2022 Build Tools..."
            Invoke-WebRequest -Uri "https://aka.ms/vs/17/release/vs_BuildTools.exe" -OutFile $installer -UseBasicParsing
        }
        Write-Host "Installiere MSVC + Windows SDK. Das kann einige Minuten dauern..." -ForegroundColor Yellow
        $args = @("--quiet","--wait","--norestart","--nocache","--add","Microsoft.VisualStudio.Workload.VCTools","--includeRecommended")
        $proc = Start-Process -FilePath $installer -ArgumentList $args -Wait -PassThru
        if ($proc.ExitCode -ne 0 -and $proc.ExitCode -ne 3010) {
            throw "Visual Studio Build Tools Installation fehlgeschlagen (Exitcode $($proc.ExitCode))."
        }
        $vs = Find-VisualStudio
        if (-not $vs) { throw "Visual C++ Build Tools wurden installiert, aber vcvars64.bat wurde nicht gefunden." }
    }
    Write-Host "Visual Studio: $($vs.Root)"
    return $vs
}

function Import-VsEnvironment([string]$VcVars) {
    $cmdLine = "`"$VcVars`" >nul && set"
    $lines = & $env:ComSpec /s /c $cmdLine
    if ($LASTEXITCODE -ne 0) { throw "vcvars64.bat konnte nicht ausgefuehrt werden." }
    foreach ($line in $lines) {
        if ($line -match '^([^=]+)=(.*)$') {
            [Environment]::SetEnvironmentVariable($Matches[1],$Matches[2],"Process")
        }
    }
    $cl = Get-Command cl.exe -ErrorAction SilentlyContinue
    if (-not $cl) { throw "cl.exe wurde nach vcvars64.bat nicht gefunden." }
    Write-Host "Host-Compiler: $($cl.Source)"
    return $cl.Source
}

function Get-NvidiaInfo {
    $smi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if (-not $smi) { return $null }

    $names = @(& $smi.Source --query-gpu=name --format=csv,noheader 2>$null | ForEach-Object { $_.ToString().Trim() } | Where-Object { $_ })
    $caps = @(& $smi.Source --query-gpu=compute_cap --format=csv,noheader 2>$null | ForEach-Object { $_.ToString().Trim() } | Where-Object { $_ -match '^\d+\.\d+$' })
    $driver = (& $smi.Source --query-gpu=driver_version --format=csv,noheader 2>$null | Select-Object -First 1)
    if ($driver) { $driver = $driver.ToString().Trim() }

    if ($caps.Count -eq 0 -and $names.Count -gt 0 -and (@($names | Where-Object { $_ -notmatch 'Blackwell' }).Count -eq 0)) {
        $caps = @("12.0")
    }

    $archs = New-Object System.Collections.Generic.List[string]
    foreach ($cap in ($caps | Select-Object -Unique)) {
        if ($cap -match '^(\d+)\.(\d+)$') {
            $maj = [int]$Matches[1]
            $min = [int]$Matches[2]
            if ($maj -ge 12) { $archs.Add(("{0}{1}a-real" -f $maj,$min)) }
            else { $archs.Add(("{0}{1}-real" -f $maj,$min)) }
        }
    }

    $isBlackwell = [bool](($caps | Where-Object { $_ -match '^12\.' }) -or ($names | Where-Object { $_ -match 'Blackwell' }))
    return [pscustomobject]@{
        Smi=$smi.Source
        Names=$names
        Driver=$driver
        Caps=$caps
        IsBlackwell=$isBlackwell
        Architectures=@($archs | Select-Object -Unique)
    }
}

function Add-CudaRootCandidate {
    param(
        [Parameter(Mandatory=$true)][AllowEmptyCollection()][System.Collections.Generic.List[string]]$List,
        [AllowNull()][AllowEmptyString()][string]$Path
    )
    if (-not $Path) { return }
    try {
        $full = [IO.Path]::GetFullPath($Path.Trim().TrimEnd('\'))
    } catch {
        return
    }
    if (Test-Path $full) { [void]$List.Add($full) }
}

function Get-CudaVersionFromRoot([string]$Root) {
    if (-not $Root) { return $null }

    $leaf = Split-Path $Root -Leaf
    if ($leaf -match '^v?(\d+)\.(\d+)$') {
        try { return [version]("{0}.{1}" -f $Matches[1],$Matches[2]) } catch { }
    }

    $versionJson = Join-Path $Root "version.json"
    if (Test-Path $versionJson) {
        try {
            $json = Get-Content $versionJson -Raw | ConvertFrom-Json
            $text = $null
            if ($json.cuda -and $json.cuda.version) { $text = [string]$json.cuda.version }
            elseif ($json.version) { $text = [string]$json.version }
            if ($text -and $text -match '^(\d+)\.(\d+)') {
                return [version]("{0}.{1}" -f $Matches[1],$Matches[2])
            }
        } catch { }
    }

    return $null
}

function Get-CudaToolkits {
    $roots = New-Object System.Collections.Generic.List[string]

    Add-CudaRootCandidate -List $roots -Path $env:CUDA_PATH
    foreach ($name in @("CUDA_PATH_V12_8","CUDA_PATH_V12_9","CUDA_PATH_V13_0","CUDA_PATH_V13_1","CUDA_PATH_V13_2","CUDA_PATH_V13_3")) {
        $value = [Environment]::GetEnvironmentVariable($name,"Process")
        if (-not $value) { $value = [Environment]::GetEnvironmentVariable($name,"Machine") }
        if (-not $value) { $value = [Environment]::GetEnvironmentVariable($name,"User") }
        Add-CudaRootCandidate -List $roots -Path $value
    }

    $programRoots = @($env:ProgramW6432,$env:ProgramFiles)
    foreach ($programRoot in ($programRoots | Where-Object { $_ } | Select-Object -Unique)) {
        $base = Join-Path $programRoot "NVIDIA GPU Computing Toolkit\CUDA"
        if (-not (Test-Path $base)) { continue }
        Get-ChildItem $base -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            Add-CudaRootCandidate -List $roots -Path $_.FullName
        }
    }

    try {
        $whereNvcc = @(& where.exe nvcc.exe 2>$null)
        foreach ($nvccPath in $whereNvcc) {
            if (-not $nvccPath) { continue }
            $binDir = Split-Path $nvccPath.Trim() -Parent
            $cudaRoot = Split-Path $binDir -Parent
            Add-CudaRootCandidate -List $roots -Path $cudaRoot
        }
    } catch { }

    foreach ($regPath in @(
        "HKLM:\SOFTWARE\NVIDIA Corporation\GPU Computing Toolkit\CUDA",
        "HKLM:\SOFTWARE\WOW6432Node\NVIDIA Corporation\GPU Computing Toolkit\CUDA"
    )) {
        if (-not (Test-Path $regPath)) { continue }
        try {
            $rootProps = Get-ItemProperty $regPath -ErrorAction SilentlyContinue
            if ($rootProps -and $rootProps.Path) { Add-CudaRootCandidate -List $roots -Path ([string]$rootProps.Path) }
            Get-ChildItem $regPath -ErrorAction SilentlyContinue | ForEach-Object {
                $props = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
                if ($props -and $props.InstallDir) { Add-CudaRootCandidate -List $roots -Path ([string]$props.InstallDir) }
                elseif ($props -and $props.Path) { Add-CudaRootCandidate -List $roots -Path ([string]$props.Path) }
            }
        } catch { }
    }

    foreach ($driveRoot in @($env:ProgramW6432,$env:ProgramFiles,"C:\Program Files")) {
        if (-not $driveRoot) { continue }
        Add-CudaRootCandidate -List $roots -Path (Join-Path $driveRoot "NVIDIA GPU Computing Toolkit\CUDA\v12.8")
    }

    $seen = @{}
    $kits = @()
    foreach ($root in $roots) {
        if (-not $root) { continue }
        $key = $root.ToLowerInvariant()
        if ($seen[$key]) { continue }
        $seen[$key] = $true

        $nvcc = Join-Path $root "bin\nvcc.exe"
        if (-not (Test-Path $nvcc)) { continue }

        $ver = Get-CudaVersionFromRoot $root
        if (-not $ver) {
            Write-Warning "CUDA Toolkit gefunden, Version aber nicht aus Pfad/version.json ermittelbar: $root"
            continue
        }

        $kits += [pscustomobject]@{ Root=$root; Nvcc=$nvcc; Version=$ver }
    }

    Write-Host ""
    Write-Host "CUDA Toolkit Erkennung:" -ForegroundColor Cyan
    if ($kits.Count -eq 0) {
        Write-Host "  Kein Toolkit mit bin\nvcc.exe gefunden." -ForegroundColor Yellow
    } else {
        foreach ($kit in ($kits | Sort-Object Version -Descending)) {
            Write-Host "  CUDA $($kit.Version) -> $($kit.Root)" -ForegroundColor Green
        }
    }

    return @($kits)
}

function Install-Cuda128 {
    if (-not (Test-IsAdministrator)) { throw "CUDA 12.8 fehlt und kann ohne Administratorrechte nicht automatisch installiert werden." }
    Write-Step "CUDA Toolkit 12.8.1"
    $installer = Join-Path $CacheDir "cuda_12.8.1_572.61_windows.exe"
    $url = "https://developer.download.nvidia.com/compute/cuda/12.8.1/local_installers/cuda_12.8.1_572.61_windows.exe"
    if (-not (Test-Path $installer)) {
        Write-Host "Lade CUDA Toolkit 12.8.1 von NVIDIA..." -ForegroundColor Yellow
        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($curl) {
            & $curl.Source -L --fail --retry 3 -o $installer $url
            if ($LASTEXITCODE -ne 0) { throw "CUDA-12.8-Download fehlgeschlagen." }
        } else {
            Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
        }
    }
    Write-Host "Installiere nur Toolkit-Komponenten; der Grafiktreiber bleibt unveraendert." -ForegroundColor Yellow
    $components = @("-s","nvcc_12.8","cudart_12.8","cublas_12.8","cublas_dev_12.8","nvrtc_12.8","nvrtc_dev_12.8","nvjitlink_12.8","thrust_12.8")
    $proc = Start-Process -FilePath $installer -ArgumentList $components -Wait -PassThru
    if ($proc.ExitCode -ne 0 -and $proc.ExitCode -ne 3010) {
        throw "CUDA Toolkit 12.8 Installation fehlgeschlagen (Exitcode $($proc.ExitCode))."
    }
}

function Select-Cuda($Nvidia) {
    $kits = @(Get-CudaToolkits)
    if ($Nvidia.IsBlackwell) {
        $preferred = @($kits | Where-Object { $_.Version.Major -eq 12 -and $_.Version -ge [version]"12.8" -and $_.Version -lt [version]"13.0" } | Sort-Object Version -Descending)
        if ($preferred.Count -gt 0) {
            $chosen = $preferred[0]
            $env:CUDA_PATH = $chosen.Root
            Add-ToPath (Join-Path $chosen.Root "bin")
            Write-Host "Verwende installiertes CUDA Toolkit $($chosen.Version): $($chosen.Root)" -ForegroundColor Green
            return $chosen
        }
        Install-Cuda128
        $kits = @(Get-CudaToolkits)
        $preferred = @($kits | Where-Object { $_.Version.Major -eq 12 -and $_.Version -ge [version]"12.8" -and $_.Version -lt [version]"13.0" } | Sort-Object Version -Descending)
        if ($preferred.Count -gt 0) {
            $chosen = $preferred[0]
            $env:CUDA_PATH = $chosen.Root
            Add-ToPath (Join-Path $chosen.Root "bin")
            return $chosen
        }
        throw "Blackwell erkannt, aber kein nutzbares CUDA Toolkit 12.8/12.9 mit bin\nvcc.exe gefunden."
    }
    if ($kits.Count -eq 0) { throw "Kein CUDA Toolkit mit bin\nvcc.exe gefunden." }
    $chosen = ($kits | Sort-Object Version -Descending | Select-Object -First 1)
    $env:CUDA_PATH = $chosen.Root
    Add-ToPath (Join-Path $chosen.Root "bin")
    return $chosen
}

function Ensure-PreparedSource([string]$Ref) {
    $python = Get-PythonExe
    $preparedRef = ""
    $preparedPath = ""
    if (Test-Path $PreparedRefFile) { $preparedRef = (Get-Content $PreparedRefFile -Raw).Trim() }
    if (Test-Path $PreparedPathFile) { $preparedPath = (Get-Content $PreparedPathFile -Raw).Trim() }
    if ($preparedRef -eq $Ref -and $preparedPath -and (Test-Path (Join-Path $preparedPath "CMakeLists.txt"))) {
        return [pscustomobject]@{ Path=$preparedPath; Ref=$Ref }
    }
    if (-not (Test-Path $PrepareSource)) { throw "PREPARE_LLAMA_SOURCE.py fehlt." }
    $args=@($PrepareSource,"--project-root",$Root,"--ref",$Ref)
    if ($ForceUpdateLlamaCpp) { $args += "--force" }
    & $python @args
    if ($LASTEXITCODE -ne 0) { throw "llama.cpp-Quellcode konnte nicht vorbereitet werden." }
    if (-not (Test-Path $PreparedPathFile)) { throw "Source-Preparer hat keinen Source-Pfad hinterlegt." }
    $preparedPath=(Get-Content $PreparedPathFile -Raw).Trim()
    if (-not $preparedPath -or -not (Test-Path (Join-Path $preparedPath "CMakeLists.txt"))) {
        throw "Vorbereiteter llama.cpp-Source-Pfad ist ungueltig: $preparedPath"
    }
    return [pscustomobject]@{ Path=$preparedPath; Ref=$Ref }
}

function Invoke-Probe([string]$Exe) {
    $o=[IO.Path]::GetTempFileName(); $e=[IO.Path]::GetTempFileName()
    try {
        $p=Start-Process $Exe -ArgumentList '--list-devices' -Wait -PassThru -NoNewWindow -RedirectStandardOutput $o -RedirectStandardError $e
        $text=((Get-Content $o -Raw -ErrorAction SilentlyContinue)+"`n"+(Get-Content $e -Raw -ErrorAction SilentlyContinue)).Trim()
        return [pscustomobject]@{Ok=($p.ExitCode -eq 0);ExitCode=$p.ExitCode;Output=$text}
    } catch { return [pscustomobject]@{Ok=$false;ExitCode=$null;Output=$_.Exception.Message} }
    finally { Remove-Item $o,$e -Force -ErrorAction SilentlyContinue }
}

function Copy-Binaries([string]$BuildDir) {
    $bench=Get-ChildItem $BuildDir -Filter llama-bench.exe -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
    $server=Get-ChildItem $BuildDir -Filter llama-server.exe -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $bench -or -not $server) { throw "Build beendet, aber llama-bench.exe/llama-server.exe fehlen." }
    if ($bench.Directory.FullName -ne $server.Directory.FullName) { throw "llama-bench und llama-server liegen nicht im selben Bin-Verzeichnis." }
    if (Test-Path $LlamaDir) { Remove-Item $LlamaDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $LlamaDir | Out-Null
    Get-ChildItem $bench.Directory.FullName -Force | ForEach-Object { Copy-Item $_.FullName $LlamaDir -Recurse -Force }
}

function Build-Llama($Tools,[string]$Cl,$Cuda,$Nvidia,[string]$Ref,$Source,[switch]$Conservative) {
    $profile=if($Conservative){'conservative'}else{'optimized'}
    $buildDir=Join-Path $BuildRoot ("$Ref-cuda-$($Cuda.Version.ToString().Replace('.','_'))-$profile")
    if (-not (Test-Path $buildDir)) {
        New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
        Write-Host "Neuer Build-Ordner: $buildDir"
    } else {
        Write-Host "Vorhandener Build-Ordner erkannt. Setze Build inkrementell fort: $buildDir" -ForegroundColor Green
    }
    $stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
    $configureLog=Join-Path $LogRoot "configure-$stamp-$profile.log"
    $buildLog=Join-Path $LogRoot "build-$stamp-$profile.log"
    $env:CUDA_PATH=$Cuda.Root
    Add-ToPath (Join-Path $Cuda.Root 'bin')
    $arch=($Nvidia.Architectures -join ';')

    Write-Step "llama.cpp lokal kompilieren ($profile)"
    Write-Host "GPU(s):         $($Nvidia.Names -join ' | ')"
    Write-Host "Treiber:        $($Nvidia.Driver)"
    Write-Host "CUDA Toolkit:   $($Cuda.Version)"
    Write-Host "CUDA Arch.:      $arch"
    Write-Host "Source:          $($Source.Path)"
    Write-Host "Build:           $buildDir"
    Write-Host "Configure-Log:   $configureLog"
    Write-Host "Build-Log:       $buildLog"
    Write-Host "Ein vorhandener Ninja-Build wird fortgesetzt; bereits fertige Objekte werden nicht neu kompiliert." -ForegroundColor Yellow

    $args=@(
        '-S',$Source.Path,'-B',$buildDir,'-G','Ninja',
        '-DCMAKE_BUILD_TYPE=Release',
        "-DCMAKE_MAKE_PROGRAM=$($Tools.Ninja)",
        "-DCMAKE_C_COMPILER=$Cl",
        "-DCMAKE_CXX_COMPILER=$Cl",
        "-DCMAKE_CUDA_COMPILER=$($Cuda.Nvcc)",
        "-DCMAKE_CUDA_HOST_COMPILER=$Cl",
        "-DCUDAToolkit_ROOT=$($Cuda.Root)",
        '-DGGML_CUDA=ON','-DGGML_NATIVE=OFF',
        "-DCMAKE_CUDA_ARCHITECTURES=$arch",
        '-DBUILD_SHARED_LIBS=ON',
        '-DLLAMA_BUILD_TESTS=OFF','-DLLAMA_BUILD_EXAMPLES=OFF',
        '-DLLAMA_BUILD_TOOLS=ON','-DLLAMA_BUILD_SERVER=ON',
        '-DLLAMA_BUILD_UI=OFF','-DLLAMA_BUILD_APP=OFF','-DLLAMA_OPENSSL=OFF'
    )
    if ($Conservative) {
        $args += '-DGGML_CUDA_GRAPHS=OFF'
        $args += '-DGGML_CUDA_NO_VMM=ON'
        $args += '-DGGML_CUDA_FA=OFF'
    }
    $rc = Invoke-NativeLogged -Exe $Tools.CMake -Arguments $args -LogFile $configureLog
    if ($rc -ne 0) { throw "CMake-Konfiguration fehlgeschlagen (Exitcode $rc). Log: $configureLog" }
    $jobs=[Math]::Max(1,[Environment]::ProcessorCount)
    $buildArgs=@('--build',$buildDir,'--target','llama-bench','llama-server','--parallel',$jobs)
    $rc = Invoke-NativeLogged -Exe $Tools.CMake -Arguments $buildArgs -LogFile $buildLog
    if ($rc -ne 0) { throw "llama.cpp-Kompilierung fehlgeschlagen (Exitcode $rc). Log: $buildLog" }

    Copy-Binaries $buildDir
    $bench=Join-Path $LlamaDir 'llama-bench.exe'
    Remove-Item Env:\GGML_CUDA_PDL -ErrorAction SilentlyContinue
    $probe=Invoke-Probe $bench
    $workaround=$null
    if (-not $probe.Ok -and $Nvidia.IsBlackwell) {
        $env:GGML_CUDA_PDL='0'
        $probe=Invoke-Probe $bench
        if ($probe.Ok) { $workaround='GGML_CUDA_PDL=0' }
    }
    return [pscustomobject]@{Ok=$probe.Ok;ExitCode=$probe.ExitCode;Output=$probe.Output;Profile=$profile;Workaround=$workaround;BuildDir=$buildDir;ConfigureLog=$configureLog;BuildLog=$buildLog}
}

function Test-ExistingBuild {
    if ($ForceUpdateLlamaCpp) { return $false }
    $bench=Join-Path $LlamaDir 'llama-bench.exe'; $server=Join-Path $LlamaDir 'llama-server.exe'
    if (-not (Test-Path $bench) -or -not (Test-Path $server) -or -not (Test-Path $StateFile)) { return $false }
    try { $state=Get-Content $StateFile -Raw | ConvertFrom-Json } catch { return $false }
    if ($state.build_kind -ne 'source') { return $false }
    if ($state.cuda_root) { $env:CUDA_PATH=[string]$state.cuda_root; Add-ToPath (Join-Path ([string]$state.cuda_root) 'bin') }
    if ($state.cuda_workaround -eq 'GGML_CUDA_PDL=0') { $env:GGML_CUDA_PDL='0' }
    $probe=Invoke-Probe $bench
    if (-not $probe.Ok) { return $false }
    Write-Host "llama.cpp Source-Build vorhanden: $($state.source_ref), CUDA $($state.cuda_toolkit), Arch $($state.cuda_architectures)" -ForegroundColor Green
    return $true
}

if (Test-ExistingBuild) { exit 0 }

$nvidia=Get-NvidiaInfo
if (-not $nvidia) { throw "Keine NVIDIA-GPU ueber nvidia-smi erkannt." }
if ($nvidia.Architectures.Count -eq 0) { throw "Compute Capability konnte nicht ermittelt werden. GPU(s): $($nvidia.Names -join ', ')" }

Write-Step "llama.cpp Source-Build Setup"
Write-Host "GPU(s): $($nvidia.Names -join ' | ')"
Write-Host "Compute Capability: $($nvidia.Caps -join ', ')"
Write-Host "Kurzer Workspace: $WorkRoot"
if ($nvidia.IsBlackwell) { Write-Host "Blackwell erkannt: nativer Build fuer $($nvidia.Architectures -join ';') mit CUDA 12.8/12.9." -ForegroundColor Green }

$tools=Ensure-CMakeNinja
$vs=Ensure-VisualStudio
$cl=Import-VsEnvironment $vs.VcVars
$cuda=Select-Cuda $nvidia
Write-Host "nvcc: $($cuda.Nvcc)"
Write-Host (& $cuda.Nvcc --version | Select-Object -Last 1)

$ref=$LlamaCppTag.Trim()
if (-not $ref -and (Test-Path $PreparedRefFile)) { $ref=(Get-Content $PreparedRefFile -Raw).Trim() }
if (-not $ref) { throw "Keine llama.cpp-Source-Ref vorhanden." }
$source=Ensure-PreparedSource $ref

try {
    $result=Build-Llama $tools $cl $cuda $nvidia $ref $source
    if (-not $result.Ok) {
        Write-Warning "Optimierter Source-Build startet nicht (Exitcode $($result.ExitCode)). Baue konservatives Profil..."
        $result=Build-Llama $tools $cl $cuda $nvidia $ref $source -Conservative
    }
    if (-not $result.Ok) {
        if (Test-Path $DiagScript) { try { & $DiagScript -BenchExe (Join-Path $LlamaDir 'llama-bench.exe') | Out-Null } catch { } }
        throw "Lokal kompilierter llama.cpp-Build startet nicht (Exitcode $($result.ExitCode))."
    }

    if ($result.Workaround) { $env:GGML_CUDA_PDL='0' }
    $sourceHash=""
    $hashFile=Join-Path $RuntimeRoot "llama-source-sha256.txt"
    if (Test-Path $hashFile) { $sourceHash=(Get-Content $hashFile -Raw).Trim() }
    $state=[ordered]@{
        build_kind='source'; source_ref=$ref; source_path=$source.Path; source_archive_sha256=$sourceHash;
        work_root=$WorkRoot; backend='cuda-source'; cuda_toolkit=$cuda.Version.ToString(); cuda_root=$cuda.Root; nvcc=$cuda.Nvcc;
        cuda_architectures=($nvidia.Architectures -join ';'); compute_capabilities=($nvidia.Caps -join ';');
        gpu_names=($nvidia.Names -join ' | '); nvidia_driver=$nvidia.Driver; build_profile=$result.Profile;
        cuda_workaround=$result.Workaround; configure_log=$result.ConfigureLog; build_log=$result.BuildLog;
        installed_at=(Get-Date).ToString('o')
    }
    $state | ConvertTo-Json -Depth 4 | Set-Content $StateFile -Encoding UTF8
    Write-Host ""
    Write-Host "llama.cpp wurde erfolgreich aus dem Quellcode kompiliert." -ForegroundColor Green
    Write-Host "Source $ref | CUDA $($cuda.Version) | $($nvidia.Architectures -join ';') | $($result.Profile)" -ForegroundColor Green
    if ($result.Workaround) { Write-Host "Runtime-Workaround: $($result.Workaround)" -ForegroundColor Yellow }
    exit 0
} catch {
    Write-Host ""
    Write-Host "Source-Build fehlgeschlagen: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Build-Logs liegen unter: $LogRoot" -ForegroundColor Yellow
    throw
}
