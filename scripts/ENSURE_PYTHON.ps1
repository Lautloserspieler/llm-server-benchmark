param()

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Root = Split-Path -Parent $PSScriptRoot
$RuntimeRoot = Join-Path $Root ".runtime"
$PythonPathFile = Join-Path $RuntimeRoot "python-path.txt"
$PythonVersion = "3.12.10"
$InstallLog = Join-Path $RuntimeRoot "python-install.log"

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

function Save-PythonPath([string]$Path) {
    if (-not $Path) { return $false }
    $Path = $Path.Trim().Trim('"')
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }

    try {
        $resolved = (Resolve-Path -LiteralPath $Path).Path
        $version = & $resolved -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $version) { return $false }

        $ok = & $resolved -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" 2>$null
        if ($LASTEXITCODE -ne 0) { return $false }

        [System.IO.File]::WriteAllText($PythonPathFile, $resolved, [System.Text.UTF8Encoding]::new($false))
        Write-Host "Python erkannt: $resolved (Version $version)" -ForegroundColor Green
        return $true
    } catch {
        return $false
    }
}

function Try-CommandPython([string]$Command, [string[]]$PrefixArgs = @()) {
    try {
        # Absichtlich direkter nativer Aufruf statt Start-Process. So behandelt
        # PowerShell die Argumente genauso wie bei einem manuellen Aufruf.
        $invokeArgs = @($PrefixArgs) + @("-c", "import sys; print(sys.executable)")
        $output = & $Command @invokeArgs 2>$null
        $exit = $LASTEXITCODE
        if ($exit -ne 0 -or -not $output) { return $false }

        $actual = ($output | Select-Object -Last 1).ToString().Trim()
        return (Save-PythonPath $actual)
    } catch {
        return $false
    }
}

function Find-ExistingPython {
    # 1) Python Launcher. Wenn `py` in einer normalen CMD funktioniert,
    # funktioniert exakt dieser Aufruf ebenfalls.
    if (Try-CommandPython "py" @("-3.12")) { return $true }
    if (Try-CommandPython "py" @("-3")) { return $true }

    # 2) python/python3 aus PATH.
    if (Try-CommandPython "python") { return $true }
    if (Try-CommandPython "python3") { return $true }

    # 3) Bekannte Installationspfade. Keine Registry-Abhängigkeit nötig.
    $known = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python310\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Launcher\py.exe"),
        (Join-Path $env:ProgramFiles "Python312\python.exe"),
        (Join-Path $env:ProgramFiles "Python311\python.exe"),
        (Join-Path $env:ProgramFiles "Python310\python.exe")
    )

    foreach ($candidate in $known) {
        if (-not $candidate -or -not (Test-Path -LiteralPath $candidate)) { continue }
        if ($candidate.EndsWith("\py.exe", [System.StringComparison]::OrdinalIgnoreCase)) {
            if (Try-CommandPython $candidate @("-3.12")) { return $true }
            if (Try-CommandPython $candidate @("-3")) { return $true }
        } elseif (Save-PythonPath $candidate) {
            return $true
        }
    }

    return $false
}

# Alte/ungültige Auflösung nicht weiterverwenden.
Remove-Item $PythonPathFile -Force -ErrorAction SilentlyContinue

if (Find-ExistingPython) {
    exit 0
}

Write-Host ""
Write-Host "=== Python $PythonVersion wird eingerichtet ===" -ForegroundColor Cyan
Write-Host "Kein startbares Python 3.10+ wurde über py/python oder Standardpfade gefunden."

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
    default {
        throw "Nicht unterstützte Windows-Architektur '$arch'. Unterstützt werden x64 und ARM64."
    }
}

$tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("llmbench-python-" + [guid]::NewGuid().ToString("N"))
$installer = Join-Path $tmpDir $fileName
$url = "https://www.python.org/ftp/python/$PythonVersion/$fileName"
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null

try {
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

    Write-Host "Download: $url"
    Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
    if (-not (Test-Path -LiteralPath $installer)) {
        throw "Python-Installer wurde nicht heruntergeladen."
    }

    $actualSha256 = (Get-FileHash -Path $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualSha256 -ne $expectedSha256) {
        throw "SHA256-Prüfung fehlgeschlagen. Erwartet: $expectedSha256, erhalten: $actualSha256"
    }

    Write-Host "SHA256-Prüfung erfolgreich."
    Write-Host "Python-Installer wird ausgeführt..."

    # Standardmäßige Per-User-Installation. Launcher und PATH werden bewusst
    # aktiviert, damit Python sowohl sofort als auch bei späteren Starts
    # eindeutig auffindbar ist.
    $installArgs = @(
        "/quiet",
        "/log", "`"$InstallLog`"",
        "InstallAllUsers=0",
        "PrependPath=1",
        "AppendPath=1",
        "Include_launcher=1",
        "InstallLauncherAllUsers=0",
        "Include_pip=1",
        "Include_test=0",
        "Include_doc=0",
        "Shortcuts=0"
    )

    $proc = Start-Process -FilePath $installer -ArgumentList $installArgs -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        throw "Python-Installer fehlgeschlagen (Exitcode $($proc.ExitCode)). Log: $InstallLog"
    }

    # Der Installer aktualisiert PATH der laufenden PowerShell nicht immer.
    # Deshalb zuerst direkte Standardpfade und Launcherpfade prüfen.
    foreach ($attempt in 1..10) {
        if (Find-ExistingPython) {
            Write-Host "Python-Setup erfolgreich abgeschlossen." -ForegroundColor Green
            exit 0
        }
        Start-Sleep -Seconds 1
    }

    Write-Host ""
    Write-Host "Diagnose:" -ForegroundColor Yellow
    Write-Host "  where py:"
    & where.exe py 2>$null | ForEach-Object { Write-Host "    $_" }
    Write-Host "  where python:"
    & where.exe python 2>$null | ForEach-Object { Write-Host "    $_" }
    Write-Host "  Erwarteter Benutzerpfad:"
    Write-Host "    $(Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')"
    Write-Host "  Installationslog: $InstallLog"

    throw "Python-Installer meldete Erfolg, aber Python konnte danach nicht gestartet werden."
}
finally {
    Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue
}
