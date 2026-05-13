param(
    [switch]$SkipJdkDownload
)

$ErrorActionPreference = "Stop"

$pluginRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $pluginRoot
$toolingRoot = Join-Path $pluginRoot ".tooling"
$gradleHome = Join-Path $toolingRoot "gradle-home"
$gradleVersion = "6.9.3"
$gradleRoot = Join-Path $toolingRoot "gradle-$gradleVersion"
$distRoot = Join-Path $pluginRoot "dist"

$cameoTargets = @(
    @{
        Label = "2022x"
        CameoHome = Join-Path $repoRoot "Knowlege\Cameo_Enterprise_Architecture_2022x_Refresh2_HF3_no_install"
        JavaVersion = "11"
    },
    @{
        Label = "2024x"
        CameoHome = Join-Path $repoRoot "Knowlege\Cameo_Enterprise_Architecture_2024x_Refresh3_HF1_no_install"
        JavaVersion = "17"
    }
)

function Get-JdkDownloadLink([string]$javaVersion) {
    $uri = "https://api.adoptium.net/v3/assets/latest/$javaVersion/hotspot?architecture=x64&heap_size=normal&image_type=jdk&jvm_impl=hotspot&os=windows&vendor=eclipse"
    $assets = Invoke-RestMethod -Uri $uri -Method Get
    if (-not $assets -or $assets.Count -lt 1) {
        throw "No JDK $javaVersion assets were returned from Adoptium."
    }
    $link = $assets[0].binary.package.link
    if (-not $link) {
        throw "Failed to resolve JDK $javaVersion download link from Adoptium response."
    }
    return $link
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

    $downloadLink = Get-JdkDownloadLink -javaVersion $javaVersion
    Write-Host "Downloading JDK $javaVersion from $downloadLink"
    Invoke-WebRequest -Uri $downloadLink -OutFile $archivePath
    Expand-Archive -Path $archivePath -DestinationPath $extractPath -Force

    $jdkHome = Get-ChildItem $extractPath -Directory | Select-Object -First 1
    if (-not $jdkHome) {
        throw "Failed to extract JDK 11 archive."
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

    if (Test-Path $archivePath) {
        Remove-Item $archivePath -Force
    }
    if (Test-Path $extractPath) {
        Remove-Item $extractPath -Recurse -Force
    }

    Write-Host "Downloading Gradle $gradleVersion from $downloadUrl"
    Invoke-WebRequest -Uri $downloadUrl -OutFile $archivePath
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
