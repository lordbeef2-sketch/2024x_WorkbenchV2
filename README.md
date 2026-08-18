<!-- Created by: Raymond Reeves Engineering Tech 4 2026 -->
# TWC Workbench

TWC Workbench is a server-backed enterprise web application for Teamwork Cloud 2024x. It provides secure TWC authentication, workspace navigation, model browsing, item details, item editing where supported by the Teamwork Cloud API, and permission-scoped item, revision, branch-to-branch, and project-to-project compare workflows.

## Architecture Summary

The platform is split into two deployable tiers:

- `backend/`: FastAPI service that owns authentication, secure HTTP-only sessions, capability discovery, Teamwork Cloud API communication, and version adapters.
- `frontend/`: React + TypeScript + Material UI application that renders the landing page, dashboard, project browser, model browser, item details, and compare experiences.

The browser never talks directly to Teamwork Cloud. All Teamwork Cloud access, token handling, and endpoint probing stay on the backend.

## One-Script Launch

Run the platform from the repository root with a single script:

Windows:

```powershell
.\launch.ps1
```

Linux:

```bash
bash ./launch.sh
```

What the launchers do:

- Windows launcher checks all `.ps1` files under the repository and unblocks any that still carry a Windows download mark.
- Both launchers create or reuse the root `.venv`.
- Both launchers install backend dependencies when `backend/pyproject.toml` changes.
- Both launchers install frontend dependencies when `frontend/package.json` changes.
- Both launchers attempt `npm audit fix` after frontend dependency installation and continue with a warning when the npm audit endpoint is unreachable or blocked by local certificate trust.
- Both launchers rebuild the frontend when source files change.
- Both launchers set `FRONTEND_ORIGIN` to the backend URL for a single-origin launch.
- Both launchers start FastAPI so the backend serves both the API and the built frontend.

Useful options:

- Windows: `.\launch.ps1 -PrepareOnly`, `.\launch.ps1 -NoBrowser`, `.\launch.ps1 -Port 8080`, `.\launch.ps1 -BindHost 127.0.0.1`
- Linux: `bash ./launch.sh --prepare-only`, `bash ./launch.sh --no-browser`, `bash ./launch.sh --port 8080`, `bash ./launch.sh --host 127.0.0.1`

If PowerShell execution policy blocks script execution on Windows, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\launch.ps1
```

## Tech Stack Justification

- **FastAPI + httpx + pydantic** provide a clean async backend with strong typed models and straightforward API integration patterns.
- **Server-side session management** keeps tokens out of browser storage and supports secure HTTP-only cookies.
- **SQLite by default** gives a zero-friction local runtime for preset server definitions and per-user server selection state while leaving room for Redis-backed sessions and external infra in production.
- **React + TypeScript + Material UI** provide a maintainable enterprise-grade frontend with responsive layout, theming, and composable workflows.
- **Adapter boundaries** isolate Teamwork Cloud version differences and remote capability uncertainty behind stable internal contracts.

## Backend Configuration

Copy `backend/.env.example` to `backend/.env` and set values appropriate for your environment.

`backend/.env` is now a small bootstrap file. Normal administration happens in Workbench Settings.
TWC server presets are created, edited, enabled, disabled, and deleted from the Settings page. `TWC_PRESET_SERVERS` remains only an optional startup seed/import path; leaving it empty no longer wipes app-managed presets.
User-management mode is also saved from Settings. The env value only picks the initial mode when no app setting exists yet.
`Sign In via TWC` is the primary sign-in path. It uses the official Teamwork Cloud 2024x Refresh3 OpenID Connect authorization-code flow. Workbench reads `https://<selected-twc-host>:8443/authentication/.well-known/oidc-configuration`, redirects to its `authorization_endpoint`, exchanges the code at its `token_endpoint` using `client_secret_basic`, requests `scope=openid`, refreshes the ID token when a refresh token is returned, and validates the user through `/osmc/admin/currentUser`. SAML may remain the Authentication Server's upstream identity provider, but it is not the protocol between Workbench and the Authentication Server. `Use TWC Token` remains the explicit fallback.
The supplied launchers disable Uvicorn access logging so the authorization code
in the callback query string is not copied into console logs. Application audit
events remain available through structured Workbench logging.
The bundled 3DS 2024x source package documents OSLC resources, but it does not define an OSLC authentication contract for this Workbench. The previous consumer-key/request-token implementation was removed because it was not supported by that source package or a captured live-server contract. OSLC access must remain unavailable until its actual 2024x endpoints and authentication exchange are captured and tested.
Preset-management authorization is derived from Teamwork Cloud or trusted reverse-proxy role and group context. When no upstream role or group claims are available, the app defaults to allowing authenticated users rather than maintaining a separate authorization list.

