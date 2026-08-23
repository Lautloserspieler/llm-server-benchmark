param()

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Root = Split-Path -Parent $PSScriptRoot
$RuntimeRoot = Join-Path $Root ".runtime"
$PythonHome = Join-Path $RuntimeRoot "python"
$PythonExe = Join-Path $PythonHome "python.exe"
$PythonVersion = "3.12.10"

function Test-Python([string]$Exe, [string[]]$PrefixArgs = @()) {
    try {
        $args = @($PrefixArgs) + @("-c", "import sys; assert sys.version_info >= (3,10); print(sys.executable)")
        $out = & $Exe @args 2>$null
        return ($LASTEXITCODE -eq 0 -and $out)
    } catch {
        return $false
    }
}

# Bereits projektlokal installiert?
if ((Test-Path $PythonExe) -and (Test-Python $PythonExe)) {
    Write-Host "Python Runtime vorhanden: $PythonExe"
    exit 0
}

# Geeignetes System-Python vorhanden? Dann muss nichts heruntergeladen werden.
$candidates = @(
    @{ Exe = "py"; Args = @("-3.12") },
    @{ Exe = "py"; Args = @("-3") },
    @{ Exe = "python"; Args = @() }
)
foreach ($candidate in $candidates) {
    try {
        $cmd = Get-Command $candidate.Exe -ErrorAction Stop
        if (Test-Python $cmd.Source $candidate.Args) {
            Write-Host "Geeignetes System-Python vorhanden: $($cmd.Source)"
            exit 0
        }
    } catch { }
}

Write-Host ""
Write-Host "=== Python wird ohne winget eingerichtet ===" -ForegroundColor Cyan
Write-Host "Es wird Python $PythonVersion direkt von python.org geladen und nur für dieses Projekt installiert."

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

$url = "https://www.python.org/ftp/python/$PythonVersion/$fileName"
$tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("llmbench-python-" + [guid]::NewGuid().ToString("N"))
$installer = Join-Path $tmpDir $fileName

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null

try {
    # Ältere Windows-/PowerShell-Konfigurationen benötigen explizit TLS 1.2.
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    } catch { }

    Write-Host "Download: $url"
    Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing

    if (-not (Test-Path $installer)) {
        throw "Der Python-Installer wurde nicht heruntergeladen."
    }

    $actualSha256 = (Get-FileHash -Path $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualSha256 -ne $expectedSha256) {
        throw "SHA256-Prüfung des Python-Installers fehlgeschlagen. Erwartet: $expectedSha256, erhalten: $actualSha256"
    }
    Write-Host "SHA256-Prüfung erfolgreich."

    if (Test-Path $PythonHome) {
        Remove-Item -Recurse -Force $PythonHome
    }
    New-Item -ItemType Directory -Force -Path $PythonHome | Out-Null

    $installArgs = @(
        "/quiet",
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
        throw "Der offizielle Python-Installer ist mit Exitcode $($proc.ExitCode) fehlgeschlagen."
    }

    if (-not (Test-Path $PythonExe)) {
        throw "Python wurde installiert, aber '$PythonExe' wurde nicht gefunden."
    }
    if (-not (Test-Python $PythonExe)) {
        throw "Die projektlokale Python-Installation konnte nicht gestartet werden."
    }

    & $PythonExe -m ensurepip --upgrade | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "pip konnte in der projektlokalen Python-Installation nicht initialisiert werden."
    }

    Write-Host "Python $PythonVersion wurde erfolgreich projektlokal installiert:"
    Write-Host "  $PythonExe" -ForegroundColor Green
    exit 0
}
finally {
    Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue
}
