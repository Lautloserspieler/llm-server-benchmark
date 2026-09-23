# Gemeinsame Terminal-Oberflaeche und Sprachsystem fuer alle Windows-Skripte.
#
# Texte stehen nicht in den Skripten, sondern in scripts\locales\<lang>.psd1
# und werden mit `T <schluessel> arg1 arg2` geholt. Die Sprache wird einmal
# ganz am Anfang gewaehlt (Select-LlmbenchLanguage), in .runtime\language
# gespeichert und als LLMBENCH_LANG an Python und Docker weitergereicht.

$script:Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$script:LocalesDir = Join-Path (Split-Path -Parent $PSScriptRoot) 'locales'
$script:Lang = 'de'
$script:Texts = @{}
$script:Supported = @('de', 'en')

function Get-LanguageFile { Join-Path $script:Root '.runtime\language' }

function ConvertTo-LlmbenchLanguage([string]$Value) {
    if (-not $Value) { return $null }
    $v = $Value.Trim().ToLowerInvariant()
    if ($v.Length -gt 2) { $v = $v.Substring(0, 2) }
    if ($script:Supported -contains $v) { return $v }
    return $null
}

function Get-LlmbenchLanguage {
    $lang = ConvertTo-LlmbenchLanguage $env:LLMBENCH_LANG
    if ($lang) { return $lang }
    $file = Get-LanguageFile
    if (Test-Path -LiteralPath $file) {
        $lang = ConvertTo-LlmbenchLanguage ((Get-Content -LiteralPath $file -Raw -ErrorAction SilentlyContinue) -as [string])
        if ($lang) { return $lang }
    }
    return $null
}

function Import-LlmbenchTexts([string]$Lang) {
    # Deutsch ist die Referenz; fehlt ein Schluessel in einer anderen Sprache,
    # erscheint der deutsche Text statt eines leeren Strings.
    $texts = Import-PowerShellDataFile (Join-Path $script:LocalesDir 'de.psd1')
    if ($Lang -ne 'de') {
        $other = Import-PowerShellDataFile (Join-Path $script:LocalesDir "$Lang.psd1")
        foreach ($key in $other.Keys) { $texts[$key] = $other[$key] }
    }
    return $texts
}

function Set-LlmbenchLanguage([string]$Lang, [switch]$NoExport) {
    $script:Lang = if (ConvertTo-LlmbenchLanguage $Lang) { ConvertTo-LlmbenchLanguage $Lang } else { 'de' }
    $script:Texts = Import-LlmbenchTexts $script:Lang
    # Nur eine tatsaechlich gewaehlte Sprache weiterreichen - sonst wuerde
    # Select-LlmbenchLanguage die Frage faelschlich ueberspringen.
    if (-not $NoExport) { $env:LLMBENCH_LANG = $script:Lang }
}

function Initialize-LlmbenchUI {
    $lang = Get-LlmbenchLanguage
    if ($lang) { Set-LlmbenchLanguage $lang } else { Set-LlmbenchLanguage 'de' -NoExport }
    try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
}

function Select-LlmbenchLanguage {
    # Fragt nur, wenn noch keine Sprache gewaehlt wurde. Die Frage selbst ist
    # zweisprachig, weil die Sprache ja noch unbekannt ist.
    $lang = Get-LlmbenchLanguage
    if (-not $lang) {
        Write-Host ''
        Write-Host '  Sprache / Language' -ForegroundColor Cyan
        Write-Host '    1) Deutsch'
        Write-Host '    2) English'
        $answer = ''
        if (-not [Console]::IsInputRedirected) { $answer = Read-Host '  Auswahl / Choice [1]' }
        $lang = if ($answer -match '^\s*(2|en)') { 'en' } else { 'de' }
        $file = Get-LanguageFile
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $file) | Out-Null
        [System.IO.File]::WriteAllText($file, "$lang`n", [System.Text.UTF8Encoding]::new($false))
    }
    Set-LlmbenchLanguage $lang
    return $lang
}

