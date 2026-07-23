param(
    [switch]$SkipJdkDownload,
    [ValidateSet("2022x", "2024x", "All")]
    [string]$Target = "2024x",
    [string]$Cameo2022xHome,
    [string]$Cameo2024xHome
)

$ErrorActionPreference = "Stop"

$pluginRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $pluginRoot
$toolingRoot = Join-Path $pluginRoot ".tooling"
$gradleHome = Join-Path $toolingRoot "gradle-home"
$gradleVersion = "8.7"
$gradleRoot = Join-Path $toolingRoot "gradle-$gradleVersion"
$distRoot = Join-Path $pluginRoot "dist"

function Resolve-CameoHome([string[]]$candidates, [string]$label) {
    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) {
            continue
        }
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    $checked = ($candidates | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join ", "
    throw "No Cameo home found for $label. Checked: $checked"
}

$cameoTargets = @()
if ($Target -in @("2022x", "All")) {
    $cameoTargets += @{
        Label = "2022x"
        CameoHome = Resolve-CameoHome @(
            $Cameo2022xHome,
            $env:CAMEO_2022X_HOME,
            $env:CAMEO2022X_HOME,
            $env:CAMEO_HOME_2022X,
            $env:CAMEO_HOME_2022,
            (Join-Path $repoRoot "Knowlege\Cameo_Enterprise_Architecture_2022x_Refresh2_HF3_no_install")
        ) "2022x"
        JavaVersion = "11"
    }
}
if ($Target -in @("2024x", "All")) {
    $cameoTargets += @{
        Label = "2024x"
        CameoHome = Resolve-CameoHome @(
            $Cameo2024xHome,
            $env:CAMEO_2024X_HOME,
            $env:CAMEO2024X_HOME,
            $env:CAMEO_HOME_2024X,
            $env:CAMEO_HOME_2024,
            $env:CAMEO_HOME,
            (Join-Path $repoRoot "Knowlege\Cameo_Enterprise_Architecture_2024x_Refresh3_HF1_no_install")
        ) "2024x"
        JavaVersion = "17"
    }
}

function Get-JdkAsset([string]$javaVersion) {
    $uri = "https://api.adoptium.net/v3/assets/latest/$javaVersion/hotspot?architecture=x64&heap_size=normal&image_type=jdk&jvm_impl=hotspot&os=windows&vendor=eclipse"
    $assets = Invoke-RestMethod -Uri $uri -Method Get
    if (-not $assets -or $assets.Count -lt 1) {
        throw "No JDK $javaVersion assets were returned from Adoptium."
    }
    $package = $assets[0].binary.package
    if (-not $package.link -or -not $package.checksum) {
        throw "Failed to resolve the JDK $javaVersion download link and SHA-256 from Adoptium."
    }
    return [pscustomobject]@{ Link = $package.link; Sha256 = $package.checksum.ToLowerInvariant() }
}

function Assert-FileSha256([string]$path, [string]$expected, [string]$label) {
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected.Trim().ToLowerInvariant()) {
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
        throw "$label SHA-256 verification failed. Expected $expected; received $actual."
    }
}

function Ensure-Jdk([string]$javaVersion) {
    $jdkRoot = Join-Path $toolingRoot "jdk-$javaVersion"
    if (Test-Path (Join-Path $jdkRoot "bin\javac.exe")) {
        return $jdkRoot
    }
    if ($SkipJdkDownload) {
        throw "JDK $javaVersion is not available at $jdkRoot and -SkipJdkDownload was set."
    }

    New-Item -ItemType Directory -Force -Path $toolingRoot | Out-Null
    $archivePath = Join-Path $toolingRoot "jdk-$javaVersion.zip"
    $extractPath = Join-Path $toolingRoot "jdk-$javaVersion-extract"

    if (Test-Path $archivePath) {
        Remove-Item $archivePath -Force
    }
    if (Test-Path $extractPath) {
        Remove-Item $extractPath -Recurse -Force
    }

    $asset = Get-JdkAsset -javaVersion $javaVersion
    Write-Host "Downloading JDK $javaVersion from $($asset.Link)"
    Invoke-WebRequest -Uri $asset.Link -OutFile $archivePath
    Assert-FileSha256 -path $archivePath -expected $asset.Sha256 -label "JDK $javaVersion archive"
    Expand-Archive -Path $archivePath -DestinationPath $extractPath -Force

    $jdkHome = Get-ChildItem $extractPath -Directory | Select-Object -First 1
    if (-not $jdkHome) {
        throw "Failed to extract JDK $javaVersion archive."
    }

    if (Test-Path $jdkRoot) {
        Remove-Item $jdkRoot -Recurse -Force
    }
    Move-Item -Path $jdkHome.FullName -Destination $jdkRoot
    return $jdkRoot
}

