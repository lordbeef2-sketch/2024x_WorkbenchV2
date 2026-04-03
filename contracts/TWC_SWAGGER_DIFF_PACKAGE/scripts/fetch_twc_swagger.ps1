param(
    [Parameter(Mandatory=$true)][string]$V2022Url,
    [Parameter(Mandatory=$true)][string]$V2024Url,
    [string]$OutDir = "output/swagger/raw"
)

$ErrorActionPreference = "Stop"
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = {$true}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

function Save-Response($Url, $OutFile) {
    Write-Host "Fetching $Url"
    $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing
    $contentType = $resp.Headers["Content-Type"]
    $body = $resp.Content

    try {
        $null = $body | ConvertFrom-Json
        Set-Content -LiteralPath $OutFile -Value $body -Encoding UTF8
        Write-Host "Saved JSON to $OutFile"
        return
    } catch {}

    if ($body -match 'url\s*:\s*["'']([^"'']+)["'']') {
        $specUrl = $matches[1]
        if ($specUrl -notmatch '^https?://') {
            $base = [System.Uri]$Url
            $specUrl = (New-Object System.Uri($base, $specUrl)).AbsoluteUri
        }
        Write-Host "Fetching linked spec $specUrl"
        $spec = Invoke-WebRequest -Uri $specUrl -UseBasicParsing
        Set-Content -LiteralPath $OutFile -Value $spec.Content -Encoding UTF8
        Write-Host "Saved linked JSON to $OutFile"
        return
    }

    throw "Could not find JSON Swagger/OpenAPI spec from $Url"
}

Save-Response -Url $V2022Url -OutFile (Join-Path $OutDir "twc_2022xR2.json")
Save-Response -Url $V2024Url -OutFile (Join-Path $OutDir "twc_2024xR3.json")
