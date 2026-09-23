[CmdletBinding()]
param(
    [string]$Config = "benchmark.yaml",
    [string]$LlamaCppTag = "",
    [switch]$SetupOnly,
    [switch]$ForceUpdateLlamaCpp
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$ToolsDir = Join-Path $Root "tools"
$LlamaDir = Join-Path $ToolsDir "llama.cpp"
$ModelsDir = Join-Path $Root "models"
$VenvDir = Join-Path $Root ".venv"
$StateFile = Join-Path $LlamaDir ".llama-build.json"
$PinFile = Join-Path $Root "llama-cpp-version.txt"

Import-Module (Join-Path $PSScriptRoot "lib\UI.psm1") -Force -DisableNameChecking
Import-Module (Join-Path $PSScriptRoot "lib\LlamaCpp.psm1") -Force -DisableNameChecking
Initialize-LlmbenchUI
$ProbeLog = Join-Path $Root ".runtime\llama-probe.log"

function Get-PythonCommand {
    $candidates = @(
        @{ Exe = "py"; Args = @("-3.12") },
        @{ Exe = "py"; Args = @("-3") },
        @{ Exe = "python"; Args = @() }
    )
    foreach ($candidate in $candidates) {
        try {
            $cmd = Get-Command $candidate.Exe -ErrorAction Stop
            $pyArgs = @($candidate.Args) + @("-c", "import sys; assert sys.version_info >= (3,10); print(sys.executable)")
            $path = & $cmd.Source @pyArgs 2>$null
            if ($LASTEXITCODE -eq 0 -and $path) {
                return ($path | Select-Object -Last 1).Trim()
            }
        } catch { }
    }
    return $null
}

function Invoke-GitHubApi([string]$Url, [switch]$AllowMissing) {
    $headers = @{ "User-Agent" = "llm-server-benchmark-installer"; "Accept" = "application/vnd.github+json" }
    if ($env:GITHUB_TOKEN) { $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN" }
    try {
        return Invoke-RestMethod -Uri $Url -Headers $headers
    } catch {
        $status = $null
        if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
        if ($status -eq 404 -and $AllowMissing) { return $null }
        if ($status -eq 403) {
            throw (T 'core.github_403')
        }
        throw (T 'core.github_failed' $Url $_.Exception.Message)
    }
}

function Assert-LlamaTag([string]$Value, [string]$Origin) {
    if ($Value -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$' -or $Value -match '\.(ya?ml|txt|json|exe|bat|ps1)$') {
        throw (T 'core.invalid_tag' $Value $Origin)
    }
    return $Value
}

function Get-PinnedLlamaTag {
    if ($LlamaCppTag) { return Assert-LlamaTag $LlamaCppTag.Trim() "Parameter -LlamaCppTag" }
    if ($env:LLMBENCH_LLAMACPP_TAG) { return Assert-LlamaTag $env:LLMBENCH_LLAMACPP_TAG.Trim() "LLMBENCH_LLAMACPP_TAG" }
    if (Test-Path $PinFile) {
        foreach ($line in (Get-Content $PinFile)) {
            $value = $line.Trim()
            if ($value -and -not $value.StartsWith("#")) {
                return Assert-LlamaTag $value "llama-cpp-version.txt"
            }
        }
    }
    return $null
}

function Get-ReleaseCandidates {
    $pinned = Get-PinnedLlamaTag
    if ($pinned) {
        Write-UiInfo (T 'core.pinned_build' $pinned)
        $release = Invoke-GitHubApi "https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/$pinned" -AllowMissing
        if (-not $release) { throw (T 'core.release_missing' $pinned) }
        return @($release)
    }

    $all = @()
    foreach ($page in 1..3) {
        $releases = Invoke-GitHubApi "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30&page=$page"
        if (-not $releases -or @($releases).Count -eq 0) { break }
        $all += @($releases | Where-Object { -not $_.draft })
    }
    return @($all)
}

function Test-ExistingLlamaInstall($Nvidia) {
    $benchExe = Join-Path $LlamaDir "llama-bench.exe"
    $serverExe = Join-Path $LlamaDir "llama-server.exe"
    if (-not (Test-Path $benchExe) -or -not (Test-Path $serverExe) -or -not (Test-Path $StateFile)) {
        return $false
    }

    try { $state = Get-Content $StateFile -Raw | ConvertFrom-Json } catch { return $false }

    # Wenn ein moderner CUDA-13-faehiger Treiber vorhanden ist, einen alten
    # cuda-12-Build nicht dauerhaft festhalten. Neu installieren und CUDA 13 nutzen.
    # Nicht, wenn cuda-12 bewusst als Ausweichloesung installiert wurde (fallback_from),
    # weil der CUDA-13-Build hier abgestuerzt ist - sonst Endlosschleife bei jedem Start.
    if ($Nvidia -and $Nvidia.SupportedCudaMajor -ge 13 -and $state.backend -like "cuda-12*" -and -not $state.fallback_from) {
        Write-UiStep (T 'core.replace_cuda12' $state.backend)
        return $false
    }

    $probe = Invoke-LlamaBenchProbe $benchExe
    if (-not $probe.Success) {
        Write-UiWarn (T 'core.existing_broken' (Format-LlamaExitCode $probe.ExitCode))
        return $false
    }

    Write-UiOk (T 'core.llama_installed_already' $LlamaDir)
    Write-UiInfo "Build: $($state.tag) / $($state.backend)"
    if ($probe.DeviceLine) { Write-UiInfo (T 'core.probe' $probe.DeviceLine.Trim()) }
    return $true
}

function Install-LlamaCpp {
    $nvidia = Get-NvidiaInfo

    if (-not $ForceUpdateLlamaCpp -and (Test-ExistingLlamaInstall $nvidia)) { return }

    Write-UiSection (T 'core.llama_setup')
    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null

    if ($nvidia) {
        $family = if ($nvidia.SupportedCudaMajor) { "CUDA-$($nvidia.SupportedCudaMajor).x" } else { T 'core.unknown' }
        Write-UiOk (T 'core.nvidia_found' $nvidia.Driver $nvidia.Cuda $family)
        if ($nvidia.GpuName) {
            $cc = if ($nvidia.ComputeCap) { $nvidia.ComputeCap } else { T 'core.unknown' }
            Write-UiInfo (T 'core.nvidia_gpu' $nvidia.GpuName $cc)
        }
    } else {
        Write-UiWarn (T 'core.no_nvidia')
    }

    $preference = Get-LlamaBuildPreference
    $selection = Select-LlamaRelease -Releases (Get-ReleaseCandidates) -Nvidia $nvidia -Preference $preference
    $release = $selection.Release
    $candidates = @($selection.Candidates)
    Write-UiInfo (T 'core.candidates' $release.tag_name (($candidates | ForEach-Object { $_.Backend }) -join ' -> '))

    $result = Install-LlamaFromCandidates -Candidates $candidates -LlamaDir $LlamaDir -ProbeLog $ProbeLog
    $chosen = $result.Candidate
    $probe = $result.Probe

    if ($probe.DeviceLine) {
        Write-UiOk (T 'core.probe_ok_device' $probe.DeviceLine.Trim())
    } else {
        Write-UiOk (T 'core.probe_ok')
    }

    $preferred = $candidates[0]
    $fallbackFrom = $null
    $fallbackReason = $null
    if ($chosen.Backend -ne $preferred.Backend) {
        $fallbackFrom = $preferred.Backend
        $fallbackReason = ($result.Attempts | ForEach-Object { "$($_.Backend): $($_.Reason)" }) -join '; '
        Write-UiWarn (T 'core.fallback_used' $chosen.Backend $preferred.Backend)
        Write-UiInfo (T 'core.probe_log' $ProbeLog)
    }
    if ($nvidia -and $chosen.Kind -ne 'cuda') {
        Write-UiWarn (T 'core.not_cuda_warning' $chosen.Backend)
    }

    $state = [ordered]@{
        tag = $release.tag_name
        backend = $chosen.Backend
        installed_at = (Get-Date).ToString("o")
        main_asset = $chosen.MainAsset.name
        runtime_asset = if ($chosen.RuntimeAsset) { $chosen.RuntimeAsset.name } else { $null }
        nvidia_driver = if ($nvidia) { $nvidia.Driver } else { $null }
        gpu_name = if ($nvidia) { $nvidia.GpuName } else { $null }
        compute_capability = if ($nvidia -and $nvidia.ComputeCap) { $nvidia.ComputeCap.ToString() } else { $null }
        cuda_compatibility = if ($nvidia -and $nvidia.Cuda) { $nvidia.Cuda.ToString() } else { $null }
        cuda_family = if ($nvidia) { $nvidia.SupportedCudaMajor } else { $null }
        # Merkt sich, dass der bevorzugte Build hier nicht lief - sonst wuerde
        # Test-ExistingLlamaInstall ihn beim naechsten Start erneut installieren.
        fallback_from = $fallbackFrom
        fallback_reason = $fallbackReason
    }
    $state | ConvertTo-Json | Set-Content -Path $StateFile -Encoding UTF8
    Write-UiOk (T 'core.llama_installed' $release.tag_name)

    if (-not (Get-PinnedLlamaTag)) {
        Write-UiWarn (T 'core.pin_hint' $release.tag_name)
    }
}

Write-UiSection (T 'core.system_check')
$PythonExe = Get-PythonCommand
if (-not $PythonExe) {
    throw (T 'core.python_not_in_path')
}
Write-UiOk "Python: $PythonExe"

Write-UiSection (T 'setup.section_packages')
if (-not (Test-Path $VenvDir)) {
    Write-UiStep (T 'setup.venv_create')
    & $PythonExe -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw (T 'core.venv_failed') }
}
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $VenvPython)) { throw (T 'core.venv_python_missing') }
Write-UiStep (T 'setup.pip_install')
& $VenvPython -m pip install --quiet --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw (T 'core.pip_failed') }
& $VenvPython -m pip install --quiet -e "."
if ($LASTEXITCODE -ne 0) { throw (T 'core.deps_failed') }
Write-UiOk (T 'setup.packages_ready')