Important settings:

- `HOST`: bind address for this app only. Use `0.0.0.0`, `127.0.0.1`, or a local interface IP. Do not put the Teamwork Cloud FQDN here.
- `FRONTEND_ORIGIN`: allowed browser origin for local development or deployment.
- `APP_ORIGIN`: optional public origin of this app when it is served behind a reverse proxy. Defaults to `FRONTEND_ORIGIN` when left empty. Set this in deployed environments if you want the app to auto-register Teamwork Cloud 2024x branch webhooks for cache refresh.
- `SESSION_SECRET`: replace with a long random secret in every non-local environment. It encrypts stored per-user delegated credentials inside the app session.
- `WORKBENCH_DEFAULT_ADMIN_USERNAME` / `WORKBENCH_DEFAULT_ADMIN_PASSWORD`: first local-mode bootstrap login when no Workbench users exist. Defaults are `admin` / `admin`; rotate immediately in Settings.
- `WORKBENCH_USER_MANAGEMENT_MODE`: initial user-management authority only. Settings owns it afterward.
- `TWC_PRESET_SERVERS`: optional JSON array used only to seed/import preset Teamwork Cloud servers at startup.
- `SECURE_COOKIES=true`: required when running behind HTTPS.
- `UPSTREAM_AUTH_COOKIE_NAMES`: optional JSON array of TWC cookie names to forward. Leave empty to forward all incoming cookies except the app's own session cookie.
- `UPSTREAM_USER_HEADERS`: optional JSON array of trusted reverse-proxy user headers.
- `UPSTREAM_GROUP_HEADERS`: optional JSON array of trusted reverse-proxy group headers used to mirror TWC group membership.
- `UPSTREAM_ROLE_HEADERS`: optional JSON array of trusted reverse-proxy role headers used to mirror TWC role membership.
- `UPSTREAM_ACCESS_TOKEN_HEADERS`: optional JSON array of trusted reverse-proxy TWC token headers.
- Teamwork Cloud server auth is configured from **Settings -> Servers**. Each server profile has an explicit auth setup mode: **Authentication ID method**, **OpenID**, or **OAuth**. Environment values below are legacy/bootstrap fallbacks only; saved Settings values win.
- `TWC_AUTH_APPLICATION_IDS` / `TWC_APPLICATION_IDS`: legacy/bootstrap fallback for the Workbench Application ID(s) value from TWC Configs. Defaults to `twcworkbench`.
- `TWC_AUTH_CLIENT_ID`: compatibility alias for the same Workbench Application ID(s) value.
- `TWC_AUTH_CLIENT_SECRET`: the generated secret for that OIDC client.
- `TWC_AUTHENTICATION_CLIENT_ID`, `TWC_AUTHENTICATION_CLIENT_IDS`, `TWC_AUTHENTICATION_CLIENT_SECRET`: optional aliases for the same TWC AuthServer properties.
- `TWC_AUTH_SCOPE`: defaults to the documented `openid` scope.
- `TWC_OIDC_DISCOVERY_URL`: optional complete 2024x Refresh3 discovery URL; otherwise Workbench derives it from the selected server.
- `TWC_OIDC_AUTHORIZE_URL` / `TWC_OIDC_TOKEN_URL`: optional explicit endpoint overrides. Normally leave them blank and use discovery.
- `TWC_OIDC_TOKEN_AUTH_METHOD`: defaults to the documented `client_secret_basic` method.
- `TWC_OIDC_RETURN_URL_PARAMETER`: query parameter used to pass the app callback URL to the TWC OIDC authorization endpoint. Defaults to `redirect_uri`.
- `TWC_AUTH_SERVER_OVERRIDES`: optional JSON object keyed by preset server id for AuthServer hosts, client ids/application ids, secrets, ports, paths, scopes, and return parameter names.
- `CACHE_INGEST_TOKENS`: optional legacy fallback list for plugin write tokens. The preferred path is to manage the plugin ingest token from Workbench admin Settings.
- `CACHE_API_TOKENS`: optional legacy fallback map of bearer token to Workbench username for cache-read API access. The preferred path is to let users create their own API keys from Workbench Settings.
- `PERMISSION_SNAPSHOT_REFRESH_MINUTES`: active-user effective permissions are atomically replaced on this interval; defaults to `30`.
- `PERMISSION_INVENTORY_REFRESH_HOURS`: refresh interval for the shared role/group catalog; defaults to `6`.
- `JOB_RETENTION_DAYS`: automatic retention period for completed, failed, and cancelled job records; defaults to `30`.
- `PERMISSION_SNAPSHOT_MAX_PARALLEL_PROBES`: bounded compatibility-probe concurrency when TWC does not return complete current-user permission claims; defaults to `2` and Workbench enforces an effective maximum of `2`.
- `PERMISSION_REFRESH_LEASE_SECONDS`: renewable database lease used to prevent duplicate cross-worker refreshes; defaults to `900`.
- `PERMISSION_REFRESH_WARNING_FAILURES`: consecutive indeterminate attempts before a persistent warning; defaults to `3`.
- `PERMISSION_ALERT_WEBHOOK_URL`: optional endpoint for sanitized repeated inventory-refresh failure alerts.
- `PERMISSION_SNAPSHOT_STALE_WARNING_MINUTES`: age of the last valid snapshot before a persistent warning; defaults to `120`.
- `REDIS_URL`: optional, enables Redis-backed sessions.
Teamwork Cloud base URLs, version hints, certificate settings, and preset ordering are configured through Workbench Settings, not through `HOST`.

