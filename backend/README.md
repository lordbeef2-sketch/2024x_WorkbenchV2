# Backend

This FastAPI service is the secure integration layer for TWC Workbench. It manages OAuth authentication, session cookies, Teamwork Cloud adapters, capability probing, background jobs, exports, collaborator workflows, and publish integrations.

Run locally with:

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Important environment variables are documented in `backend/.env.example` and the repository root `README.md`.
