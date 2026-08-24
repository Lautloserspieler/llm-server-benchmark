[CmdletBinding()]
param(
    [string]$BenchExe = ""
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$RuntimeRoot = Join-Path $Root ".runtime"
$DiagDir = Join-Path $RuntimeRoot "diagnostics"
$LlamaDir = Join-Path $Root "tools\llama.cpp"
if (-not $BenchExe) { $BenchExe = Join-Path $LlamaDir "llama-bench.exe" }

New-Item -ItemType Directory -Force -Path $DiagDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$DiagFile = Join-Path $DiagDir "llama-crash-$stamp.txt"
$lines = New-Object System.Collections.Generic.List[string]

function Add-Line([string]$Text = "") {
    $lines.Add($Text)
}

function Add-Section([string]$Title) {
    Add-Line ""
    Add-Line "=== $Title ==="
}

function Command-Text([string]$Exe, [string[]]$Args = @()) {
    try {
        $cmd = Get-Command $Exe -ErrorAction Stop
        return ((& $cmd.Source @Args 2>&1 | Out-String).Trim())
    } catch {
        return "nicht gefunden: $Exe"
    }
}

function ExitCode-Hex($ExitCode) {
    if ($null -eq $ExitCode) { return "unbekannt" }
    try {
        $bytes = [BitConverter]::GetBytes([int32]$ExitCode)
        $u32 = [BitConverter]::ToUInt32($bytes, 0)
        return ("0x{0:X8}" -f $u32)
    } catch {
        return "unbekannt"
    }
}

Add-Line "LLM Server Benchmark - llama.cpp Crash-Diagnose"
Add-Line "Zeit: $(Get-Date -Format o)"
Add-Line "Computer: $env:COMPUTERNAME"
Add-Line "Benutzer: $env:USERNAME"
Add-Line "PowerShell: $($PSVersionTable.PSVersion)"

Add-Section "Windows"
try {
    $os = Get-CimInstance Win32_OperatingSystem
    Add-Line "OS: $($os.Caption)"
    Add-Line "Version: $($os.Version)"
    Add-Line "Build: $($os.BuildNumber)"
    Add-Line "Architektur: $($os.OSArchitecture)"
} catch {
    Add-Line "OS-Abfrage fehlgeschlagen: $($_.Exception.Message)"
}

Add-Section "NVIDIA"
$nvidiaSmi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
if ($nvidiaSmi) {
    Add-Line "nvidia-smi: $($nvidiaSmi.Source)"
    Add-Line (Command-Text "nvidia-smi.exe" @("--query-gpu=name,driver_version,pci.bus_id,memory.total","--format=csv,noheader"))
    Add-Line ""
    Add-Line (Command-Text "nvidia-smi.exe")
} else {
    Add-Line "nvidia-smi.exe nicht gefunden"
}

Add-Section "CUDA Toolkit"
$nvcc = Get-Command nvcc.exe -ErrorAction SilentlyContinue
if ($nvcc) {
    Add-Line "nvcc: $($nvcc.Source)"
    Add-Line (Command-Text "nvcc.exe" @("--version"))
} else {
    Add-Line "nvcc.exe nicht im PATH gefunden"
}
foreach ($cudaVar in @("CUDA_PATH", "CUDA_PATH_V12_8", "CUDA_PATH_V12_9", "CUDA_PATH_V13_0", "CUDA_PATH_V13_1", "CUDA_PATH_V13_2", "CUDA_PATH_V13_3")) {
    $value = [Environment]::GetEnvironmentVariable($cudaVar)
    if ($value) { Add-Line "$cudaVar=$value" }
}

Add-Section "llama.cpp Dateien"
Add-Line "llama-bench: $BenchExe"
Add-Line "Existiert: $(Test-Path $BenchExe)"
if (Test-Path $BenchExe) {
    try {
        $item = Get-Item $BenchExe
        Add-Line "Groesse: $($item.Length) Bytes"
        Add-Line "Version: $($item.VersionInfo.FileVersion)"
    } catch { }
}
if (Test-Path $LlamaDir) {
    $dlls = Get-ChildItem $LlamaDir -Filter "*.dll" -File -ErrorAction SilentlyContinue | Sort-Object Name
    foreach ($dll in $dlls) {
        if ($dll.Name -match 'cuda|cudart|cublas|nvrtc|ggml|vcruntime|msvcp') {
            Add-Line ("{0} | {1} bytes" -f $dll.Name, $dll.Length)
        }
    }
}

Add-Section "Microsoft VC Runtime"
foreach ($dllName in @("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")) {
    $systemDll = Join-Path $env:WINDIR "System32\$dllName"
    if (Test-Path $systemDll) {
        try {
            $v = (Get-Item $systemDll).VersionInfo.FileVersion
            Add-Line "$systemDll | $v"
        } catch {
            Add-Line "$systemDll | vorhanden"
        }
    } else {
        Add-Line "$systemDll | FEHLT"
    }
}

Add-Section "Direkter Starttest"
$startTime = Get-Date
$exitCode = $null
$stdout = ""
$stderr = ""
if (Test-Path $BenchExe) {
    $outFile = [System.IO.Path]::GetTempFileName()
    $errFile = [System.IO.Path]::GetTempFileName()
    try {
        $proc = Start-Process -FilePath $BenchExe -ArgumentList "--list-devices" -Wait -PassThru -NoNewWindow `
            -RedirectStandardOutput $outFile -RedirectStandardError $errFile
        $exitCode = $proc.ExitCode
        $stdout = (Get-Content $outFile -Raw -ErrorAction SilentlyContinue)
        $stderr = (Get-Content $errFile -Raw -ErrorAction SilentlyContinue)
    } catch {
        Add-Line "Start-Process Exception: $($_.Exception.Message)"
    } finally {
        Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue
    }
    $hex = ExitCode-Hex $exitCode
    Add-Line "Exitcode dezimal: $exitCode"
    Add-Line "Exitcode hex: $hex"
    if ($hex -eq "0xC0000005") {
        Add-Line "Bedeutung: STATUS_ACCESS_VIOLATION - nativer Prozesszugriffsfehler. Das ist kein normaler llama.cpp-CLI-Fehler."
    } elseif ($hex -eq "0xC0000135") {
        Add-Line "Bedeutung: STATUS_DLL_NOT_FOUND - eine benoetigte DLL fehlt."
    } elseif ($hex -eq "0xC000007B") {
        Add-Line "Bedeutung: STATUS_INVALID_IMAGE_FORMAT - meist falsche DLL-Architektur oder inkompatible Runtime."
    }
    if ($stdout.Trim()) {
        Add-Line "--- stdout ---"
        Add-Line $stdout.Trim()
    }
    if ($stderr.Trim()) {
        Add-Line "--- stderr ---"
        Add-Line $stderr.Trim()
    }
}

Add-Section "Windows Application Error / WER"
try {
    Start-Sleep -Seconds 1
    $events = Get-WinEvent -FilterHashtable @{ LogName='Application'; StartTime=$startTime.AddSeconds(-10) } -MaxEvents 80 -ErrorAction Stop |
        Where-Object {
            ($_.ProviderName -eq 'Application Error' -or $_.ProviderName -eq 'Windows Error Reporting') -and
            ($_.Message -match 'llama-bench|ggml|cuda')
        } | Select-Object -First 6
    if ($events) {
        foreach ($evt in $events) {
            Add-Line "[$($evt.TimeCreated)] Provider=$($evt.ProviderName) Id=$($evt.Id)"
            Add-Line (($evt.Message -replace "`r", "").Trim())
            Add-Line ""
        }
    } else {
        Add-Line "Kein passendes Application-Error/WER-Ereignis gefunden."
    }
} catch {
    Add-Line "Eventlog-Abfrage fehlgeschlagen: $($_.Exception.Message)"
}

