# Live Capture Playbook

This playbook is for collecting **true** environment-specific artifacts from your own TWC servers and internal services.

## 1. Export Swagger / OpenAPI
### Teamwork Cloud
Open in browser:
- `https://<2022xR2-server>:8111/osmc/swagger`
- `https://<2024xR3-server>:8111/osmc/swagger`

Use port `8111` for REST/Swagger capture. Do not substitute the main browser UI port `8443` here.
Use your normal HTTPS host name and keep the default Teamwork Cloud ports and paths.

If you need browser-side validation of the end-user application separately, use:
- `https://<2022xR2-server>:8443`
- `https://<2024xR3-server>:8443`

If the UI offers JSON/YAML export, save it to:
- `live_capture/2022xR2/swagger/`
- `live_capture/2024xR3/swagger/`

If it does not, save:
- the HTML page,
- browser HAR,
- any downloaded JSON spec visible in DevTools network.

### Simulation
Repeat for simulation if your server exposes a separate spec.

## 2. Capture success payloads
Use browser Swagger, Postman, curl, or your Python scripts.
For each critical endpoint, save:
- request headers (sanitized)
- request body
- response body
- status code

## 3. Capture failure payloads
Intentionally trigger:
- 401 unauthorized
- 403 forbidden
- 404 missing object/path
- 409 conflict/version mismatch
- validation errors

## 4. Save collaborator and publish artifacts separately
Keep these separate from core TWC:
- `live_capture/<version>/collaborator/`
- `live_capture/common/publish/`

## 5. Sanitization
Do not remove field names, schema shape, or status codes.
Only remove secrets.