The launch scripts read `HOST` and `PORT` from `backend/.env` by default. Command-line launch options override them when provided.

## Developer API

Workbench now includes a cache-first developer API for scripts, AI tools, and
external integrations.

- Users create labeled API keys from the Workbench `Developer API` tab or
  Settings.
- `read` keys authenticate Workbench `GET`, `HEAD`, and `OPTIONS` read routes
  with `Authorization: Bearer <api-key>`. This includes cache reads and
  workspace read helpers such as model-cache/owned-elements and comparison
  endpoints when the route accepts the same query parameters the browser uses.
- Browser/admin mutations still require a live Workbench browser session and
  CSRF token. Plugin cache ingestion uses the separate plugin ingest token, or
  a Workbench API key with the dedicated `write` scope on cache-ingest routes.
- `edit` scope is reserved for scoped cache-edit endpoints and does not turn a
  bearer key into a general Workbench admin/write session.
- The shared model cache is stored once per branch, while Workbench maintains a
  per-user visibility and editability overlay so TWC access stays user-scoped
  without caching the same model N times.
- TWC REST is used for current-user and administrative permission data. It does
  not enumerate models or elements or create partial model caches.
- Projects, branches, models, and elements appear only from authoritative
  Cameo Workbench plugin snapshots.
- Cached project discovery is storage-only. The current user's effective TWC
  permission response is compared with all locally registered Cameo snapshots,
  allowing authorized users to discover projects published by someone else
  without exposing them to users who lack TWC access.
- The Workbench project selector refreshes on focus and every 30 seconds so an
  already-open session discovers newly published shared projects.
- Login evaluates the signed-in user only against Workbench's local registry of
  uploaded project branches and persists the results per user. Subsequent list
  refreshes reuse those records and never probe the model tree.
- Effective Workbench access merges TWC's direct authenticated branch result
  with direct project roles, group and nested-group roles, read-only branch
  overrides, and resource-scoped project-administration permissions. Global
  Server Administrator status does not imply resource edit or project-admin
  access.
- Every exposed branch operation enforces the corresponding effective flag:
  view for browsing, edit for model changes, access-right administration for
  permission-map actions, and resource administration for branch actions.
- Workbench captures a complete effective permission snapshot for the
  authenticated user at login. Normal browsing and authorization read that
  stored snapshot without repeatedly calling TWC. Active users are refreshed
  every 30 minutes, and each refresh atomically replaces—not merges—the user's
  prior branch and model permissions so confirmed revoked access cannot
  survive. Temporary TWC failures retain the last valid snapshot and retry;
  they are not treated as proof that access was revoked.
- The shared six-hour role/group inventory produces a revision-bound project
  ACL that is reused across users. A Server Administrator login or an upload
  observed while an administrator session is active queues a deduplicated
  background inventory job when the inventory is missing, dirty, or expired;
  neither request waits for the scan. Uploads wake the background scheduler
  immediately, and interrupted inventory jobs are safely made retryable after
  a Workbench restart. Regular users never scan the global administration
  endpoints. Settings shows the local inventory/job status, metrics, recent
  append-only audit events, no-active-admin warnings, and a non-blocking retry,
  and user refreshes keep the open model mounted until an authoritative result
  removes that user's access.