function Ensure-Gradle {
    $gradleBat = Join-Path $gradleRoot "bin\gradle.bat"
    if (Test-Path $gradleBat) {
        return $gradleBat
    }

    New-Item -ItemType Directory -Force -Path $toolingRoot | Out-Null
    $archivePath = Join-Path $toolingRoot "gradle-$gradleVersion-bin.zip"
    $extractPath = Join-Path $toolingRoot "gradle-extract"
    $downloadUrl = "https://services.gradle.org/distributions/gradle-$gradleVersion-bin.zip"
    $checksumUrl = "$downloadUrl.sha256"

    if (Test-Path $archivePath) {
        Remove-Item $archivePath -Force
    }
    if (Test-Path $extractPath) {
        Remove-Item $extractPath -Recurse -Force
    }

    Write-Host "Downloading Gradle $gradleVersion from $downloadUrl"
    Invoke-WebRequest -Uri $downloadUrl -OutFile $archivePath
    $expectedChecksum = (Invoke-RestMethod -Uri $checksumUrl -Method Get).ToString().Trim().Split()[0]
    Assert-FileSha256 -path $archivePath -expected $expectedChecksum -label "Gradle $gradleVersion archive"
    Expand-Archive -Path $archivePath -DestinationPath $extractPath -Force

    $gradleDir = Get-ChildItem $extractPath -Directory | Where-Object { $_.Name -like "gradle-*" } | Select-Object -First 1
    if (-not $gradleDir) {
        throw "Failed to extract Gradle distribution."
    }

    if (Test-Path $gradleRoot) {
        Remove-Item $gradleRoot -Recurse -Force
    }
    Move-Item -Path $gradleDir.FullName -Destination $gradleRoot
    return $gradleBat
}

function Build-PluginTarget([string]$label, [string]$cameoHome, [string]$javaVersion) {
    if (-not (Test-Path $cameoHome)) {
        throw "Cameo home not found: $cameoHome"
    }

    $jdkRoot = Ensure-Jdk -javaVersion $javaVersion
    $env:JAVA_HOME = $jdkRoot
    $env:Path = (Join-Path $jdkRoot "bin") + ";" + $env:Path
    $env:GRADLE_USER_HOME = $gradleHome
    $gradleExe = Ensure-Gradle

    Write-Host "Building plugin for $label using $cameoHome"
    & $gradleExe -p $pluginRoot clean stagePlugin "-PcameoHome=$cameoHome" "-PpluginTarget=$label" "-PpluginJavaVersion=$javaVersion" --no-daemon
    if ($LASTEXITCODE -ne 0) {
        throw "Gradle build failed for $label."
    }

    $stagedDir = Join-Path $pluginRoot "build\cameo-plugin-$label"
    if (-not (Test-Path $stagedDir)) {
        throw "Expected staged plugin directory was not produced: $stagedDir"
    }

    New-Item -ItemType Directory -Force -Path $distRoot | Out-Null
    $targetDir = Join-Path $distRoot $label
    if (Test-Path $targetDir) {
        Remove-Item $targetDir -Recurse -Force
    }
    Copy-Item -Path $stagedDir -Destination $targetDir -Recurse

    $zipPath = Join-Path $distRoot "twc-workbench-cameo-plugin-$label.zip"
    if (Test-Path $zipPath) {
        Remove-Item $zipPath -Force
    }
    Compress-Archive -Path (Join-Path $targetDir "*") -DestinationPath $zipPath
}

foreach ($target in $cameoTargets) {
    Build-PluginTarget -label $target.Label -cameoHome $target.CameoHome -javaVersion $target.JavaVersion
}

Write-Host "Plugin builds complete."
