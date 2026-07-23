# Live Data Collection Checklist

Use this checklist to gather the **non-public** or **environment-specific** artifacts that a coding agent will need.

## A. Swagger / OpenAPI
### Required
- [x] Export 2022xR2 Teamwork Cloud Swagger/OpenAPI from your live server
- [x] Export 2024xR3 Teamwork Cloud Swagger/OpenAPI from your live server
- [ ] Export 2022xR2 simulation Swagger/OpenAPI if available
- [ ] Export 2024xR3 simulation Swagger/OpenAPI if available

Already present in this repo:
- `contracts/TWC_SWAGGER_DIFF_PACKAGE/scripts/output/twc_2022xR2.json`
- `contracts/TWC_SWAGGER_DIFF_PACKAGE/scripts/output/twc_2024xR3.json`

### Save to
- `live_capture/2022xR2/swagger/`
- `live_capture/2024xR3/swagger/`

## B. Authentication / Session behavior
### Capture
- [ ] Successful OIDC discovery, authorization-code, callback, and refresh flow notes (sanitize codes, tokens, and secrets)
- [ ] Exact registered Workbench redirect URI and client configuration (never capture the secret value)
- [ ] Confirmation that REST calls accept `Authorization: Token <ID token>`
- [ ] Upstream SAML notes only if AuthServer delegates authentication to a SAML identity provider
- [ ] Logout/session termination behavior

### Save to
- `live_capture/common/auth/`

## C. Project / model browsing
Capture one success and one failure for each, where possible:
- [ ] projects listing
- [ ] branches listing
- [ ] tree / decomposition / model browsing
- [ ] element details lookup
- [ ] search

### Save to
- `live_capture/2022xR2/browse/`
- `live_capture/2024xR3/browse/`

## D. Write / edit operations
Capture:
- [ ] create example
- [ ] update example
- [ ] conflict/version failure example (409 or equivalent)
- [ ] permission failure example (403 or equivalent)
- [ ] validation failure example

Also capture any required:
- version field
- revision field
- concurrency token / ETag / branch context

### Save to
- `live_capture/2022xR2/write/`
- `live_capture/2024xR3/write/`

## E. Simulation
Capture:
- [ ] config discovery
- [ ] run/start request and response
- [ ] cancel/stop request and response
- [ ] status polling payload
- [ ] logs/output payload
- [ ] results retrieval payload

### Save to
- `live_capture/2022xR2/simulation/`
- `live_capture/2024xR3/simulation/`

## F. Collaborator / document features
Capture:
- [ ] documents list or retrieval
- [ ] attachments
- [ ] comments
- [ ] versions/history
- [ ] edit-on-web if applicable

### Save to
- `live_capture/2022xR2/collaborator/`
- `live_capture/2024xR3/collaborator/`

## G. Publish / document generation
### Cameo Collaborator / TWC
- [ ] publish trigger request/response
- [ ] status polling
- [ ] result link or artifact

### Internal publish service
- [ ] request schema
- [ ] response schema
- [ ] async/sync behavior
- [ ] PPT/doc generation result format
- [ ] editability semantics in your app UI

### Save to
- `live_capture/common/publish/`

## H. Standard error payloads
Capture real payloads for:
- [ ] 401
- [ ] 403
- [ ] 404
- [ ] 409 / version conflict
- [ ] capability restriction
- [ ] validation errors

### Save to
- `live_capture/common/errors/`

## Sanitization rules
- Remove passwords, raw tokens, session cookies, and internal-only secrets.
- Keep endpoint paths, status codes, field names, and response shapes intact.
- Preserve realistic IDs if safe; otherwise replace consistently.