Install-LlamaCpp

Write-UiSection (T 'setup.section_config')
New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null
& $VenvPython -m llmbench bootstrap --config $Config --root $Root --llama-dir $LlamaDir --models-dir $ModelsDir
if ($LASTEXITCODE -ne 0) { throw (T 'core.bootstrap_failed') }

$Models = Get-ChildItem -Path $ModelsDir -Filter "*.gguf" -Recurse -File -ErrorAction SilentlyContinue
if (-not $Models -or $Models.Count -eq 0) {
    Write-UiDone (T 'core.setup_done') @((T 'core.no_models'), $ModelsDir)
    exit 0
}

Write-UiSection (T 'start.models_title' $Models.Count)
$Models | ForEach-Object { Write-UiInfo "- $($_.Name)" }

Write-UiSection (T 'start.doctor_title')
& $VenvPython -m llmbench doctor --config $Config
if ($LASTEXITCODE -ne 0) { throw (T 'start.doctor_failed') }

if ($SetupOnly) {
    Write-UiDone (T 'core.setup_done')
    exit 0
}

$options = Read-BenchmarkOptions -NoStress
& $VenvPython -m llmbench run --config $Config --duration $options.Duration --hardware $options.Hardware
if ($LASTEXITCODE -ne 0) { throw (T 'start.benchmark_failed' $LASTEXITCODE) }
