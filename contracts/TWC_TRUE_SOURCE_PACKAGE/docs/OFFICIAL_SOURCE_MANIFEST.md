# Official Source Manifest

This file lists **official public source-of-truth locations** relevant to the Teamwork Cloud integration effort.

## 1) Public Swagger index
- Public index: `https://osmc.nomagic.com/`
- Public Teamwork Cloud Swagger UI entries:
  - `https://osmc.nomagic.com/2022xR2/swagger/index.html`
  - `https://osmc.nomagic.com/2024xR3/swagger/index.html`
- Public server-side simulation Swagger UI entries:
  - `https://osmc.nomagic.com/simulation/2022xRefresh2/swagger/index.html`
  - `https://osmc.nomagic.com/simulation/2024xRefresh3/swagger/index.html`

## 2) In-product addresses
Use your own live servers for machine-readable contract export and browser validation:
- REST / Swagger: `https://<Teamwork-Cloud-IP>:8111/osmc/swagger`
- Browser UI: `https://<Teamwork-Cloud-IP>:8443`
- For this project, keep the default ports and paths above and substitute only your HTTPS host name.
- The public `osmc.nomagic.com` pages are documentation mirrors; they do not replace your live host/port layout.

## 3) Official REST API landing docs
- Teamwork Cloud and Services 2024x REST APIs:
  - `https://docs.nomagic.com/spaces/TWCloud2024x/pages/137987736/REST%2BAPIs`
- Teamwork Cloud and Services 2022x Refresh2 authentication section:
  - `https://docs.nomagic.com/spaces/TWCloud2022xR2/pages/127970880/Authentication`
- Teamwork Cloud and Services 2022x Refresh2 token auth page:
  - `https://docs.nomagic.com/spaces/TWCloud2022xR2/pages/127970883/Token-based%2Bauthentication`
- Teamwork Cloud and Services 2022x Refresh2 model manipulation page:
  - `https://docs.nomagic.com/spaces/TWCloud2022xR2/pages/127970884/Model%2Bmanipulation`
- Teamwork Cloud 2022x session reuse page:
  - `https://docs.nomagic.com/spaces/TWCloud2022x/pages/158597352/Reusing%2BTeamwork%2BCloud%2Bsession`
- Teamwork Cloud 2022x REST API change log:
  - `https://docs.nomagic.com/display/TWCloud2022x/REST%2BAPI%2BChange%2BLog`

## 4) Authentication / SAML official docs
- Teamwork Cloud 2024x authentication server overview:
  - `https://docs.nomagic.com/spaces/TWCloud2024x/pages/137986532/Authentication%2Bserver`
- Teamwork Cloud 2022x authentication server overview:
  - `https://docs.nomagic.com/spaces/TWCloud2022x/pages/95722146/Authentication%2Bserver`
- Teamwork Cloud 2024x SAML integration:
  - `https://docs.nomagic.com/spaces/TWCloud2024x/pages/137986541/SAML%2Bintegration`
- Teamwork Cloud 2024x SAML parameters:
  - `https://docs.nomagic.com/spaces/TWCloud2024x/pages/137986542/SAML%2Bparameters`
- Magic Collaboration Studio 2024xR3 SAML setup UI flow:
  - `https://docs.nomagic.com/spaces/MCS2024xR3/pages/261619838/Configuring%2Bauthentication%2Bserver%2Bfor%2BSAML%2Bintegration`

## 5) Version context / release notes
- Teamwork Cloud and Services 2024x Refresh3 overview:
  - `https://docs.nomagic.com/spaces/TWCloud2024xR3/pages/227171266/Teamwork%2BCloud%2Band%2BServices`
- 2024x Refresh3 version news (useful for version-specific capabilities, e.g. SSO in CLI tools):
  - `https://docs.nomagic.com/spaces/MD2024xR3/pages/227148264/2024x%2BRefresh3%2BVersion%2BNews`
- 2022x Refresh2 Hot Fix 2 version news:
  - `https://docs.nomagic.com/spaces/NMDOC/pages/178160520/2022x%2BRefresh2%2BHot%2BFix%2B2%2BVersion%2BNews`

## 6) Why live exports are still required
Even with public docs, the coding agent still needs live artifacts for:
- actual enabled endpoints,
- actual error bodies,
- real permission/capability restrictions,
- real collaborator/publish behaviors in your deployment,
- internal publish service contract.

## 7) Required live artifacts to add to this package
- 2022xR2 Swagger/OpenAPI export from your server
- 2024xR3 Swagger/OpenAPI export from your server
- Simulation Swagger/OpenAPI export from your server if different from public docs
- one successful request/response and one failure payload for each critical feature area
- internal publish service request/response contract