function T {
    param([Parameter(Mandatory = $true, Position = 0)][string]$Key,
          [Parameter(ValueFromRemainingArguments = $true)][object[]]$Arguments)
    $text = $script:Texts[$Key]
    if ($null -eq $text) { return "<$Key>" }
    if ($Arguments -and $Arguments.Count -gt 0) { return ($text -f $Arguments) }
    return $text
}

# --------------------------------------------------------------- Ausgabe

function Write-UiHeader([string]$Title, [string]$Subtitle = '') {
    $width = [Math]::Max(52, [Math]::Max($Title.Length, $Subtitle.Length) + 6)
    $line = [string]::new([char]0x2500, $width)
    Write-Host ''
    Write-Host ("  " + [char]0x250C + $line + [char]0x2510) -ForegroundColor DarkCyan
    Write-Host ("  " + [char]0x2502 + ("  " + $Title).PadRight($width) + [char]0x2502) -ForegroundColor Cyan
    if ($Subtitle) {
        Write-Host ("  " + [char]0x2502 + ("  " + $Subtitle).PadRight($width) + [char]0x2502) -ForegroundColor DarkGray
    }
    Write-Host ("  " + [char]0x2514 + $line + [char]0x2518) -ForegroundColor DarkCyan
}

function Write-UiSection([string]$Title) {
    $rest = [Math]::Max(4, 50 - $Title.Length)
    Write-Host ''
    Write-Host ("  " + [string]::new([char]0x2500, 2) + " $Title " + [string]::new([char]0x2500, $rest)) -ForegroundColor Cyan
}

function Write-UiBadge([string]$Badge, [string]$Color, [string]$Message) {
    Write-Host '  ' -NoNewline
    Write-Host $Badge.PadRight(4) -ForegroundColor $Color -NoNewline
    Write-Host " $Message"
}

function Write-UiStep([string]$Message) { Write-UiBadge '[+]' 'Cyan' $Message }
function Write-UiOk([string]$Message) { Write-UiBadge '[OK]' 'Green' $Message }
function Write-UiWarn([string]$Message) { Write-UiBadge '[!]' 'Yellow' $Message }
function Write-UiFail([string]$Message) { Write-UiBadge '[X]' 'Red' $Message }
function Write-UiInfo([string]$Message) { Write-Host "       $Message" -ForegroundColor Gray }

function Write-UiDone([string]$Title, [string[]]$Lines = @()) {
    Write-Host ''
    Write-Host ("  " + [char]0x221A + " $Title") -ForegroundColor Green
    foreach ($l in $Lines) { Write-Host "    $l" }
    Write-Host ''
}

# --------------------------------------------------------------- Eingabe

function Test-UiInteractive { return -not [Console]::IsInputRedirected }

function Confirm-UiYesNo {
    param([string]$Question, [switch]$DefaultYes)
    $yes = T 'ui.yes_key'
    $hint = if ($DefaultYes) { "[$($yes.ToUpper())/n]" } else { "[$yes/N]" }
    if (-not (Test-UiInteractive)) { return [bool]$DefaultYes }
    Write-Host '  ' -NoNewline
    Write-Host '[?]' -ForegroundColor Magenta -NoNewline
    $answer = Read-Host " $Question $hint"
    if (-not $answer) { return [bool]$DefaultYes }
    return ($answer -match '^\s*[jJyY]')
}

function Confirm-Install([string]$What) {
    # LLMBENCH_AUTO_INSTALL=1 beantwortet alle Rueckfragen mit Ja, =0 mit Nein.
    if ($env:LLMBENCH_AUTO_INSTALL -eq '1') {
        Write-UiStep (T 'ui.auto_install' $What)
        return $true
    }
    if ($env:LLMBENCH_AUTO_INSTALL -eq '0') { return $false }
    if (-not (Test-UiInteractive)) { return $false }
    return (Confirm-UiYesNo (T 'ui.install_question' $What) -DefaultYes)
}

