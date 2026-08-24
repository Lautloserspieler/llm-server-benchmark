param()

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Root = Split-Path -Parent $PSScriptRoot
$RuntimeRoot = Join-Path $Root ".runtime"
$PythonHome = Join-Path $RuntimeRoot "python"
$PythonExe = Join-Path $PythonHome "python.exe"
$PythonPathFile = Join-Path $RuntimeRoot "python-path.txt"
$PythonVersion = "3.12.10"

function Invoke-PythonProbe([string]$Exe, [string[]]$PrefixArgs = @(), [switch]$VerboseFailure) {
    if (-not $Exe -or -not (Test-Path $Exe)) { return $null }

    $outFile = [System.IO.Path]::GetTempFileName()
    $errFile = [System.IO.Path]::GetTempFileName()
    try {
        $probeArgs = @($PrefixArgs) + @("-c", "import sys; assert sys.version_info >= (3,10); print(sys.executable)")
        $proc = Start-Process -FilePath $Exe -ArgumentList $probeArgs -Wait -PassThru -NoNewWindow `
            -RedirectStandardOutput $outFile -RedirectStandardError $errFile

        $stdout = (Get-Content $outFile -Raw -ErrorAction SilentlyContinue).Trim()
        $stderr = (Get-Content $errFile -Raw -ErrorAction SilentlyContinue).Trim()
        if ($proc.ExitCode -eq 0 -and $stdout) {
            return ($stdout -split "`r?`n" | Select-Object -Last 1).Trim()
        }

        if ($VerboseFailure) {
            Write-Warning "Python-Kandidat konnte nicht gestartet werden: $Exe (Exitcode $($proc.ExitCode))"
            if ($stderr) { Write-Host "  Fehler: $stderr" -ForegroundColor Yellow }
            elseif ($stdout) { Write-Host "  Ausgabe: $stdout" -ForegroundColor Yellow }
        }
        return $null
    } catch {
        if ($VerboseFailure) {
            Write-Warning "Python-Kandidat konnte nicht gestartet werden: $Exe"
            Write-Host "  Fehler: $($_.Exception.Message)" -ForegroundColor Yellow
        }
        return $null
    } finally {
        Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue
    }
}

function Test-Python([string]$Exe, [string[]]$PrefixArgs = @()) {
    return [bool](Invoke-PythonProbe $Exe $PrefixArgs)
}

function Save-PythonPath([string]$Exe) {
    New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
    $resolved = (Resolve-Path $Exe).Path
    [System.IO.File]::WriteAllText($PythonPathFile, $resolved, [System.Text.UTF8Encoding]::new($false))
    return $resolved
}

function Add-PythonCandidatesFromDirectory($List, [string]$Base, [int]$Depth = 3) {
    if (-not $Base -or -not (Test-Path $Base)) { return }
    try {
        Get-ChildItem -Path $Base -Filter "python.exe" -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object {
                $relative = $_.FullName.Substring($Base.Length).TrimStart('\')
                (($relative -split '\\').Count -le $Depth)
            } |
            ForEach-Object { $List.Add($_.FullName) }
    } catch { }
}

function Get-PythonCandidates {
    $paths = New-Object System.Collections.Generic.List[string]
    if (Test-Path $PythonExe) { $paths.Add($PythonExe) }

    $known = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python311\python.exe",
        "$env:ProgramFiles\Python310\python.exe"
    )
    foreach ($p in $known) { if ($p -and (Test-Path $p)) { $paths.Add($p) } }

    $registryRoots = @(
        "HKCU:\Software\Python\PythonCore",
        "HKLM:\Software\Python\PythonCore",
        "HKLM:\Software\WOW6432Node\Python\PythonCore"
    )
    foreach ($rootKey in $registryRoots) {
        if (-not (Test-Path $rootKey)) { continue }
        foreach ($versionKey in Get-ChildItem $rootKey -ErrorAction SilentlyContinue) {
            $installKey = Join-Path $versionKey.PSPath "InstallPath"
            try {
                $props = Get-ItemProperty $installKey -ErrorAction Stop
                if ($props.ExecutablePath -and (Test-Path $props.ExecutablePath)) {
                    $paths.Add([string]$props.ExecutablePath)
                }
                $home = (Get-Item $installKey -ErrorAction Stop).GetValue("")
                if ($home) {
                    $candidate = Join-Path $home "python.exe"
                    if (Test-Path $candidate) { $paths.Add($candidate) }
                }
            } catch { }
        }
    }

    Add-PythonCandidatesFromDirectory $paths (Join-Path $env:LOCALAPPDATA "Programs\Python") 4
    Add-PythonCandidatesFromDirectory $paths (Join-Path $env:LOCALAPPDATA "Python") 4
    Add-PythonCandidatesFromDirectory $paths $PythonHome 4
    if ($env:ProgramFiles) { Add-PythonCandidatesFromDirectory $paths $env:ProgramFiles 2 }

    $seen = @{}
    $unique = New-Object System.Collections.Generic.List[string]
    foreach ($p in $paths) {
        if (-not $p) { continue }
        $key = $p.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        $unique.Add($p)
    }
    return $unique
}

function Find-Python([switch]$ShowFailures) {
    foreach ($p in (Get-PythonCandidates)) {
        $actual = Invoke-PythonProbe $p @() -VerboseFailure:$ShowFailures
        if ($actual -and (Test-Path $actual)) { return (Resolve-Path $actual).Path }
        if ($actual -and (Test-Path $p)) { return (Resolve-Path $p).Path }
    }

    $commands = @(
        @{ Exe = "py.exe"; Args = @("-3.12") },
        @{ Exe = "py.exe"; Args = @("-3") },
        @{ Exe = "python.exe"; Args = @() }
    )
    foreach ($candidate in $commands) {
        try {
            $cmd = Get-Command $candidate.Exe -ErrorAction Stop
            # WindowsApps-Aliase sind keine echte Python-Installation.
            if ($cmd.Source -like "*\Microsoft\WindowsApps\python*.exe") { continue }
            $actual = Invoke-PythonProbe $cmd.Source $candidate.Args -VerboseFailure:$ShowFailures
            if ($actual -and (Test-Path $actual)) { return (Resolve-Path $actual).Path }
        } catch { }
    }
    return $null
}

$existing = Find-Python
if ($existing) {
    $existing = Save-PythonPath $existing
    Write-Host "Geeignetes Python vorhanden: $existing" -ForegroundColor Green
    exit 0
}

Write-Host ""
Write-Host "=== Python wird ohne winget eingerichtet ===" -ForegroundColor Cyan
Write-Host "Es wird Python $PythonVersion direkt von python.org geladen."

$arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLowerInvariant()
switch ($arch) {
    "x64" {
        $fileName = "python-$PythonVersion-amd64.exe"
        $expectedSha256 = "67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb"
    }
    "arm64" {
        $fileName = "python-$PythonVersion-arm64.exe"
        $expectedSha256 = "377ac8fd478987940088e879441e702a71b53164d2a1e6f1d51ff77a7e470258"
    }
    default { throw "Nicht unterstützte Windows-Architektur '$arch'. Unterstützt werden x64 und ARM64." }
}

$url = "https://www.python.org/ftp/python/$PythonVersion/$fileName"
$tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("llmbench-python-" + [guid]::NewGuid().ToString("N"))
$installer = Join-Path $tmpDir $fileName
$logFile = Join-Path $RuntimeRoot "python-install.log"
New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null

try {
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }
    Write-Host "Download: $url"
    Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
    if (-not (Test-Path $installer)) { throw "Der Python-Installer wurde nicht heruntergeladen." }

    $actualSha256 = (Get-FileHash -Path $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualSha256 -ne $expectedSha256) {
        throw "SHA256-Prüfung des Python-Installers fehlgeschlagen. Erwartet: $expectedSha256, erhalten: $actualSha256"
    }
    Write-Host "SHA256-Prüfung erfolgreich."

    $installArgs = @(
        "/quiet",
        "/log", "`"$logFile`"",
        "InstallAllUsers=0",
        "PrependPath=0",
        "AppendPath=0",
        "Include_launcher=1",
        "InstallLauncherAllUsers=0",
        "Include_pip=1",
        "Include_test=0",
        "Include_doc=0",
        "Shortcuts=0"
    )

    Write-Host "Python-Installer wird ausgeführt..."
    $proc = Start-Process -FilePath $installer -ArgumentList $installArgs -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        throw "Der offizielle Python-Installer ist mit Exitcode $($proc.ExitCode) fehlgeschlagen. Installationslog: $logFile"
    }

    $installed = $null
    foreach ($attempt in 1..20) {
        $installed = Find-Python
        if ($installed) { break }
        Start-Sleep -Seconds 1
    }

    if (-not $installed) {
        Write-Host "" 
        Write-Host "Python-Dateien wurden nach Installer-Erfolg gefunden/geprüft:" -ForegroundColor Yellow
        $candidates = @(Get-PythonCandidates)
        if ($candidates.Count -eq 0) {
            Write-Host "  Kein python.exe in den erwarteten Installationsorten gefunden." -ForegroundColor Yellow
        } else {
            foreach ($candidate in $candidates) {
                Write-Host "  $candidate"
                [void](Invoke-PythonProbe $candidate @() -VerboseFailure)
            }
        }
        Write-Host "Installationslog: $logFile" -ForegroundColor Yellow
        throw "Python-Installer meldete Erfolg, aber kein startbarer Python-Interpreter wurde gefunden. Siehe die konkrete Kandidaten-/Fehlerausgabe oben."
    }

    $installed = Save-PythonPath $installed
    Write-Host "Python wurde erfolgreich erkannt:" -ForegroundColor Green
    Write-Host "  $installed" -ForegroundColor Green

    $pipOut = Invoke-PythonProbe $installed @("-m", "pip", "--version")
    & $installed -m pip --version *> $null
    if ($LASTEXITCODE -ne 0) {
        & $installed -m ensurepip --upgrade
        if ($LASTEXITCODE -ne 0) { throw "Python wurde gefunden, aber pip konnte nicht initialisiert werden." }
    }
    exit 0
}
finally {
    Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue
}
