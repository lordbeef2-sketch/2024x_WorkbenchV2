[CmdletBinding()]
param(
    [string]$OutputDirectory,
    [string]$PipIndexUrl,
    [string]$PackageCaFile,
    [switch]$AllowUntrustedPackageHosts,
    [switch]$SkipFrontendInstall,
    [switch]$SkipTests,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Phase {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $Executable $($Arguments -join ' ')"
    }
}

function Test-PythonInterpreter {
    param([string]$Executable, [string[]]$Arguments = @())
    try {
        $value = & $Executable @Arguments -c "import platform,sys; print(f'{sys.version_info.major}.{sys.version_info.minor}|{platform.machine()}')"
        $parts = "$value".Trim().Split("|")
        return $parts.Count -eq 2 -and [version]$parts[0] -ge [version]"3.11"
    }
    catch {
        return $false
    }
}

function Get-BootstrapPython {
    $candidates = @()
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $candidates += ,@($py.Source, "-3.11")
        $candidates += ,@($py.Source, "-3")
    }
    foreach ($name in @("python3", "python")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) { $candidates += ,@($command.Source) }
    }
    foreach ($candidate in $candidates) {
        $executable = $candidate[0]
        $arguments = if ($candidate.Count -gt 1) { @($candidate[1..($candidate.Count - 1)]) } else { @() }
        if (Test-PythonInterpreter -Executable $executable -Arguments $arguments) {
            return [pscustomobject]@{ Executable = $executable; Arguments = $arguments }
        }
    }
    throw "Python 3.11 or newer with pip is required on the connected prep machine."
}

function Copy-DirectoryContents {
    param([string]$Source, [string]$Destination)
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        throw "Required directory was not found: $Source"
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $Destination -Recurse -Force
    }
}

function Get-PipNetworkArguments {
    $arguments = @()
    if (-not [string]::IsNullOrWhiteSpace($PipIndexUrl)) {
        $arguments += @("--index-url", $PipIndexUrl)
    }
    if (-not [string]::IsNullOrWhiteSpace($PackageCaFile)) {
        if (-not (Test-Path -LiteralPath $PackageCaFile -PathType Leaf)) { throw "Package CA file was not found: $PackageCaFile" }
        $arguments += @("--cert", (Resolve-Path -LiteralPath $PackageCaFile).Path)
    }
    if ($AllowUntrustedPackageHosts) {
        $arguments += @("--trusted-host", "pypi.org", "--trusted-host", "files.pythonhosted.org")
    }
    return $arguments
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = [System.IO.Path]::GetFullPath((Join-Path $scriptDir ".."))
$backendDir = Join-Path $rootDir "backend"
$frontendDir = Join-Path $rootDir "frontend"
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $scriptDir "artifacts"
}
$outputRoot = [System.IO.Path]::GetFullPath($OutputDirectory)
$bundleName = "TWC-Workbench-Offline-$((Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss'))"
$stageRoot = Join-Path $outputRoot $bundleName
$payloadRoot = Join-Path $stageRoot "payload"
$wheelhouse = Join-Path $stageRoot "wheelhouse"
$zipPath = Join-Path $outputRoot "$bundleName.zip"

if ((Test-Path -LiteralPath $stageRoot) -or (Test-Path -LiteralPath $zipPath)) {
    if (-not $Force) { throw "Output already exists. Rerun with -Force or choose another output directory." }
    Remove-Item -LiteralPath $stageRoot -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $zipPath -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Path $payloadRoot, $wheelhouse -Force | Out-Null

$python = Get-BootstrapPython
$pythonInfo = & $python.Executable @($python.Arguments) -c "import json,platform,sys; print(json.dumps({'version': platform.python_version(), 'major_minor': f'{sys.version_info.major}.{sys.version_info.minor}', 'architecture': platform.machine(), 'platform': platform.platform()}))"
$pythonMetadata = $pythonInfo | ConvertFrom-Json
$pipNetworkArguments = @(Get-PipNetworkArguments)
if ($AllowUntrustedPackageHosts) {
    Write-Warning "TLS verification is disabled only for pypi.org and files.pythonhosted.org during this prep run. Prefer -PackageCaFile or an approved -PipIndexUrl."
}

if (-not $SkipTests) {
    Write-Phase "Creating an isolated backend test environment"
    $testVenv = Join-Path $stageRoot ".test-venv"
    Invoke-Checked -Executable $python.Executable -Arguments (@($python.Arguments) + @("-m", "venv", $testVenv))
    $testPython = Join-Path $testVenv "Scripts\python.exe"
    Invoke-Checked -Executable $testPython -Arguments (@("-m", "pip", "install") + $pipNetworkArguments + @("pytest", "-e", $backendDir))
    Write-Phase "Running backend tests"
    Push-Location $backendDir
    try { Invoke-Checked -Executable $testPython -Arguments @("-m", "pytest", "tests", "-q") }
    finally { Pop-Location }
    Remove-Item -LiteralPath $testVenv -Recurse -Force
}

$npm = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npm) { throw "Node.js 20+ and npm are required on the connected prep machine to build frontend/dist." }
if (-not $SkipFrontendInstall) {
    Write-Phase "Installing locked frontend dependencies"
    Push-Location $frontendDir
    try {
        $npmArguments = @("ci")
        if (-not [string]::IsNullOrWhiteSpace($PackageCaFile)) { $npmArguments += "--cafile=$PackageCaFile" }
        if ($AllowUntrustedPackageHosts) { $npmArguments += "--strict-ssl=false" }
        Invoke-Checked -Executable $npm.Source -Arguments $npmArguments
    }
    finally { Pop-Location }
}
Write-Phase "Building the production frontend"
Push-Location $frontendDir
try { Invoke-Checked -Executable $npm.Source -Arguments @("run", "build") }
finally { Pop-Location }
if (-not (Test-Path -LiteralPath (Join-Path $frontendDir "dist\index.html"))) {
    throw "Frontend build did not produce frontend/dist/index.html."
}