- Every Cameo snapshot/delta upload carries a permission manifest alongside the
  branch revision. Workbench retains package ACL evidence from Cameo, merges in
  the current TWC resource-role map when that endpoint is available, and records
  the comparison with each user's effective snapshot. The attachment is audit
  evidence only: current authenticated TWC REST results always decide access.
- ACL-changing deltas make active user snapshots due immediately. Revision-
  guarded branch tombstones atomically remove deleted branches and their stored
  grants while retaining an append-only deletion record.

Operational multi-worker restart checks, verified SQLite backups, and a real
Workbench-to-TWC smoke runner are provided under `backend/ops`.

See:

- [docs/WORKBENCH_API_VARIABLES.md](docs/WORKBENCH_API_VARIABLES.md)
- [docs/WORKBENCH_API_ENDPOINT_AUTHORING.md](docs/WORKBENCH_API_ENDPOINT_AUTHORING.md)
- [CACHE_API.md](CACHE_API.md)
- [examples/README.md](examples/README.md)

The Model Browser now requests the complete accessible containment tree from
the plugin-backed branch snapshot. The lazy child endpoint remains available
for integrations and recovery, but filtering and navigation operate against
the full tree instead of model headers alone.

Workbench Agent uses the verified reference corpus bundled with the installed
Workbench application. The raw corpus is intentionally not committed into
normal Git history because it is a multi-gigabyte release payload; the
offline/release package copies it into the install root. Before retrieval, the
bundled corpus controller, manifest, validation anchor, all manifest rows, and
every Markdown document are serially verified to produce the controller-required
completion certificate. Persistent OWUI files carry Workbench operating
guidance and the validated reference control rails. For each user question,
Workbench routes the most relevant documents from that internal corpus into the
OWUI system context and attaches the current user's permission-scoped branch
model file. There is no admin-configurable KB path, generated-KB, repository,
external user-profile, or `C:\sand` fallback.
Open WebUI connection policy is admin-managed in Settings > Agentic Settings.
Local/enterprise defaults keep HTTPS as the required scheme but disable TLS
certificate verification so an internal domain or self-signed/private-CA OWUI
host can be used without certificate blocking. Admins can turn certificate
verification back on, set an internal CA bundle path, optionally allow plain
HTTP for lab-only hosts, and restrict destinations with an allowed-host list.
Workbench still rejects embedded credentials, query strings, and fragments in
the Open WebUI base URL.
Agent knowledge pushes execute as background Workbench jobs and the UI polls
their status, so large Open WebUI ingestion runs are not held inside one HTTP
request that a gateway can terminate. Each completed reference segment is
checkpointed, so a later gateway or processing failure resumes at the first
unfinished segment instead of re-uploading the processed prefix.

## Frontend Configuration

Copy `frontend/.env.example` to `frontend/.env` when you need to override the default API base path.

By default the frontend uses `VITE_API_BASE=/api`, which works with both:

- Vite dev proxy during local development.
- Backend-served static assets when the frontend has been built into `frontend/dist`.

## Dependencies

Backend dependencies are declared in `backend/pyproject.toml`.

Frontend dependencies are declared in `frontend/package.json`.

## Setup Instructions

### Backend

1. Create a Python 3.11+ virtual environment.
2. Install the backend package in editable mode.
3. Copy `backend/.env.example` to `backend/.env`.
4. Set `SESSION_SECRET` and environment-specific values.

Windows example:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e backend
Copy-Item backend/.env.example backend/.env
```

Linux example:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e backend
cp backend/.env.example backend/.env
```

### Offline installation

For disconnected Windows environments, use the two-script workflow under
[`offline`](offline/README.md). Run `Offline-Prep.ps1` on a connected machine to
build and hash a platform-matched ZIP, then run `Offline-Installer.ps1` from the
extracted bundle on the offline host. The offline host needs the matching Python
3.11+ line but does not need Node.js or internet access.

### Frontend

1. Install Node.js 20+.
2. Install frontend dependencies.
3. Run `npm audit fix`.
4. Optionally copy `frontend/.env.example` to `frontend/.env`.

Windows example:

```powershell
Set-Location frontend
npm install
npm audit fix
Copy-Item .env.example .env
```

Linux example:

```bash
cd frontend
npm install
npm audit fix
cp .env.example .env
```

## Run Instructions

### Preferred

