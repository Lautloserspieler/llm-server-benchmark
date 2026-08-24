[CmdletBinding()]
param(
    [string]$BenchExe = ""
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$RuntimeRoot = Join-Path $Root ".runtime"
$DiagDir = Join-Path $RuntimeRoot "diagnostics"
$LlamaDir = Join-Path $Root "tools\llama.cpp"
$LocalCMake = Join-Path $RuntimeRoot "build-tools\Scripts\cmake.exe"
$LocalNinja = Join-Path $RuntimeRoot "build-tools\Scripts\ninja.exe"
if (-not $BenchExe) { $BenchExe = Join-Path $LlamaDir "llama-bench.exe" }

New-Item -ItemType Directory -Force -Path $DiagDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$DiagFile = Join-Path $DiagDir "llama-crash-$stamp.txt"
$lines = New-Object System.Collections.Generic.List[string]

function Add-Line([string]$Text = "") { $lines.Add($Text) }
function Add-Section([string]$Title) { Add-Line ""; Add-Line "=== $Title ===" }
function ExitCode-Hex($ExitCode) {
    if ($null -eq $ExitCode) { return "unbekannt" }
    try { return ("0x{0:X8}" -f ([BitConverter]::ToUInt32([BitConverter]::GetBytes([int32]$ExitCode),0))) } catch { return "unbekannt" }
}

function Find-VisualStudio {
    $candidates=@(
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe",
        "$env:ProgramFiles\Microsoft Visual Studio\Installer\vswhere.exe"
    )
    foreach($vswhere in $candidates){
        if(-not $vswhere -or -not (Test-Path $vswhere)){continue}
        $root=(& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null | Select-Object -First 1)
        if($root){
            $root=$root.ToString().Trim(); $vcvars=Join-Path $root "VC\Auxiliary\Build\vcvars64.bat"
            if(Test-Path $vcvars){return [pscustomobject]@{Root=$root;VsWhere=$vswhere;VcVars=$vcvars}}
        }
    }
    foreach($base in @("$env:ProgramFiles\Microsoft Visual Studio","${env:ProgramFiles(x86)}\Microsoft Visual Studio")){
        if(-not $base -or -not (Test-Path $base)){continue}
        $vcvars=Get-ChildItem $base -Filter vcvars64.bat -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
        if($vcvars){return [pscustomobject]@{Root=$base;VsWhere=$null;VcVars=$vcvars.FullName}}
    }
    return $null
}

Add-Line "LLM Server Benchmark - llama.cpp Diagnose"
Add-Line "Zeit: $(Get-Date -Format o)"
Add-Line "Computer: $env:COMPUTERNAME"
Add-Line "Benutzer: $env:USERNAME"
Add-Line "PowerShell: $($PSVersionTable.PSVersion)"

Add-Section "Windows"
try {
    $os=Get-CimInstance Win32_OperatingSystem
    Add-Line "OS: $($os.Caption)"
    Add-Line "Version: $($os.Version)"
    Add-Line "Build: $($os.BuildNumber)"
    Add-Line "Architektur: $($os.OSArchitecture)"
} catch { Add-Line "OS-Abfrage fehlgeschlagen: $($_.Exception.Message)" }

Add-Section "NVIDIA"
$smi=Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
if($smi){
    Add-Line "nvidia-smi: $($smi.Source)"
    try { Add-Line ((& $smi.Source --query-gpu=name,driver_version,pci.bus_id,memory.total,compute_cap --format=csv,noheader 2>&1 | Out-String).Trim()) } catch {}
    Add-Line ""
    try { Add-Line ((& $smi.Source 2>&1 | Out-String).Trim()) } catch {}
}else{Add-Line "nvidia-smi.exe nicht gefunden"}

Add-Section "CUDA Toolkit"
$cudaRoots=New-Object System.Collections.Generic.List[string]
if($env:CUDA_PATH){$cudaRoots.Add($env:CUDA_PATH)}
$cudaBase=Join-Path $env:ProgramFiles "NVIDIA GPU Computing Toolkit\CUDA"
if(Test-Path $cudaBase){Get-ChildItem $cudaBase -Directory -ErrorAction SilentlyContinue | ForEach-Object {$cudaRoots.Add($_.FullName)}}
$seen=@{}
foreach($root in $cudaRoots){
    if(-not $root){continue};$key=$root.ToLowerInvariant();if($seen[$key]){continue};$seen[$key]=$true
    $nvcc=Join-Path $root "bin\nvcc.exe"
    if(Test-Path $nvcc){
        Add-Line "nvcc: $nvcc"
        try { Add-Line ((& $nvcc --version 2>&1 | Out-String).Trim()) } catch { Add-Line "nvcc --version fehlgeschlagen: $($_.Exception.Message)" }
    }
}
foreach($v in @("CUDA_PATH","CUDA_PATH_V12_8","CUDA_PATH_V12_9","CUDA_PATH_V13_0","CUDA_PATH_V13_1","CUDA_PATH_V13_2","CUDA_PATH_V13_3")){
    $value=[Environment]::GetEnvironmentVariable($v);if($value){Add-Line "$v=$value"}
}

Add-Section "llama.cpp Dateien"
Add-Line "llama-bench: $BenchExe"
Add-Line "Existiert: $(Test-Path $BenchExe)"
if(Test-Path $BenchExe){
    $item=Get-Item $BenchExe
    Add-Line "Groesse: $($item.Length) Bytes"
    Add-Line "Version: $($item.VersionInfo.FileVersion)"
}
if(Test-Path $LlamaDir){
    Get-ChildItem $LlamaDir -Filter *.dll -File -ErrorAction SilentlyContinue | Sort-Object Name | ForEach-Object { Add-Line "$($_.Name) | $($_.Length) bytes" }
}

Add-Section "Direkter Starttest"
$startTime=Get-Date;$exitCode=$null
if(Test-Path $BenchExe){
    $out=[IO.Path]::GetTempFileName();$err=[IO.Path]::GetTempFileName()
    try{
        $p=Start-Process $BenchExe -ArgumentList '--list-devices' -Wait -PassThru -NoNewWindow -RedirectStandardOutput $out -RedirectStandardError $err
        $exitCode=$p.ExitCode
        $stdout=Get-Content $out -Raw -ErrorAction SilentlyContinue
        $stderr=Get-Content $err -Raw -ErrorAction SilentlyContinue
        Add-Line "Exitcode dezimal: $exitCode"
        $hex=ExitCode-Hex $exitCode;Add-Line "Exitcode hex: $hex"
        if($hex -eq '0xC0000005'){Add-Line 'Bedeutung: STATUS_ACCESS_VIOLATION'}
        if($stdout.Trim()){Add-Line '--- stdout ---';Add-Line $stdout.Trim()}
        if($stderr.Trim()){Add-Line '--- stderr ---';Add-Line $stderr.Trim()}
    }catch{Add-Line "Start-Process Exception: $($_.Exception.Message)"}
    finally{Remove-Item $out,$err -Force -ErrorAction SilentlyContinue}
}else{Add-Line "Kein Starttest: llama-bench.exe existiert noch nicht."}

Add-Section "Windows Application Error / WER"
try{
    Start-Sleep -Seconds 1
    $events=Get-WinEvent -FilterHashtable @{LogName='Application';StartTime=$startTime.AddSeconds(-15)} -MaxEvents 100 -ErrorAction Stop | Where-Object {($_.ProviderName -eq 'Application Error' -or $_.ProviderName -eq 'Windows Error Reporting') -and ($_.Message -match 'llama-bench|ggml|cuda')} | Select-Object -First 8
    if($events){foreach($evt in $events){Add-Line "[$($evt.TimeCreated)] $($evt.ProviderName) Id=$($evt.Id)";Add-Line (($evt.Message -replace "`r",'').Trim());Add-Line ''}}
    else{Add-Line 'Kein passendes Application-Error/WER-Ereignis gefunden.'}
}catch{Add-Line "Eventlog-Abfrage fehlgeschlagen: $($_.Exception.Message)"}

Add-Section "Source-Build Bereitschaft"
$cmakePath = if(Test-Path $LocalCMake){$LocalCMake}else{(Get-Command cmake.exe -ErrorAction SilentlyContinue).Source}
$ninjaPath = if(Test-Path $LocalNinja){$LocalNinja}else{(Get-Command ninja.exe -ErrorAction SilentlyContinue).Source}
$vs=Find-VisualStudio
Add-Line "cmake.exe: $(if($cmakePath){$cmakePath}else{'nicht gefunden'})"
Add-Line "ninja.exe: $(if($ninjaPath){$ninjaPath}else{'nicht gefunden'})"
if($vs){Add-Line "Visual Studio: $($vs.Root)";Add-Line "vcvars64.bat: $($vs.VcVars)";Add-Line "vswhere.exe: $(if($vs.VsWhere){$vs.VsWhere}else{'nicht benoetigt / rekursiv gefunden'})"}
else{Add-Line 'Visual C++ Build Tools: nicht gefunden'}
$cuda128=Test-Path "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin\nvcc.exe"
Add-Line "CUDA 12.8 nvcc: $(if($cuda128){'vorhanden'}else{'nicht gefunden'})"
$ready=[bool]($cmakePath -and $ninjaPath -and $vs -and ($cudaRoots.Count -gt 0))
Add-Line "Source-Build Voraussetzungen gefunden: $(if($ready){'JA'}else{'NEIN/UNVOLLSTAENDIG'})"

Add-Section "Letzte Build-Logs"
$logRoot=Join-Path $RuntimeRoot 'build-logs'
if(Test-Path $logRoot){
    $logs=Get-ChildItem $logRoot -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 4
    foreach($log in $logs){Add-Line "$($log.FullName) | $($log.LastWriteTime) | $($log.Length) bytes"}
}else{Add-Line 'Noch keine Source-Build-Logs vorhanden.'}

[IO.File]::WriteAllLines($DiagFile,$lines,[Text.UTF8Encoding]::new($true))
Write-Host ""
Write-Host "=== llama.cpp Diagnose ===" -ForegroundColor Yellow
Write-Host "Source-Build Voraussetzungen gefunden: $(if($ready){'JA'}else{'NEIN/UNVOLLSTAENDIG'})" -ForegroundColor Yellow
Write-Host "Vollstaendige Diagnose: $DiagFile" -ForegroundColor Yellow
exit 0
