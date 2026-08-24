param()

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Root = Split-Path -Parent $PSScriptRoot
$RuntimeRoot = Join-Path $Root ".runtime"
$PythonHome = Join-Path $RuntimeRoot "python"
$PythonExe = Join-Path $PythonHome "python.exe"
$PythonPathFile = Join-Path $RuntimeRoot "python-path.txt"
$PythonVersion = "3.12.10"

function Test-Python([string]$Exe, [string[]]$PrefixArgs = @()) {
    try {
        if (-not $Exe -or -not (Test-Path $Exe)) { return $false }
        $testArgs = @($PrefixArgs) + @("-c", "import sys; assert sys.version_info >= (3,10); print(sys.executable)")
        $out = & $Exe @testArgs 2>$null
        return ($LASTEXITCODE -eq 0 -and $out)
    } catch {
        return $false
    }
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

function Find-Python {
    $seen = @{}
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
    foreach ($p in $known) {
        if ($p -and (Test-Path $p)) { $paths.Add($p) }
    }

    # PEP-514: zuverlässigste Quelle für regulär installierte CPython-Versionen.
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

    # Fallback für Installer, die trotz erfolgreichem Exitcode einen anderen
    # Zielordner gewählt haben. Die Suche bleibt auf typische Python-Wurzeln
    # beschränkt und läuft nicht über die gesamte Festplatte.
    Add-PythonCandidatesFromDirectory $paths (Join-Path $env:LOCALAPPDATA "Programs\Python") 4
    Add-PythonCandidatesFromDirectory $paths (Join-Path $env:LOCALAPPDATA "Python") 4
    Add-PythonCandidatesFromDirectory $paths $PythonHome 4
    if ($env:ProgramFiles) { Add-PythonCandidatesFromDirectory $paths $env:ProgramFiles 2 }

    foreach ($p in $paths) {
        if (-not $p) { continue }
        $key = $p.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        if (Test-Python $p) { return (Resolve-Path $p).Path }
    }

    $commands = @(
        @{ Exe = "py"; Args = @("-3.12") },
        @{ Exe = "py"; Args = @("-3") },
        @{ Exe = "python"; Args = @() }
    )
    foreach ($candidate in $commands) {
        try {
            $cmd = Get-Command $candidate.Exe -ErrorAction Stop
            $testArgs = @($candidate.Args) + @("-c", "import sys; print(sys.executable)")
            $actual = (& $cmd.Source @testArgs 2>$null | Select-Object -Last 1)
            if ($LASTEXITCODE -eq 0 -and $actual) {
                $actual = $actual.ToString().Trim()
                if ($actual -and (Test-Python $actual)) { return (Resolve-Path $actual).Path }
            }
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

    # Keine erzwungene TargetDir mehr. Der offizielle Installer entscheidet über
    # seinen normalen per-user-Pfad. Das vermeidet den Maintenance/Repair-Fall,
    # bei dem Exitcode 0 geliefert wird, .runtime\python aber leer bleibt.
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

    # Registry-/Dateisystem-Updates können direkt nach Installer-Ende kurz
    # verzögert sichtbar werden. Bis zu 15 Sekunden erneut suchen.
    $installed = $null
    foreach ($attempt in 1..15) {
        $installed = Find-Python
        if ($installed) { break }
        Start-Sleep -Seconds 1
    }

    if (-not $installed) {
        Write-Host "Installationslog: $logFile" -ForegroundColor Yellow
        throw "Python-Installer meldete Erfolg, aber kein startbarer Python-Interpreter wurde gefunden."
    }

    $installed = Save-PythonPath $installed
    Write-Host "Python wurde erfolgreich erkannt:" -ForegroundColor Green
    Write-Host "  $installed" -ForegroundColor Green

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
