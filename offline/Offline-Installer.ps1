[CmdletBinding()]
param(
    [string]$InstallPath,
    [Nullable[int]]$Port = $null,
    [string]$BindHost,
    [switch]$StartAfterInstall,
    [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Phase {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $Executable $($Arguments -join ' ')"
    }
}

function Test-PythonInterpreter {
    param([string]$Executable, [string[]]$Arguments = @())
    try {
        $value = & $Executable @Arguments -c "import platform,sys; print(f'{sys.version_info.major}.{sys.version_info.minor}|{platform.machine()}')"
        return "$value".Trim()
    }
    catch { return $null }
}

function Get-BootstrapPython {
    param([string]$RequiredVersion, [string]$RequiredArchitecture)
    $candidates = @()
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $candidates += ,@($py.Source, "-$RequiredVersion")
        $candidates += ,@($py.Source, "-3")
    }
    foreach ($name in @("python3", "python")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) { $candidates += ,@($command.Source) }
    }
    foreach ($candidate in $candidates) {
        $executable = $candidate[0]
        $arguments = if ($candidate.Count -gt 1) { @($candidate[1..($candidate.Count - 1)]) } else { @() }
        $identity = Test-PythonInterpreter -Executable $executable -Arguments $arguments
        if ($identity -eq "$RequiredVersion|$RequiredArchitecture") {
            return [pscustomobject]@{ Executable = $executable; Arguments = $arguments }
        }
    }
    throw "This bundle requires Python $RequiredVersion ($RequiredArchitecture). Install that exact Python line on the offline host and rerun the installer."
}

function Assert-SafeInstallPath {
    param([string]$Path)
    $full = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetPathRoot($full)
    if ([string]::IsNullOrWhiteSpace($full) -or $full -eq $root -or $full.Length -lt ($root.Length + 4)) {
        throw "Refusing unsafe installation path: $full"
    }
    return $full.TrimEnd("\")
}

function Remove-InstallChild {
    param([string]$InstallRoot, [string]$ChildPath)
    if (-not (Test-Path -LiteralPath $ChildPath)) { return }
    $root = [System.IO.Path]::GetFullPath($InstallRoot).TrimEnd("\") + "\"
    $child = [System.IO.Path]::GetFullPath($ChildPath)
    if (-not $child.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a path outside the installation root: $child"
    }
    Remove-Item -LiteralPath $child -Recurse -Force
}

function New-SessionSecret {
    $bytes = New-Object byte[] 48
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) }
    finally { $generator.Dispose() }
    return [Convert]::ToBase64String($bytes)
}

$bundleRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifestPath = Join-Path $bundleRoot "offline-manifest.json"
$payloadRoot = Join-Path $bundleRoot "payload"
$wheelhouse = Join-Path $bundleRoot "wheelhouse"
if (-not (Test-Path -LiteralPath $manifestPath)) { throw "offline-manifest.json is missing. Extract the complete offline ZIP before installing." }
if (-not (Test-Path -LiteralPath $payloadRoot -PathType Container)) { throw "The payload directory is missing." }
if (-not (Test-Path -LiteralPath $wheelhouse -PathType Container)) { throw "The wheelhouse directory is missing." }

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.schema_version -ne 1) { throw "Unsupported offline manifest schema: $($manifest.schema_version)" }
$knowledgeRoot = [System.IO.Path]::GetFullPath("$($manifest.three_ds_kb_path)")
$knowledgeController = Join-Path $knowledgeRoot "AGENTS.md"
$knowledgeManifest = Join-Path $knowledgeRoot "00_MACHINE_MANIFEST.md"
$knowledgeValidation = Join-Path $knowledgeRoot "00_VALIDATION.md"
foreach ($knowledgeCheck in @(
    @($knowledgeController, "$($manifest.three_ds_kb_controller_sha256)"),
    @($knowledgeManifest, "$($manifest.three_ds_kb_manifest_sha256)"),
    @($knowledgeValidation, "$($manifest.three_ds_kb_validation_sha256)")
)) {
    if (-not (Test-Path -LiteralPath $knowledgeCheck[0] -PathType Leaf)) {
        throw "The single authoritative 3DS KB is unavailable: $($knowledgeCheck[0])"
    }
    $knowledgeHash = (Get-FileHash -LiteralPath $knowledgeCheck[0] -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($knowledgeHash -ne $knowledgeCheck[1].ToLowerInvariant()) {
        throw "The authoritative 3DS KB control hash changed: $($knowledgeCheck[0])"
    }
}

Write-Phase "Verifying every offline package file"
foreach ($entry in $manifest.files) {
    $filePath = Join-Path $bundleRoot ($entry.path.Replace("/", "\"))
    if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) { throw "Offline package file is missing: $($entry.path)" }
    $item = Get-Item -LiteralPath $filePath
    if ($item.Length -ne [long]$entry.size) { throw "Offline package size check failed: $($entry.path)" }
    $actualHash = (Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne "$($entry.sha256)".ToLowerInvariant()) { throw "Offline package hash check failed: $($entry.path)" }
}

if ([string]::IsNullOrWhiteSpace($InstallPath)) {
    $baseInstallPath = if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { $env:ProgramData } else { $env:LOCALAPPDATA }
    $InstallPath = Join-Path $baseInstallPath "TWCWorkbench"
}
$installRoot = Assert-SafeInstallPath -Path $InstallPath
$python = Get-BootstrapPython -RequiredVersion $manifest.python_major_minor -RequiredArchitecture $manifest.architecture
$venvDir = Join-Path $installRoot ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$backendTarget = Join-Path $installRoot "backend"
$frontendTarget = Join-Path $installRoot "frontend"
$envTarget = Join-Path $backendTarget ".env"

Write-Phase "Installing the verified Workbench payload"
New-Item -ItemType Directory -Path $installRoot, $backendTarget, $frontendTarget -Force | Out-Null
$deploymentStage = Join-Path $installRoot ".offline-stage-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path (Join-Path $deploymentStage "backend"), (Join-Path $deploymentStage "frontend") -Force | Out-Null
try {
    Copy-Item -LiteralPath (Join-Path $payloadRoot "backend\app") -Destination (Join-Path $deploymentStage "backend\app") -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $payloadRoot "frontend\dist") -Destination (Join-Path $deploymentStage "frontend\dist") -Recurse -Force

    # All payload copies finish before the installed runtime is replaced. The
    # final moves stay on the same volume and therefore minimize the upgrade
    # window where a target directory is absent.
    Remove-InstallChild -InstallRoot $installRoot -ChildPath (Join-Path $backendTarget "app")
    Move-Item -LiteralPath (Join-Path $deploymentStage "backend\app") -Destination (Join-Path $backendTarget "app")
    Remove-InstallChild -InstallRoot $installRoot -ChildPath (Join-Path $frontendTarget "dist")
    Move-Item -LiteralPath (Join-Path $deploymentStage "frontend\dist") -Destination (Join-Path $frontendTarget "dist")
}
finally {
    Remove-InstallChild -InstallRoot $installRoot -ChildPath $deploymentStage
}
Copy-Item -LiteralPath (Join-Path $payloadRoot "backend\.env.example") -Destination (Join-Path $backendTarget ".env.example") -Force
foreach ($file in @("README.md", "CACHE_API.md")) {
    $source = Join-Path $payloadRoot $file
    if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination (Join-Path $installRoot $file) -Force }
}

if (-not (Test-Path -LiteralPath $envTarget)) {
    Copy-Item -LiteralPath (Join-Path $backendTarget ".env.example") -Destination $envTarget -Force
    $secret = New-SessionSecret
    $content = Get-Content -LiteralPath $envTarget -Raw
    $content = [regex]::Replace($content, '(?m)^SESSION_SECRET=.*$', "SESSION_SECRET=$secret")
    Write-Host "Created backend/.env with a new random SESSION_SECRET." -ForegroundColor Green
}
else {
    $content = Get-Content -LiteralPath $envTarget -Raw
    Write-Host "Preserved the existing backend/.env configuration." -ForegroundColor DarkGray
}
$knowledgeSetting = "THREE_DS_KB_PATH=$($knowledgeRoot.Replace('\', '/'))"
if ([regex]::IsMatch($content, '(?m)^THREE_DS_KB_PATH=.*$')) {
    $content = [regex]::Replace($content, '(?m)^THREE_DS_KB_PATH=.*$', $knowledgeSetting)
}
else {
    $content = $content.TrimEnd() + [Environment]::NewLine + $knowledgeSetting + [Environment]::NewLine
}
Set-Content -LiteralPath $envTarget -Value $content -Encoding utf8

