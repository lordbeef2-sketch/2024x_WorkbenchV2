[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Root,
    [switch]$Force,
    [switch]$Quiet,
    [switch]$PassThru
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $Root) {
    if ($PSScriptRoot) {
        $Root = $PSScriptRoot
    }
    else {
        $Root = (Get-Location).Path
    }
}

function Test-IsBlocked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    try {
        Get-Item -LiteralPath $Path -Stream Zone.Identifier -ErrorAction Stop | Out-Null
        return $true
    }
    catch [System.Management.Automation.ItemNotFoundException] {
        return $false
    }
    catch [System.IO.FileNotFoundException] {
        return $false
    }
}

if (-not (Test-Path -LiteralPath $Root)) {
    throw "The root path '$Root' does not exist."
}

$resolvedRoot = (Resolve-Path -LiteralPath $Root).Path
$scriptFiles = Get-ChildItem -LiteralPath $resolvedRoot -Filter *.ps1 -File -Recurse -Force:$Force

$results = foreach ($scriptFile in $scriptFiles) {
    $isBlocked = Test-IsBlocked -Path $scriptFile.FullName
    $action = "already-clear"
    $displayPath = if ($scriptFile.FullName.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        $scriptFile.FullName.Substring($resolvedRoot.Length).TrimStart([char[]]@('\', '/'))
    }
    else {
        $scriptFile.FullName
    }

    if ($isBlocked) {
        if ($PSCmdlet.ShouldProcess($scriptFile.FullName, "Unblock PowerShell script")) {
            Unblock-File -LiteralPath $scriptFile.FullName
            $action = "unblocked"
        }
        else {
            $action = "would-unblock"
        }
    }

    [pscustomobject]@{
        Path = $displayPath
        FullPath = $scriptFile.FullName
        Blocked = $isBlocked
        Action = $action
    }
}

$blockedCount = @($results | Where-Object { $_.Blocked }).Count
$unblockedCount = @($results | Where-Object { $_.Action -eq "unblocked" }).Count

if (-not $Quiet) {
    if ($results) {
        $results | Sort-Object Path | Format-Table Path, Blocked, Action -AutoSize -Wrap
    }
    else {
        Write-Host "No .ps1 files were found under $resolvedRoot"
    }

    Write-Host ""
    Write-Host "Scanned:   $(@($results).Count) script(s)" -ForegroundColor Cyan
    Write-Host "Blocked:   $blockedCount script(s)" -ForegroundColor Yellow
    Write-Host "Unblocked: $unblockedCount script(s)" -ForegroundColor Green
}

if ($PassThru) {
    $results
}