function Read-UiChoice {
    # Nummeriertes Menue; liefert den 1-basierten Index der Auswahl.
    param([string]$Question, [string[]]$Options, [int]$Default = 1)
    Write-Host ''
    Write-Host "  $Question" -ForegroundColor White
    for ($i = 0; $i -lt $Options.Count; $i++) {
        $marker = if (($i + 1) -eq $Default) { '>' } else { ' ' }
        Write-Host ("   $marker {0}) {1}" -f ($i + 1), $Options[$i]) -ForegroundColor $(if (($i + 1) -eq $Default) { 'Cyan' } else { 'Gray' })
    }
    if (-not (Test-UiInteractive)) { return $Default }
    $answer = Read-Host ("  " + (T 'ui.choice_prompt' $Options.Count $Default))
    $n = 0
    if ([int]::TryParse($answer, [ref]$n) -and $n -ge 1 -and $n -le $Options.Count) { return $n }
    return $Default
}

function Read-BenchmarkOptions {
    # Gemeinsames Startmenue fuer nativen und Docker-Lauf.
    param([switch]$NoStress)
    Write-UiSection (T 'run.title')
    $d = Read-UiChoice (T 'run.duration_question') @((T 'run.duration_short'), (T 'run.duration_medium'), (T 'run.duration_long')) 2
    $duration = @('short', 'medium', 'long')[$d - 1]
    $h = Read-UiChoice (T 'run.hardware_question') @((T 'run.hardware_cpu'), (T 'run.hardware_gpu'), (T 'run.hardware_both')) 3
    $hardware = @('cpu', 'gpu', 'both')[$h - 1]
    $stress = $false
    if (-not $NoStress) {
        Write-Host ''
        $stress = Confirm-UiYesNo (T 'run.stress_question')
    }
    Write-Host ''
    Write-UiInfo (T 'run.selection' $duration $hardware $(if ($stress) { T 'ui.yes' } else { T 'ui.no' }))
    return [pscustomobject]@{ Duration = $duration; Hardware = $hardware; Stress = $stress }
}

# --------------------------------------------------------------- Download

function Format-UiBytes([double]$Bytes) {
    if ($Bytes -ge 1GB) { return ('{0:N1} GB' -f ($Bytes / 1GB)) }
    return ('{0:N1} MB' -f ($Bytes / 1MB))
}

function Invoke-UiDownload {
    # Download mit eigenem Fortschrittsbalken (Prozent, Menge, Tempo, Restzeit).
    # Invoke-WebRequest zeigt unter Windows PowerShell keinen brauchbaren
    # Fortschritt und ist mit aktivem Fortschritt sehr langsam.
    param([string]$Url, [string]$OutFile, [string]$Label = '')
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }
    if (-not $Label) { $Label = Split-Path -Leaf $OutFile }
    Write-UiStep (T 'ui.download' $Label)
    $request = [System.Net.HttpWebRequest]::Create($Url)
    $request.UserAgent = 'llm-server-benchmark-installer'
    $response = $request.GetResponse()
    try {
        $total = [double]$response.ContentLength
        $inStream = $response.GetResponseStream()
        $outStream = [System.IO.File]::Create($OutFile)
        try {
            $buffer = New-Object byte[] 262144
            $done = 0.0
            $watch = [System.Diagnostics.Stopwatch]::StartNew()
            $lastDraw = -1.0
            while (($read = $inStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                $outStream.Write($buffer, 0, $read)
                $done += $read
                $elapsed = $watch.Elapsed.TotalSeconds
                if (($elapsed - $lastDraw) -ge 0.25) {
                    $lastDraw = $elapsed
                    Write-UiProgress $done $total $elapsed
                }
            }
            Write-UiProgress $done $(if ($total -gt 0) { $total } else { $done }) $watch.Elapsed.TotalSeconds
            Write-Host ''
        } finally {
            $outStream.Dispose()
            $inStream.Dispose()
        }
    } finally {
        $response.Dispose()
    }
}

