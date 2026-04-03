# TWC Workbench

TWC Workbench is a server-backed enterprise web application for Teamwork Cloud 2022x and 2024x. It provides secure authentication, workspace navigation, model browsing and editing, simulation orchestration, pluggable publishing, collaborator document workflows, attachments, exports, and a live job center.

## Architecture Summary

The platform is split into two deployable tiers:

- `backend/`: FastAPI service that owns authentication, secure HTTP-only sessions, capability discovery, Teamwork Cloud API communication, version adapters, background jobs, exports, and pluggable publishing.
- `frontend/`: React + TypeScript + Material UI application that renders the enterprise workspace, landing page, navigation, simulation, compare, collaborator, search, and job center experiences.

The browser never talks directly to Teamwork Cloud. All Teamwork Cloud access, token handling, endpoint probing, and job orchestration stay on the backend.

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

- Windows: `.\launch.ps1 -PrepareOnly`, `.\launch.ps1 -NoBrowser`, `.\launch.ps1 -Port 8080`
- Linux: `bash ./launch.sh --prepare-only`, `bash ./launch.sh --no-browser`, `bash ./launch.sh --port 8080`

If PowerShell execution policy blocks script execution on Windows, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\launch.ps1
```

## Tech Stack Justification

- **FastAPI + httpx + pydantic** provide a clean async backend with strong typed models and straightforward API integration patterns.
- **Server-side session management** keeps tokens out of browser storage and supports secure HTTP-only cookies.
- **SQLite by default** gives a zero-friction local runtime for server profiles and job history while leaving room for Redis-backed sessions and external infra in production.
- **React + TypeScript + Material UI** provide a maintainable enterprise-grade frontend with responsive layout, theming, and composable workflows.
- **Adapter boundaries** isolate Teamwork Cloud version differences, publishing integrations, and remote capability uncertainty behind stable internal contracts.

## Backend Configuration

Copy `backend/.env.example` to `backend/.env` and set values appropriate for your environment.

Important settings:

- `FRONTEND_ORIGIN`: allowed browser origin for local development or deployment.
- `SESSION_SECRET`: replace with a long random secret in every non-local environment.
- `SECURE_COOKIES=true`: required when running behind HTTPS.
- `REDIS_URL`: optional, enables Redis-backed sessions.
- `PUBLISHER_MODE=local|cli|webhook`: selects the publishing adapter.
- `PUBLISHER_COMMAND`: used when `PUBLISHER_MODE=cli`.
- `PUBLISHER_WEBHOOK_URL`: used when `PUBLISHER_MODE=webhook`.
- `ENABLE_PAT_LOGIN=true`: enables the admin-only PAT fallback flow.
- `PAT_ADMIN_SECRET`: required if PAT login is enabled in a shared environment.

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
- Move SQLite to a managed relational database if you need multi-node profile and job persistence.
- Replace the default local publish adapter with `cli` or `webhook` mode when you want the backend to hand work off to an external publishing pipeline.
- If custom CA bundles are required, mount them into the backend container or VM and reference them in server profiles.

## TWC Authentication Configuration Notes

- Register the backend callback URL, not the frontend URL, with the authentication provider.
- For local development the default callback is typically `http://localhost:8000/api/auth/callback`.
- The OAuth implementation supports OIDC metadata discovery where available and falls back to derived token and userinfo endpoints when necessary.
- The callback route can resolve the server profile from OAuth state, so the callback URI does not need a server-specific query parameter.
- PAT login is optional, disabled by default, and should only be enabled for controlled administrative scenarios.

## Version Compatibility Notes

- Teamwork Cloud `2022x` and `2024x` are supported through the adapter boundary in `backend/app/adapters/teamwork.py`.
- Auto-detection probes version and endpoint availability after sign-in.
- The adapter now uses the verified main TWC Swagger surface for resource, branch, model, and element browsing when the live server exposes those endpoints.
- Version-aware request serialization is applied for the shared 2022xR2 and 2024xR3 operations that changed from `text/plain` payloads to `application/json` payloads.
- Branch rename and branch metadata edit are treated as `2024x`-only because those `PATCH` endpoints were verified only in the `2024xR3` export.
- Unknown or unavailable remote capabilities are isolated behind safe fallbacks so the UI can still operate without unsafe direct browser integrations.

## Simulation Notes

- Simulation is treated as a first-class background job.
- The verified main Teamwork Cloud Swagger does not include simulation operations, so simulation remains a separately probed capability.
- The backend attempts remote simulation endpoints first and falls back to the local adapter when remote support is not safely confirmed.
- The UI supports configuration discovery, parameter editing, execution, live logs, result metrics, history, and run comparison.

## Publishing Notes

- Publishing is intentionally pluggable, not hardcoded to a single REST path.
- The verified main Teamwork Cloud Swagger does not include publish operations, so publishing remains integration-defined rather than contract-derived.
- `local` mode generates a concrete local publish package with `manifest.json`, `summary.md`, `summary.pdf`, `index.html`, and a ZIP bundle.
- `cli` mode executes an external command.
- `webhook` mode delegates to an external job endpoint.

## Attachment Handling Notes

- Attachment upload, listing, download, and delete are exposed via backend routes.
- The verified main Teamwork Cloud Swagger does not include collaborator attachment workflows, so collaborator and attachment capability remains separate from the main TWC contract.
- Fallback storage persists uploaded files under the backend data directory when remote collaborator endpoints are not confirmed.
- Image attachments render inline previews in the collaborator workspace.

## Future Roadmap

- Add persistent relational storage for profiles, sessions, and job artifacts.
- Add remote collaborator diffing for document version comparisons.
- Expand capability probes with product-specific endpoint signatures from production Teamwork Cloud deployments.
- Add SSO provider-specific hardening and token refresh flow handling.
- Add richer simulation result visualizations and charting.
- Add packaging for Docker and container orchestration.
