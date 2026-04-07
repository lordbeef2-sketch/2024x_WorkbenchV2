# TWC Workbench

TWC Workbench is a server-backed enterprise web application for Teamwork Cloud 2022x and 2024x. It provides secure TWC authentication, workspace navigation, model browsing, item details, item editing where supported by the Teamwork Cloud API, and compare workflows derived from `contracts/RealSwagger.json`.

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

`backend/.env` remains the app runtime configuration file, and it also carries the preset Teamwork Cloud catalog through `TWC_PRESET_SERVERS`.
`TWC_PRESET_SERVERS` is the authoritative JSON catalog for pre-login Teamwork Cloud discovery. Each preset includes `id`, `name`, `base_url`, `version`, `verify_tls`, `ca_bundle_path`, `enabled`, and `display_order`.
The backend loads that catalog at startup and exposes enabled presets on the landing page before authentication. Users do not create their own target servers just to connect; the app persists only each user’s selected and last-used server state separately.
To change the pre-login preset catalog, edit `TWC_PRESET_SERVERS` and restart the backend.
`Sign In via TWC` is the primary sign-in path. It redirects to the selected Teamwork Cloud server's SAML-backed `/osmc/login.html` entry point, preserves the selected Teamwork Cloud server, returns through the app callback, and completes only when that callback receives authenticated Teamwork Cloud session cookies or a forwarded user-scoped TWC token from your deployment. `Use TWC Token` remains the explicit fallback. The app does not require an app-owned OAuth or OIDC client configuration.
Preset-management authorization is derived from Teamwork Cloud or trusted reverse-proxy role and group context. When no upstream role or group claims are available, the app defaults to allowing authenticated users rather than maintaining a separate authorization list.

Important settings:

- `HOST`: bind address for this app only. Use `0.0.0.0`, `127.0.0.1`, or a local interface IP. Do not put the Teamwork Cloud FQDN here.
- `FRONTEND_ORIGIN`: allowed browser origin for local development or deployment.
- `APP_ORIGIN`: optional public origin of this app when it is served behind a reverse proxy. Defaults to `FRONTEND_ORIGIN` when left empty.
- `SESSION_SECRET`: replace with a long random secret in every non-local environment. It encrypts stored per-user delegated credentials inside the app session.
- `TWC_PRESET_SERVERS`: JSON array of preset Teamwork Cloud servers loaded at startup for pre-login discovery.
- `SECURE_COOKIES=true`: required when running behind HTTPS.
- `UPSTREAM_AUTH_COOKIE_NAMES`: optional JSON array of TWC cookie names to forward. Leave empty to forward all incoming cookies except the app's own session cookie.
- `UPSTREAM_USER_HEADERS`: optional JSON array of trusted reverse-proxy user headers.
- `UPSTREAM_GROUP_HEADERS`: optional JSON array of trusted reverse-proxy group headers used to mirror TWC group membership.
- `UPSTREAM_ROLE_HEADERS`: optional JSON array of trusted reverse-proxy role headers used to mirror TWC role membership.
- `UPSTREAM_ACCESS_TOKEN_HEADERS`: optional JSON array of trusted reverse-proxy TWC token headers.
- `TWC_SAML_LOGIN_PATH`: browser login path on the selected Teamwork Cloud server. Defaults to `/osmc/login.html`.
- `TWC_SAML_RETURN_URL_PARAMETER`: query parameter used to pass the app callback URL to the TWC login entry point. Defaults to `redirect`.
- `REDIS_URL`: optional, enables Redis-backed sessions.
Teamwork Cloud base URLs, version hints, certificate settings, and preset ordering are configured through `TWC_PRESET_SERVERS`, not through `HOST`.

The launch scripts read `HOST` and `PORT` from `backend/.env` by default. Command-line launch options override them when provided.

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

### Frontend

1. Install Node.js 20+.
2. Install frontend dependencies.
3. Optionally copy `frontend/.env.example` to `frontend/.env`.

Windows example:

```powershell
Set-Location frontend
npm install
Copy-Item .env.example .env
```

Linux example:

```bash
cd frontend
npm install
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
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Run backend on Linux:

```bash
./.venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
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
- Redirect-based `Sign In via TWC` sends the browser to TWC's SAML v2 login front door, preserves the selected preset server, and completes the app session on the callback route.
- The callback must receive authenticated Teamwork Cloud session cookies or a forwarded user-scoped TWC token from your proxy or auth gateway.
- `Use TWC Token` remains the explicit fallback when your deployment cannot return authenticated TWC context to the callback.
- If your proxy cannot forward Teamwork Cloud session cookies, configure `UPSTREAM_ACCESS_TOKEN_HEADERS` to pass a user-scoped TWC token instead.
- Direct token sign-in is also supported from the landing page. The backend validates the supplied token against `/osmc/admin/currentUser` before opening a workbench session.
- Optional trusted user headers in `UPSTREAM_USER_HEADERS` are used only as identity hints and authorization context when a reverse proxy already knows the authenticated TWC user; they do not replace the required Teamwork Cloud session cookies or forwarded token for callback completion.

## Version Compatibility Notes

- Teamwork Cloud `2022x` and `2024x` are supported through the adapter boundary in `backend/app/adapters/teamwork.py`.
- Auto-detection probes version and endpoint availability after sign-in.
- The adapter now uses the verified main TWC Swagger surface for resource, branch, model, and element browsing when the live server exposes those endpoints.
- Version-aware request serialization is applied for the shared 2022xR2 and 2024xR3 operations that changed from `text/plain` payloads to `application/json` payloads.
- Branch rename and branch metadata edit are not exposed because the provided `RealSwagger.json` does not define those update paths.
- Unknown or unavailable remote capabilities are not replaced with local workspace fallbacks.

## Removed API Surface

`contracts/RealSwagger.json` is treated as the entire Teamwork Cloud API contract for this app. Simulation, collaborator workspace, global model search results, publish/export jobs, job center, saved searches, bookmarks, comments, documents, and attachments are not exposed because this Swagger file does not define those APIs.

## Future Roadmap

- Add persistent relational storage for profiles and sessions.
- Add SSO provider-specific hardening and token refresh flow handling.
- Add packaging for Docker and container orchestration.
