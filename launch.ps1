[CmdletBinding()]
param(
    [Nullable[int]]$Port = $null,
    [string]$BindHost,
    [switch]$NoBrowser,
    [switch]$PrepareOnly,
    [switch]$SkipInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Phase {
    param([string]$Message)

    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-PythonInterpreter {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [string[]]$Arguments = @()
    )

    try {
        $versionText = & $Executable @Arguments -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
        return [version]$versionText -ge [version]"3.11"
    }
    catch {
        return $false
    }
}

function Get-BootstrapPython {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    $candidates = @()
    if ($pyLauncher) {
        $candidates += ,@($pyLauncher.Source, "-3.11")
        $candidates += ,@($pyLauncher.Source, "-3")
    }

    $python3Command = Get-Command python3 -ErrorAction SilentlyContinue
    if ($python3Command) {
        $candidates += ,@($python3Command.Source)
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $candidates += ,@($pythonCommand.Source)
    }

    foreach ($candidate in $candidates) {
        $executable = $candidate[0]
        $arguments = if ($candidate.Count -gt 1) { $candidate[1..($candidate.Count - 1)] } else { @() }
        if (Test-PythonInterpreter -Executable $executable -Arguments $arguments) {
            return $candidate
        }
    }

    throw "Python 3.11 or newer is required but was not found on PATH."
}

function Get-EnvFileValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if (-not (Test-Path $FilePath)) {
        return $null
    }

    $pattern = '^\s*' + [regex]::Escape($Name) + '\s*=\s*(.*)\s*$'
    foreach ($line in Get-Content -LiteralPath $FilePath) {
        if ([string]::IsNullOrWhiteSpace($line) -or $line -match '^\s*#') {
            continue
        }

        if ($line -match $pattern) {
            return $matches[1].Trim().Trim('"').Trim("'")
        }
    }

    return $null
}

function Get-LatestWriteTimeUtc {
    param([string[]]$Paths)

    $latest = [datetime]::MinValue
    foreach ($path in $Paths) {
        if (-not (Test-Path $path)) {
            continue
        }

        $item = Get-Item $path
        if ($item.PSIsContainer) {
            $children = Get-ChildItem $path -File -Recurse -ErrorAction SilentlyContinue
            foreach ($child in $children) {
                if ($child.LastWriteTimeUtc -gt $latest) {
                    $latest = $child.LastWriteTimeUtc
                }
            }
            continue
        }

        if ($item.LastWriteTimeUtc -gt $latest) {
            $latest = $item.LastWriteTimeUtc
        }
    }

    return $latest
}

function Invoke-FrontendAuditFix {
    param(
        [Parameter(Mandatory = $true)]
        [string]$NpmExecutable
    )

    Write-Phase "Running frontend npm audit fix"
    & $NpmExecutable audit fix
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "npm audit fix did not complete cleanly. Continuing with the installed dependencies. Check npm registry access and local certificate trust if this keeps happening."
    }
}

function Invoke-RepoScriptUnblock {
    param(
        [Parameter(Mandatory = $true)]
        [string]$UtilityPath,
        [Parameter(Mandatory = $true)]
        [string]$RootPath
    )

    if (-not (Test-Path $UtilityPath)) {
        return
    }

    try {
        Unblock-File -LiteralPath $UtilityPath -ErrorAction Stop
    }
    catch {
    }

    Write-Phase "Checking PowerShell scripts for Windows block markers"
    $results = & $UtilityPath -Root $RootPath -Quiet -PassThru
    $blockedCount = @($results | Where-Object { $_.Blocked }).Count
    $unblockedCount = @($results | Where-Object { $_.Action -eq "unblocked" }).Count

    if ($blockedCount -gt 0) {
        Write-Host "Unblocked $unblockedCount PowerShell script(s)." -ForegroundColor Green
    }
    else {
        Write-Host "All PowerShell scripts are already clear." -ForegroundColor DarkGray
    }
}

$rootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $rootDir "backend"
$frontendDir = Join-Path $rootDir "frontend"
$venvDir = Join-Path $rootDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$backendInstallStamp = Join-Path $venvDir ".backend-install.stamp"
$frontendInstallStamp = Join-Path $frontendDir "node_modules\.install.stamp"
$frontendBuildStamp = Join-Path $frontendDir "dist\.build.stamp"
$backendEnvFile = Join-Path $backendDir ".env"
$frontendEnvFile = Join-Path $frontendDir ".env"
$unblockScript = Join-Path $rootDir "unblock-ps1.ps1"

Invoke-RepoScriptUnblock -UtilityPath $unblockScript -RootPath $rootDir

if (-not (Test-Path $venvPython)) {
    Write-Phase "Creating Python virtual environment in .venv"
    $bootstrap = Get-BootstrapPython
    $bootstrapExe = $bootstrap[0]
    $bootstrapArgs = @()
    if ($bootstrap.Count -gt 1) {
        $bootstrapArgs += $bootstrap[1..($bootstrap.Count - 1)]
    }
    $bootstrapArgs += @("-m", "venv", $venvDir)
    & $bootstrapExe @bootstrapArgs
}

$pythonVersion = & $venvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([version]$pythonVersion -lt [version]"3.11") {
    throw "The virtual environment uses Python $pythonVersion. Remove .venv and rerun the launcher with Python 3.11 or newer available on PATH."
}

if (-not (Test-Path $backendEnvFile) -and (Test-Path (Join-Path $backendDir ".env.example"))) {
    Write-Phase "Creating backend/.env from the example file"
    Copy-Item (Join-Path $backendDir ".env.example") $backendEnvFile
}

