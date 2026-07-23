$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PackageRoot = Split-Path -Parent $Root
$OutDir = Join-Path $PackageRoot 'official_html'
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$Sources = @(
    @{ Name = 'public_swagger_index.html'; Url = 'https://osmc.nomagic.com/' },
    @{ Name = 'public_twc_2022xR2_swagger_ui.html'; Url = 'https://osmc.nomagic.com/2022xR2/swagger/index.html' },
    @{ Name = 'public_twc_2024xR3_swagger_ui.html'; Url = 'https://osmc.nomagic.com/2024xR3/swagger/index.html' },
    @{ Name = 'public_sim_2022xR2_swagger_ui.html'; Url = 'https://osmc.nomagic.com/simulation/2022xRefresh2/swagger/index.html' },
    @{ Name = 'public_sim_2024xR3_swagger_ui.html'; Url = 'https://osmc.nomagic.com/simulation/2024xRefresh3/swagger/index.html' },
    @{ Name = 'docs_twc_2024x_rest_apis.html'; Url = 'https://docs.nomagic.com/spaces/TWCloud2024x/pages/137987736/REST%2BAPIs' },
    @{ Name = 'docs_twc_2022xR2_authentication.html'; Url = 'https://docs.nomagic.com/spaces/TWCloud2022xR2/pages/127970880/Authentication' },
    @{ Name = 'docs_twc_2022xR2_token_auth.html'; Url = 'https://docs.nomagic.com/spaces/TWCloud2022xR2/pages/127970883/Token-based%2Bauthentication' },
    @{ Name = 'docs_twc_2022xR2_model_manipulation.html'; Url = 'https://docs.nomagic.com/spaces/TWCloud2022xR2/pages/127970884/Model%2Bmanipulation' },
    @{ Name = 'docs_twc_2022x_session_reuse.html'; Url = 'https://docs.nomagic.com/spaces/TWCloud2022x/pages/158597352/Reusing%2BTeamwork%2BCloud%2Bsession' },
    @{ Name = 'docs_twc_2024x_auth_server.html'; Url = 'https://docs.nomagic.com/spaces/TWCloud2024x/pages/137986532/Authentication%2Bserver' },
    @{ Name = 'docs_devg_2024xR3_oidc_authentication.html'; Url = 'https://docs.nomagic.com/spaces/DEVG2024xR3/pages/225347498/OpenID%2BConnect%2Bauthentication' },
    @{ Name = 'docs_twc_2024x_saml_integration.html'; Url = 'https://docs.nomagic.com/spaces/TWCloud2024x/pages/137986541/SAML%2Bintegration' },
    @{ Name = 'docs_twc_2024x_saml_parameters.html'; Url = 'https://docs.nomagic.com/spaces/TWCloud2024x/pages/137986542/SAML%2Bparameters' },
    @{ Name = 'docs_mcs_2024xR3_saml_config.html'; Url = 'https://docs.nomagic.com/spaces/MCS2024xR3/pages/261619838/Configuring%2Bauthentication%2Bserver%2Bfor%2BSAML%2Bintegration' },
    @{ Name = 'docs_twc_2024xR3_overview.html'; Url = 'https://docs.nomagic.com/spaces/TWCloud2024xR3/pages/227171266/Teamwork%2BCloud%2Band%2BServices' },
    @{ Name = 'docs_2024xR3_version_news.html'; Url = 'https://docs.nomagic.com/spaces/MD2024xR3/pages/227148264/2024x%2BRefresh3%2BVersion%2BNews' },
    @{ Name = 'docs_2022xR2_hf2_version_news.html'; Url = 'https://docs.nomagic.com/spaces/NMDOC/pages/178160520/2022x%2BRefresh2%2BHot%2BFix%2B2%2BVersion%2BNews' },
    @{ Name = 'jdocs_cameo_2022x_overview.html'; Url = 'https://jdocs.nomagic.com/2022x/' },
    @{ Name = 'jdocs_cameo_2024x_overview.html'; Url = 'https://jdocs.nomagic.com/2024x/' },
    @{ Name = 'jdocs_cameo_2022x_plugins_package.html'; Url = 'https://jdocs.nomagic.com/2022x/com/nomagic/magicdraw/plugins/package-summary.html' },
    @{ Name = 'jdocs_cameo_2024x_plugins_package.html'; Url = 'https://jdocs.nomagic.com/2024x/com/nomagic/magicdraw/plugins/package-summary.html' },
    @{ Name = 'jdocs_cameo_2022x_openapi_uml_package.html'; Url = 'https://jdocs.nomagic.com/2022x/com/nomagic/magicdraw/openapi/uml/package-summary.html' },
    @{ Name = 'jdocs_cameo_2024x_openapi_uml_package.html'; Url = 'https://jdocs.nomagic.com/2024x/com/nomagic/magicdraw/openapi/uml/package-summary.html' },
    @{ Name = 'jdocs_cameo_2022x_browser_package.html'; Url = 'https://jdocs.nomagic.com/2022x/com/nomagic/magicdraw/ui/browser/package-summary.html' },
    @{ Name = 'jdocs_cameo_2024x_browser_package.html'; Url = 'https://jdocs.nomagic.com/2024x/com/nomagic/magicdraw/ui/browser/package-summary.html' },
    @{ Name = 'jdocs_cameo_2022x_specifications_package.html'; Url = 'https://jdocs.nomagic.com/2022x/com/nomagic/magicdraw/ui/dialogs/specifications/package-summary.html' },
    @{ Name = 'jdocs_cameo_2024x_specifications_package.html'; Url = 'https://jdocs.nomagic.com/2024x/com/nomagic/magicdraw/ui/dialogs/specifications/package-summary.html' },
    @{ Name = 'jdocs_cameo_2022x_teamwork2_package.html'; Url = 'https://jdocs.nomagic.com/2022x/com/nomagic/magicdraw/teamwork2/package-summary.html' },
    @{ Name = 'jdocs_cameo_2024x_teamwork2_package.html'; Url = 'https://jdocs.nomagic.com/2024x/com/nomagic/magicdraw/teamwork2/package-summary.html' },
    @{ Name = 'jdocs_cameo_2022x_uml_symbols_package.html'; Url = 'https://jdocs.nomagic.com/2022x/com/nomagic/magicdraw/uml/symbols/package-summary.html' },
    @{ Name = 'jdocs_cameo_2024x_uml_symbols_package.html'; Url = 'https://jdocs.nomagic.com/2024x/com/nomagic/magicdraw/uml/symbols/package-summary.html' }
)

foreach ($s in $Sources) {
    $target = Join-Path $OutDir $s.Name
    Write-Host "Downloading $($s.Url) -> $target"
    try {
        Invoke-WebRequest -Uri $s.Url -OutFile $target -UseBasicParsing
    }
    catch {
        Write-Warning "Failed: $($s.Url) :: $($_.Exception.Message)"
    }
}

Write-Host 'Done.'