Write-Phase "Installing Python dependencies strictly from the offline wheelhouse"
if ((Test-Path -LiteralPath $venvPython) -and (Test-PythonInterpreter -Executable $venvPython) -ne "$($manifest.python_major_minor)|$($manifest.architecture)") {
    Write-Host "Replacing a virtual environment that does not match this bundle." -ForegroundColor Yellow
    Remove-InstallChild -InstallRoot $installRoot -ChildPath $venvDir
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    Invoke-Checked -Executable $python.Executable -Arguments (@($python.Arguments) + @("-m", "venv", $venvDir))
}
$backendWheel = Join-Path $wheelhouse $manifest.backend_wheel
Invoke-Checked -Executable $venvPython -Arguments @("-m", "pip", "install", "--no-index", "--find-links", $wheelhouse, "--upgrade", $backendWheel)
Invoke-Checked -Executable $venvPython -Arguments @("-c", "import app,fastapi,httpx,pydantic_settings,uvicorn; print('offline installation import verification passed')")

$launcherPath = Join-Path $installRoot "Start-Workbench.ps1"
$launcher = @'
[CmdletBinding()]
param(
    [Nullable[int]]$Port = $null,
    [string]$BindHost = "",
    [switch]$NoBrowser
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$rootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $rootDir "backend"
$python = Join-Path $rootDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Offline Workbench virtual environment is missing. Rerun Offline-Installer.ps1." }
function Get-EnvValue([string]$Name) {
    $file = Join-Path $backendDir ".env"
    if (-not (Test-Path -LiteralPath $file)) { return $null }
    $pattern = '^\s*' + [regex]::Escape($Name) + '\s*=\s*(.*)\s*$'
    foreach ($line in Get-Content -LiteralPath $file) {
        if ($line -notmatch '^\s*#' -and $line -match $pattern) { return $matches[1].Trim().Trim('"').Trim("'") }
    }
    return $null
}
if ([string]::IsNullOrWhiteSpace($BindHost)) { $BindHost = Get-EnvValue "HOST" }
if ([string]::IsNullOrWhiteSpace($BindHost)) { $BindHost = "0.0.0.0" }
if ($null -eq $Port) { $configuredPort = Get-EnvValue "PORT"; $Port = if ($configuredPort) { [int]$configuredPort } else { 8000 } }
$url = "http://localhost:$Port"
$env:PYTHONPATH = $backendDir
$env:HOST = $BindHost
$env:PORT = "$Port"
$env:FRONTEND_ORIGIN = $url
if (-not $NoBrowser) {
    Start-Job -ScriptBlock {
        param($RootUrl)
        for ($attempt = 0; $attempt -lt 60; $attempt++) {
            Start-Sleep -Seconds 1
            try { Invoke-WebRequest -UseBasicParsing -Uri "$RootUrl/healthz" -TimeoutSec 2 | Out-Null; Start-Process $RootUrl; return } catch { }
        }
    } -ArgumentList $url | Out-Null
}
Write-Host "Starting TWC Workbench at $url" -ForegroundColor Green
Push-Location $backendDir
try { & $python -m uvicorn app.main:app --host $BindHost --port $Port --no-access-log }
finally { Pop-Location }
'@
Set-Content -LiteralPath $launcherPath -Value $launcher -Encoding utf8

$installRecord = [ordered]@{
    installed_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    source_commit = $manifest.source_commit
    offline_bundle_created_at_utc = $manifest.created_at_utc
    python_major_minor = $manifest.python_major_minor
    architecture = $manifest.architecture
}
$installRecord | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $installRoot "offline-install.json") -Encoding utf8

Write-Host ""
Write-Host "TWC Workbench offline installation completed." -ForegroundColor Green
Write-Host "Install path : $installRoot"
Write-Host "Configuration: $envTarget"
Write-Host "Data         : $(Join-Path $backendTarget 'data')"
Write-Host "Start command: powershell -ExecutionPolicy Bypass -File `"$launcherPath`""

if ($StartAfterInstall) {
    $arguments = @("-ExecutionPolicy", "Bypass", "-File", $launcherPath)
    if ($null -ne $Port) { $arguments += @("-Port", "$Port") }
    if (-not [string]::IsNullOrWhiteSpace($BindHost)) { $arguments += @("-BindHost", $BindHost) }
    if ($NoBrowser) { $arguments += "-NoBrowser" }
    & powershell.exe @arguments
}
