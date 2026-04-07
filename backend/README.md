# Backend

This FastAPI service is the secure integration layer for TWC Workbench. It manages delegated Teamwork Cloud sessions, direct Teamwork Cloud token sign-in, HTTP-only app sessions, startup-loaded Teamwork Cloud preset servers from `TWC_PRESET_SERVERS`, pre-login selected-server state, per-user post-login server selection state, Teamwork Cloud adapters, and capability probing.

To change the pre-login preset catalog, edit `TWC_PRESET_SERVERS` in `backend/.env` and restart the backend.
`Sign In via TWC` is the primary path. It sends the browser to the selected Teamwork Cloud server's SAML-backed `/osmc/login.html` entry point and completes when the deployment returns authenticated Teamwork Cloud session cookies or a forwarded user-scoped TWC token to the app callback. `Use TWC Token` remains the explicit fallback. The backend does not require app-owned OAuth or OIDC client registration.

Preset-management authorization is derived from Teamwork Cloud user context and trusted upstream role or group headers when they are available. The backend does not keep a separate hardcoded admin-user list.

## Verified Contract Boundary

- The adapter uses the verified Teamwork Cloud Swagger surface in `contracts/RealSwagger.json` for resources, workspaces, branches, models, elements, revision diff, and current-user validation.
- Branch rename and branch metadata edit are not exposed because the provided `RealSwagger.json` does not define those update paths.
- Simulation, collaborator workspace, attachments, comments, documents, publish/export jobs, job center, saved searches, bookmarks, and global model search are not exposed because this Swagger file does not define those APIs.

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