if (-not (Test-Path $frontendEnvFile) -and (Test-Path (Join-Path $frontendDir ".env.example"))) {
    Write-Phase "Creating frontend/.env from the example file"
    Copy-Item (Join-Path $frontendDir ".env.example") $frontendEnvFile
}

$configuredBindHost = Get-EnvFileValue -FilePath $backendEnvFile -Name "HOST"
$configuredPort = Get-EnvFileValue -FilePath $backendEnvFile -Name "PORT"

if ([string]::IsNullOrWhiteSpace($BindHost)) {
    $BindHost = if ([string]::IsNullOrWhiteSpace($configuredBindHost)) { "0.0.0.0" } else { $configuredBindHost }
}

if ($null -eq $Port) {
    if (-not [string]::IsNullOrWhiteSpace($configuredPort)) {
        $Port = [int]$configuredPort
    }
    else {
        $Port = 8000
    }
}

$appUrl = "http://localhost:$Port"

if (-not $SkipInstall) {
    $backendPyProject = Join-Path $backendDir "pyproject.toml"
    $backendInstallTime = if (Test-Path $backendInstallStamp) { (Get-Item $backendInstallStamp).LastWriteTimeUtc } else { [datetime]::MinValue }
    $needsBackendInstall =
        (-not (Test-Path $backendInstallStamp)) -or
        ((Get-Item $backendPyProject).LastWriteTimeUtc -gt $backendInstallTime)

    if ($needsBackendInstall) {
        Write-Phase "Installing backend dependencies into .venv"
        & $venvPython -m pip install -e $backendDir
        Set-Content -Path $backendInstallStamp -Value (Get-Date).ToString("o") -Encoding ascii
    }

    $frontendInstallTime = if (Test-Path $frontendInstallStamp) { (Get-Item $frontendInstallStamp).LastWriteTimeUtc } else { [datetime]::MinValue }
    $needsFrontendInstall =
        (-not (Test-Path (Join-Path $frontendDir "node_modules"))) -or
        (-not (Test-Path $frontendInstallStamp)) -or
        ((Get-Item (Join-Path $frontendDir "package.json")).LastWriteTimeUtc -gt $frontendInstallTime)

    if ($needsFrontendInstall) {
        $npmCommand = Get-Command npm -ErrorAction SilentlyContinue
        if (-not $npmCommand) {
            throw "npm is required to install frontend dependencies. Install Node.js 20 or newer."
        }

        Write-Phase "Installing frontend dependencies"
        Push-Location $frontendDir
        try {
            & $npmCommand.Source install
            Invoke-FrontendAuditFix -NpmExecutable $npmCommand.Source
        }
        finally {
            Pop-Location
        }

        Set-Content -Path $frontendInstallStamp -Value (Get-Date).ToString("o") -Encoding ascii
    }
}

$frontendSources = @(
    (Join-Path $frontendDir "src"),
    (Join-Path $frontendDir "index.html"),
    (Join-Path $frontendDir "package.json"),
    (Join-Path $frontendDir "tsconfig.json"),
    (Join-Path $frontendDir "tsconfig.app.json"),
    (Join-Path $frontendDir "tsconfig.node.json"),
    (Join-Path $frontendDir "vite.config.ts")
)

$latestFrontendSource = Get-LatestWriteTimeUtc -Paths $frontendSources
$frontendBuildTime = if (Test-Path $frontendBuildStamp) { (Get-Item $frontendBuildStamp).LastWriteTimeUtc } else { [datetime]::MinValue }
$needsFrontendBuild =
    (-not (Test-Path (Join-Path $frontendDir "dist\index.html"))) -or
    ($latestFrontendSource -gt $frontendBuildTime)

if ($needsFrontendBuild) {
    $npmCommand = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npmCommand) {
        throw "npm is required to build the frontend. Install Node.js 20 or newer."
    }

    Write-Phase "Building the frontend bundle"
    Push-Location $frontendDir
    try {
        & $npmCommand.Source run build
    }
    finally {
        Pop-Location
    }

    if (-not (Test-Path (Join-Path $frontendDir "dist"))) {
        throw "Frontend build completed without producing frontend/dist."
    }

    Set-Content -Path $frontendBuildStamp -Value (Get-Date).ToString("o") -Encoding ascii
}

$env:FRONTEND_ORIGIN = $appUrl
$env:HOST = $BindHost
$env:PORT = "$Port"

Write-Phase "Prepared TWC Workbench for launch at $appUrl"

if ($PrepareOnly) {
    Write-Host "Preparation completed. Run .\launch.ps1 to start the server." -ForegroundColor Green
    return
}

if (-not $NoBrowser) {
    Get-Job -Name "twc-workbench-browser" -ErrorAction SilentlyContinue | Remove-Job -Force -ErrorAction SilentlyContinue
    Start-Job -Name "twc-workbench-browser" -ScriptBlock {
        param($RootUrl)

        $healthUrl = "$RootUrl/healthz"
        for ($attempt = 0; $attempt -lt 60; $attempt++) {
            Start-Sleep -Seconds 1
            try {
                Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 2 | Out-Null
                Start-Process $RootUrl
                return
            }
            catch {
            }
        }
    } -ArgumentList $appUrl | Out-Null
}

Write-Phase "Starting the single-origin FastAPI server"
Push-Location $backendDir
try {
    & $venvPython -m uvicorn app.main:app --host $BindHost --port $Port
}
finally {
    Pop-Location
}