From the repository root:

Windows:

```powershell
.\launch.ps1
```

Linux:

```bash
bash ./launch.sh
```

Open `http://localhost:8000`.

### Development

Run backend on Windows:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --no-access-log
```

Run backend on Linux:

```bash
./.venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --no-access-log
```

Run frontend in a second terminal:

```bash
cd frontend
npm run dev
```

Open `http://localhost:5173`.

### Production-style Single-Origin Serve

Build the frontend:

```powershell
cd frontend
npm run build
```

Then run the backend. If `frontend/dist` exists, FastAPI serves it automatically from the root path.

## Deployment Notes

- Terminate TLS at a reverse proxy or application gateway and forward traffic to FastAPI.
- Set `SECURE_COOKIES=true` behind HTTPS.
- Move sessions to Redis via `REDIS_URL` for multi-instance deployments.
- Move SQLite to a managed relational database if you need multi-node preset and per-user state.
- If custom CA bundles are required, mount them into the backend container or VM and reference them in server profiles.

## TWC Authentication Configuration Notes

- TWC is the authentication and authorization authority for this app.
- Preset Teamwork Cloud servers are loaded from `TWC_PRESET_SERVERS` at startup and are readable on the landing page before app login.
- Users select a preset server first, then authenticate against that selected Teamwork Cloud server.
- The post-login app session is bound to the selected server, not the other way around.
- Redirect-based `Sign In via TWC` sends the browser to the selected preset's AuthServer authorize endpoint, preserves the selected preset server, and completes the app session on the callback route after exchanging the returned authorization code.
- Pick the server auth setup mode in **Settings -> Servers**. **Authentication ID method** maps to Teamwork Cloud AuthServer `authserver.properties`; **OpenID** exposes discovery/authorize/token endpoints; **OAuth** exposes OSLC/RealSwagger consumer key, secret, callback, and base URL fields.
- The callback URL is the Workbench public app URL, normally `https://<workbench-host>:<public-port>/api/auth/callback`; whitelist that same callback in every TWC/AuthServer client registration that should be able to return users to this app. If Workbench is behind Caddy or another reverse proxy, set the server profile's **Workbench Public URL** to the external URL users browse to. Do not use `localhost` for a shared deployment callback.
- Configure Teamwork Cloud AuthServer so `authserver.properties` includes the Workbench callback URI in `authentication.redirect.uri.whitelist`, includes the Workbench Application ID in `authentication.client.ids` (normally `twcworkbench`), and uses the matching `authentication.client.secret` in the Workbench server profile or `TWC_AUTH_CLIENT_SECRET` / `TWC_AUTH_SERVER_OVERRIDES`.
- If your deployment bypasses the AuthServer code flow, the callback must receive authenticated Teamwork Cloud session cookies or a forwarded user-scoped TWC token from your proxy or auth gateway.
- `Use TWC Token` remains the explicit fallback when your deployment cannot return authenticated TWC context to the callback.
- If your proxy cannot forward Teamwork Cloud session cookies, configure `UPSTREAM_ACCESS_TOKEN_HEADERS` to pass a user-scoped TWC token instead.
- Direct token sign-in is also supported from the landing page. The backend validates the supplied token against `/osmc/admin/currentUser` before opening a workbench session.
- Optional trusted user headers in `UPSTREAM_USER_HEADERS` are used only as identity hints and authorization context when a reverse proxy already knows the authenticated TWC user; they do not replace the required Teamwork Cloud session cookies or forwarded token for callback completion.

## 2024x Profile

- The project is configured, documented, and defaulted for Teamwork Cloud `2024x`.
- New preset server definitions default to version `2024x`.
- The adapter uses the verified main TWC Swagger surface for resource, branch, model, and element browsing when the live server exposes those endpoints.
- Branch rename and branch metadata edit are available on 2024x deployments when the live server accepts the PATCH paths defined in `contracts/RealSwagger.json`.
- Unknown or unavailable remote capabilities are not replaced with local workspace fallbacks.

## Removed API Surface

`contracts/RealSwagger.json` is treated as the entire Teamwork Cloud API contract for this app. Simulation, collaborator workspace, global model search results, publish/export jobs, job center, saved searches, bookmarks, comments, documents, and attachments are not exposed because this Swagger file does not define those APIs.

## Future Roadmap

- Add persistent relational storage for profiles and sessions.
- Add SSO provider-specific hardening and token refresh flow handling.
- Add packaging for Docker and container orchestration.