Write-Phase "Collecting backend and dependency wheels"
$wheelSource = Join-Path $stageRoot ".wheel-source\backend"
Copy-DirectoryContents -Source (Join-Path $backendDir "app") -Destination (Join-Path $wheelSource "app")
Copy-Item -LiteralPath (Join-Path $backendDir "pyproject.toml") -Destination (Join-Path $wheelSource "pyproject.toml") -Force
Copy-Item -LiteralPath (Join-Path $backendDir "README.md") -Destination (Join-Path $wheelSource "README.md") -Force
Invoke-Checked -Executable $python.Executable -Arguments (@($python.Arguments) + @("-m", "pip", "wheel") + $pipNetworkArguments + @("--wheel-dir", $wheelhouse, $wheelSource))
Invoke-Checked -Executable $python.Executable -Arguments (@($python.Arguments) + @("-m", "pip", "download") + $pipNetworkArguments + @("--dest", $wheelhouse, "setuptools>=68", "wheel"))
Remove-Item -LiteralPath (Join-Path $stageRoot ".wheel-source") -Recurse -Force
$backendWheel = Get-ChildItem -LiteralPath $wheelhouse -Filter "twc_workbench_backend-*.whl" | Sort-Object Name -Descending | Select-Object -First 1
if (-not $backendWheel) { throw "The backend application wheel was not created." }

Write-Phase "Verifying the wheelhouse without internet access"
$verificationVenv = Join-Path $stageRoot ".verification-venv"
Invoke-Checked -Executable $python.Executable -Arguments (@($python.Arguments) + @("-m", "venv", $verificationVenv))
$verificationPython = Join-Path $verificationVenv "Scripts\python.exe"
Invoke-Checked -Executable $verificationPython -Arguments @("-m", "pip", "install", "--no-index", "--find-links", $wheelhouse, $backendWheel.FullName)
Invoke-Checked -Executable $verificationPython -Arguments @("-c", "import app,fastapi,httpx,pydantic_settings,uvicorn; print('offline wheelhouse import verification passed')")
Remove-Item -LiteralPath $verificationVenv -Recurse -Force

Write-Phase "Assembling the offline runtime payload"
Copy-DirectoryContents -Source (Join-Path $backendDir "app") -Destination (Join-Path $payloadRoot "backend\app")
Copy-Item -LiteralPath (Join-Path $backendDir ".env.example") -Destination (Join-Path $payloadRoot "backend\.env.example") -Force
Copy-DirectoryContents -Source (Join-Path $frontendDir "dist") -Destination (Join-Path $payloadRoot "frontend\dist")
foreach ($file in @("README.md", "CACHE_API.md")) {
    if (Test-Path -LiteralPath (Join-Path $rootDir $file)) {
        Copy-Item -LiteralPath (Join-Path $rootDir $file) -Destination (Join-Path $payloadRoot $file) -Force
    }
}
Copy-Item -LiteralPath (Join-Path $scriptDir "Offline-Installer.ps1") -Destination (Join-Path $stageRoot "Offline-Installer.ps1") -Force
Copy-Item -LiteralPath (Join-Path $scriptDir "README.md") -Destination (Join-Path $stageRoot "README.md") -Force

$commit = "unknown"
$git = Get-Command git -ErrorAction SilentlyContinue
if ($git) {
    try { $commit = (& $git.Source -C $rootDir rev-parse HEAD).Trim() } catch { }
}
$files = Get-ChildItem -LiteralPath $stageRoot -File -Recurse | Sort-Object FullName | ForEach-Object {
    $relativePath = $_.FullName.Substring($stageRoot.TrimEnd("\").Length + 1)
    [pscustomobject]@{
        path = $relativePath.Replace("\", "/")
        size = $_.Length
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$manifest = [ordered]@{
    schema_version = 1
    application = "TWC Workbench"
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    source_commit = $commit
    python_version = $pythonMetadata.version
    python_major_minor = $pythonMetadata.major_minor
    architecture = $pythonMetadata.architecture
    platform = $pythonMetadata.platform
    backend_wheel = $backendWheel.Name
    file_count = @($files).Count
    files = @($files)
}
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $stageRoot "offline-manifest.json") -Encoding utf8

Write-Phase "Creating the transferable ZIP"
Compress-Archive -Path (Join-Path $stageRoot "*") -DestinationPath $zipPath -CompressionLevel Optimal -Force
$zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$zipPath.sha256" -Value "$zipHash  $([System.IO.Path]::GetFileName($zipPath))" -Encoding ascii

Write-Host ""
Write-Host "Offline package created successfully." -ForegroundColor Green
Write-Host "Folder : $stageRoot"
Write-Host "ZIP    : $zipPath"
Write-Host "SHA256 : $zipHash"
Write-Host "Target : Windows $($pythonMetadata.architecture), Python $($pythonMetadata.major_minor)"
Write-Host "Transfer the ZIP and .sha256 file, extract the ZIP, then run Offline-Installer.ps1."
