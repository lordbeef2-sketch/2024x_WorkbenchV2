# Backend

This FastAPI service is the secure integration layer for TWC Workbench. It manages delegated Teamwork Cloud sessions, direct Teamwork Cloud token sign-in, HTTP-only app sessions, startup-loaded Teamwork Cloud preset servers from `TWC_PRESET_SERVERS`, pre-login selected-server state, per-user post-login server selection state, Teamwork Cloud adapters, and capability probing.

To change the pre-login preset catalog, edit `TWC_PRESET_SERVERS` in `backend/.env` and restart the backend.
`Sign In via TWC` is the primary path. It sends the browser to the selected Teamwork Cloud Authentication Server authorize endpoint, derived by default as `https://<selected-twc-host>:8443/authentication/authorize`, exchanges the returned authorization code at `/authentication/api/token`, refreshes that token when the AuthServer returns a refresh token, and validates the user through `/osmc/admin/currentUser`. `Use TWC Token` remains the explicit fallback. The Authentication Server must have this app's callback URL whitelisted, one app client id from `authentication.client.ids`, and `authentication.client.secret` configured. This project is now documented and configured around a Teamwork Cloud 2022x deployment profile.

OSLC is a separate integration lane. The workbench now includes an OSLC Explorer that discovers `/oslc/api/rootservices`, authorizes through the server's OAuth 1.0a consumer endpoints, executes signed OSLC GET requests with the approved consumer key and secret configured in `backend/.env`, and can generate a consumer key from the root-services registration URL when the server publishes it. Generated keys still require admin approval in Magic Collaboration Studio Settings before OSLC authorization will succeed.

Preset-management authorization is derived from Teamwork Cloud user context and trusted upstream role or group headers when they are available. The backend does not keep a separate hardcoded admin-user list.

## Verified Contract Boundary

- The adapter uses the verified Teamwork Cloud Swagger surface in `contracts/RealSwagger.json` for resources, workspaces, branches, models, elements, revision diff, and current-user validation.
- Branch rename and branch metadata edit are not exposed because the provided `RealSwagger.json` does not define those update paths.
- Simulation, collaborator workspace, attachments, comments, documents, publish/export jobs, job center, saved searches, bookmarks, and global model search are not exposed because this Swagger file does not define those APIs.

## Artifact-First Extractor

For offline or scripted extraction, use `app.extractors.twc_artifact_extractor`. It intentionally starts from branch artifacts because the validated Swagger for this project exposes:

- `GET /osmc/workspaces/{workspaceId}/resources/{resourceId}/branches/{branchId}/artifacts`
- `GET /osmc/workspaces/{workspaceId}/resources/{resourceId}/branches/{branchId}/artifacts/{artifact}`
- `POST /osmc/workspaces/{workspaceId}/resources/{resourceId}/branches/{branchId}/elements`

but does not expose a root `GET .../elements` listing path for the whole branch.

Windows example:

```powershell
.\.venv\Scripts\python.exe -m app.extractors.twc_artifact_extractor `
  --base-url https://twc-host:8111 `
  --token <bearer-token> `
  --workspace-id <workspace-id> `
  --resource-id <resource-id> `
  --branch-id <branch-id> `
  --verify-tls false
```

The extractor caches discovered IDs in `backend/data/twc_artifact_extractor.sqlite3` unless you override `--cache-path`, and `--refresh-discovery` forces a new artifact walk when you need one.

Run locally from the repository root virtual environment:

Windows:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Linux:

```bash
./.venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Important environment variables are documented in `backend/.env.example` and the repository root `README.md`.