Add-Section "Source-Build Bereitschaft"
$cmake = Get-Command cmake.exe -ErrorAction SilentlyContinue
$cl = Get-Command cl.exe -ErrorAction SilentlyContinue
$vswhere = Get-Command vswhere.exe -ErrorAction SilentlyContinue
Add-Line "cmake.exe: $(if ($cmake) { $cmake.Source } else { 'nicht gefunden' })"
Add-Line "cl.exe: $(if ($cl) { $cl.Source } else { 'nicht gefunden' })"
Add-Line "vswhere.exe: $(if ($vswhere) { $vswhere.Source } else { 'nicht gefunden' })"
if ($nvcc -and $cmake -and $cl) {
    Add-Line "Source-Build Voraussetzungen im PATH vorhanden: JA"
    Add-Line "Blackwell-Build kann mit CUDA >=12.8 und CMAKE_CUDA_ARCHITECTURES=120a versucht werden."
} else {
    Add-Line "Source-Build Voraussetzungen im PATH vorhanden: NEIN/UNVOLLSTAENDIG"
}

[System.IO.File]::WriteAllLines($DiagFile, $lines, [System.Text.UTF8Encoding]::new($true))

Write-Host ""
Write-Host "=== llama.cpp Crash-Diagnose ===" -ForegroundColor Yellow
foreach ($line in $lines) {
    if ($line -match '^Exitcode|^Bedeutung:|Faulting|Fehlerhaftes|Source-Build Voraussetzungen') {
        Write-Host $line -ForegroundColor Yellow
    }
}
Write-Host "Vollstaendige Diagnose gespeichert unter:" -ForegroundColor Yellow
Write-Host "  $DiagFile" -ForegroundColor Yellow

exit 0
