# Created by: Raymond Reeves Engineering Tech 4 2026

# Workbench API Endpoint Authoring

Use this when a developer or Workbench Agent is asked to create a new Workbench API call.

## Placement map

1. Put structured request/response models in `backend/app/models/domain.py` when a route needs a typed body or shared response shape.
2. Put session-backed workspace routes in `backend/app/api/routes/workspace.py`.
3. Put cache-token automation routes in `backend/app/api/routes/cache.py`.
4. Put auth/session/bootstrap routes in `backend/app/api/routes/auth.py`.
5. Keep the route thin. Put reusable business logic in `backend/app/services/platform.py` or a focused service module.
6. Enforce access before data work:
   - `get_session` for normal authenticated reads. It accepts a live browser
     session first, then a `read`-scoped Workbench bearer API key for
     `GET`/`HEAD`/`OPTIONS` routes.
   - `require_csrf` for user writes.
   - `require_admin` or `require_admin_csrf` for Workbench-admin actions.
   - `require_cache_ingest_token` or `require_cache_api_scope(CacheApiKeyScope.WRITE)` only for documented cache-ingest automation routes.
   - Existing effective branch-access helpers for project, branch, model, and element reads.
7. Add API Explorer support for user-facing Workbench calls:
   - define a `WORKBENCH_*_OPERATION_KEY`;
   - add a `SwaggerOperationSpec`;
   - add an executor branch in `execute_swagger_operation`;
   - return a clear `SwaggerExecuteResponse`.
8. Add frontend support when the UI calls the route:
   - interfaces in `frontend/src/models/api.ts`;
   - helper function in `frontend/src/services/api.ts`;
   - page/component wiring in `frontend/src/pages/WorkspacePage.tsx` or the relevant component.
9. Add runnable examples under `examples/` and list them in `examples/README.md`.
10. Update `README.md`, `CACHE_API.md`, or a focused doc under `docs/`.
11. Validate before reporting done:
    - backend compile/tests;
    - targeted route tests;
    - frontend `npm run build`;
    - PowerShell parser checks if installer/offline scripts changed.

## Safety rules

- Never put real tokens, passwords, session cookies, or private TWC data in examples.
- Use environment variables or placeholders for credentials.
- Do not bypass Workbench permission helpers.
- Do not make admin-only calls visible or executable to non-admin users unless the route is intentionally read-only documentation.
- If a route exposes model data, it must respect the current user's effective Workbench/TWC access unless the caller is an explicit Workbench admin path.
- Do not allow bearer API keys to mutate Settings, users/groups, server presets,
  or general workspace state through `get_session`. Shared API-key support is
  for read routes; mutation routes must use session + CSRF unless a scoped
  cache-ingest/cache-edit route explicitly documents otherwise.

## Minimal backend shape

```python
@router.get("/my-feature")
def my_feature(
    projectId: str = Query(...),
    branchId: str = Query(...),
    session=Depends(get_session),
    container: ApplicationContainer = Depends(get_container),
):
    try:
        return container.platform.my_feature_for_user(
            session.server.id,
            session.user.preferred_username,
            projectId,
            branchId,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
```

For bearer-key clients calling workspace routes, include `serverId` or
`server_id` as a query parameter when the route path does not contain the server
id. `get_session` also accepts `x-workbench-server-id` and `x-twc-server-id`.

## Minimal frontend helper

```ts
myFeature(projectId: string, branchId: string) {
  const params = new URLSearchParams({ projectId, branchId });
  return request<MyFeatureResponse>(`/workspace/my-feature?${params.toString()}`);
}
```
