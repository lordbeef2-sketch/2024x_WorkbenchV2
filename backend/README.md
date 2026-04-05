# Backend

This FastAPI service is the secure integration layer for TWC Workbench. It manages delegated Teamwork Cloud sessions, direct Teamwork Cloud token sign-in, HTTP-only app sessions, admin-managed Teamwork Cloud preset servers that are visible before login, pre-login selected-server state, per-user post-login server selection state, Teamwork Cloud adapters, capability probing, background jobs, exports, collaborator workflows, and publish integrations.

Preset-management authorization is derived from Teamwork Cloud user context and trusted upstream role or group headers when they are available. The backend does not keep a separate hardcoded admin-user list.

## Verified Contract Boundary

- The adapter uses the verified main Teamwork Cloud Swagger surface for resources, branches, models, and element retrieval where the live server exposes those endpoints.
- Shared 2022xR2 and 2024xR3 operations that changed request body encoding are serialized per version so the backend does not assume `application/json` is backward-compatible with `2022xR2`.
- Branch rename and branch metadata edit are exposed as `2024x`-only capability because those `PATCH` endpoints were verified only in the `2024xR3` export.
- Simulation, collaborator, attachments, and publish are not part of the verified main TWC Swagger surface and therefore remain separately probed or integration-defined.

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