function Write-UiProgress([double]$Done, [double]$Total, [double]$Elapsed) {
    $speed = if ($Elapsed -gt 0) { $Done / $Elapsed } else { 0 }
    $width = 28
    if ($Total -gt 0) {
        $ratio = [Math]::Min(1.0, $Done / $Total)
        $filled = [int][Math]::Round($ratio * $width)
        $bar = ([string]::new([char]0x2588, $filled)) + ([string]::new([char]0x2591, $width - $filled))
        $eta = if ($speed -gt 0) { [TimeSpan]::FromSeconds([Math]::Max(0, ($Total - $Done) / $speed)).ToString('mm\:ss') } else { '--:--' }
        $text = ("       {0} {1,3:N0}%  {2} / {3}  {4}/s  {5}" -f $bar, ($ratio * 100), (Format-UiBytes $Done), (Format-UiBytes $Total), (Format-UiBytes $speed), $eta)
    } else {
        $text = ("       {0}  {1}/s" -f (Format-UiBytes $Done), (Format-UiBytes $speed))
    }
    Write-Host ("`r" + $text.PadRight(90)) -NoNewline -ForegroundColor Cyan
}

# --------------------------------------------------------------- Neustart

function Get-ResumeCommand {
    # Befehl fuer den einmaligen RunOnce-Eintrag nach dem Neustart.
    param([string]$Launcher = 'setup.bat')
    $launcherPath = Join-Path $script:Root $Launcher
    # Einstellungen, die nur in dieser Sitzung gesetzt wurden (z. B. ein
    # erzwungener Docker-Modus), muessen den Neustart ueberleben - sonst
    # liefe die Fortsetzung im Auto-Modus und fiele ggf. auf nativ zurueck.
    $prefix = ''
    foreach ($name in 'LLMBENCH_EXECUTION_MODE', 'LLMBENCH_AUTO_INSTALL', 'LLMBENCH_LANG') {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ($value -and $value -match '^[A-Za-z0-9_-]+$') { $prefix += 'set "{0}={1}" && ' -f $name, $value }
    }
    # cmd /c entfernt die aeusseren Anfuehrungszeichen; die inneren bleiben
    # fuer Pfade mit Leerzeichen erhalten.
    return ('cmd.exe /c "{0}cd /d "{1}" && "{2}""' -f $prefix, $script:Root, $launcherPath)
}

function Invoke-RebootFlow {
    # Einheitlicher Ablauf, wenn eine Installation einen Neustart braucht:
    # Hinweis zeigen, auf Wunsch das Starter-Skript einmalig nach der naechsten
    # Anmeldung weiterlaufen lassen (HKCU RunOnce) und auf Wunsch sofort neu starten.
    param([string]$Launcher = 'setup.bat')
    Write-Host ''
    Write-UiWarn (T 'reboot.title')
    Write-UiInfo (T 'reboot.hint' $Launcher)
    Write-Host ''
    if (-not (Test-UiInteractive)) { return }

    if (Confirm-UiYesNo (T 'reboot.resume_question') -DefaultYes) {
        $command = Get-ResumeCommand $Launcher
        try {
            $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce'
            if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null }
            Set-ItemProperty -Path $key -Name 'LLMServerBenchmark' -Value $command
            Write-UiOk (T 'reboot.resume_registered')
        } catch {
            Write-UiWarn (T 'reboot.resume_failed' $_.Exception.Message)
        }
    }
    if (Confirm-UiYesNo (T 'reboot.restart_now')) {
        Restart-Computer -Force
    }
}

Export-ModuleMember -Function T, Invoke-RebootFlow, Get-ResumeCommand, Initialize-LlmbenchUI, Select-LlmbenchLanguage, Get-LlmbenchLanguage, Set-LlmbenchLanguage,
    Write-UiHeader, Write-UiSection, Write-UiStep, Write-UiOk, Write-UiWarn, Write-UiFail, Write-UiInfo, Write-UiDone,
    Confirm-UiYesNo, Confirm-Install, Read-UiChoice, Read-BenchmarkOptions, Invoke-UiDownload, Test-UiInteractive
