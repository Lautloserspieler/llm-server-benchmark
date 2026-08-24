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
        if (-not $Exe) { return $false }
        $args = @($PrefixArgs) + @("-c", "import sys; assert sys.version_info >= (3,10); print(sys.executable)")
        $out = & $Exe @args 2>$null
        return ($LASTEXITCODE -eq 0 -and $out)
    } catch {
        return $false
    }
}

function Save-PythonPath([string]$Exe) {
    New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
    $resolved = (Resolve-Path $Exe).Path
    Set-Content -Path $PythonPathFile -Value $resolved -Encoding UTF8
    return $resolved
}

function Find-Python {
    $seen = @{}
    $paths = New-Object System.Collections.Generic.List[string]

    # Projektlokale Runtime zuerst.
    if (Test-Path $PythonExe) { $paths.Add($PythonExe) }

    # Übliche Installationsorte. Wichtig für Maschinen, auf denen Python zwar
    # installiert, aber nicht in PATH eingetragen ist.
    $known = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python311\python.exe",
        "$env:ProgramFiles\Python310\python.exe"
    )
    foreach ($p in $known) { if ($p -and (Test-Path $p)) { $paths.Add($p) } }

    # PEP-514-Registry auslesen. Der Python-Installer kann eine vorhandene
    # Installation reparieren statt TargetDir neu anzulegen; dann steht der
    # echte Interpreter hier, auch wenn PATH noch nicht aktualisiert wurde.
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

    foreach ($p in $paths) {
        $key = $p.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        if (Test-Python $p) { return (Resolve-Path $p).Path }
    }

    # Zuletzt PATH/py-Launcher prüfen.
    $commands = @(
        @{ Exe = "py"; Args = @("-3.12") },
        @{ Exe = "py"; Args = @("-3") },
        @{ Exe = "python"; Args = @() }
    )
    foreach ($candidate in $commands) {
        try {
            $cmd = Get-Command $candidate.Exe -ErrorAction Stop
            if (Test-Python $cmd.Source $candidate.Args) {
                $args = @($candidate.Args) + @("-c", "import sys; print(sys.executable)")
                $actual = (& $cmd.Source @args 2>$null | Select-Object -Last 1).Trim()
                if ($actual -and (Test-Path $actual)) { return (Resolve-Path $actual).Path }
            }
        } catch { }
    }
    return $null
}

$existing = Find-Python
if ($existing) {
    $existing = Save-PythonPath $existing
    Write-Host "Geeignetes Python vorhanden: $existing"
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
$logFile = Join-Path $tmpDir "python-install.log"
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

    if (Test-Path $PythonHome) { Remove-Item -Recurse -Force $PythonHome }
    New-Item -ItemType Directory -Force -Path $PythonHome | Out-Null

    $installArgs = @(
        "/quiet",
        "/log", "`"$logFile`"",
        "InstallAllUsers=0",
        "TargetDir=`"$PythonHome`"",
        "PrependPath=0",
        "AppendPath=0",
        "Include_launcher=0",
        "InstallLauncherAllUsers=0",
        "Include_pip=1",
        "Include_test=0",
        "Include_doc=0",
        "Shortcuts=0"
    )
    $proc = Start-Process -FilePath $installer -ArgumentList $installArgs -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        throw "Der offizielle Python-Installer ist mit Exitcode $($proc.ExitCode) fehlgeschlagen. Installationslog: $logFile"
    }

    # Nicht mehr blind TargetDir voraussetzen. Bei einer bereits registrierten
    # Python-Version kann der Installer erfolgreich enden und die bestehende
    # Installation verwenden/reparieren.
    $installed = Find-Python
    if (-not $installed) {
        throw "Python-Installer meldete Erfolg, aber kein funktionsfähiger Python-Interpreter wurde gefunden."
    }
    $installed = Save-PythonPath $installed

    if ($installed -ieq $PythonExe) {
        & $installed -m ensurepip --upgrade | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "pip konnte nicht initialisiert werden." }
        Write-Host "Python $PythonVersion wurde projektlokal installiert:"
    } else {
        Write-Warning "Der Python-Installer hat eine bestehende Installation verwendet. Diese wird für den Benchmark genutzt."
        Write-Host "Python gefunden:"
    }
    Write-Host "  $installed" -ForegroundColor Green
    exit 0
}
finally {
    Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue
}
