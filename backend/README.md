# Backend

This FastAPI service is the secure integration layer for TWC Workbench. It manages delegated Teamwork Cloud sessions, direct Teamwork Cloud token sign-in, HTTP-only app sessions, startup-loaded Teamwork Cloud preset servers from `TWC_PRESET_SERVERS`, pre-login selected-server state, per-user post-login server selection state, Teamwork Cloud adapters, and capability probing.

To change the pre-login preset catalog, edit `TWC_PRESET_SERVERS` in `backend/.env` and restart the backend.
`Sign In via TWC` is the primary path. It uses Teamwork Cloud 2024x Refresh3 OpenID Connect discovery at `/authentication/.well-known/oidc-configuration`, authorization code flow, `scope=openid`, and the discovered token endpoint with `client_secret_basic`, then validates the returned ID token through `/osmc/admin/currentUser`. Register the exact callback URI in Web Application Platform Settings -> OAuth clients -> OpenID Connect and configure the generated client ID and secret in Workbench. SAML may be configured behind AuthServer as its upstream identity provider; Workbench itself is an OIDC client. `Use TWC Token` remains the explicit fallback.

OSLC authentication is intentionally not implemented. The bundled 3DS 2024x package documents OSLC resources but does not define the authentication exchange needed by this application, and no captured live-server contract is checked into the repository. The unsupported consumer-key/request-token implementation was removed instead of being presented as verified TWC 2024x behavior.

The backend also supports plugin-fed model cache ingestion. The preferred setup is to generate the plugin ingest token inside the admin Settings screen, where Workbench stores it encrypted in app storage. `CACHE_INGEST_TOKENS` remains available as a legacy fallback for bearer-authenticated writes into:

- `POST /api/cache-ingest/branch-snapshots`
- `POST /api/cache-ingest/branch-deltas`
- `POST /api/cache-ingest/branch-tombstones`
- `POST /api/cache-ingest/project-tombstones`

Users can now create their own cache API keys from Workbench Settings for scripts, AI tools, and other integrations. Each key carries explicit `read`, `write`, and `edit` scopes. `CACHE_API_TOKENS` remains available as a legacy fallback for environment-managed bearer tokens. Cache access is exposed through:

- `GET /api/cache`
- `GET /api/cache/servers`
- `GET /api/cache/servers/{server_id}/projects`
- `GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/summary`
- `GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/snapshot`
- `GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/tree`
- `GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/nodes/{parent_id}/children`
- `GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/models`
- `GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/models/{model_id}`
- `GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements`
- `GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/search`
- `GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/by-stereotype`
- `GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/{element_id}`
- `GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/{element_id}/details`
- `GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/{element_id}/graph`
- `PATCH /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/{element_id}`

Workspace comparison also supports `GET /api/workspace/compare/branches` with independent `leftProjectId`, `leftBranchId`, `rightProjectId`, and `rightBranchId` parameters. It compares the complete accessible cached element sets, matches same-project branches by element ID, and matches different projects by qualified path plus metaclass.

Use `Authorization: Bearer <api-key>` on those requests. The API key identity maps back to the Workbench user who created it, so cache reads stay scoped to that user's cached visibility instead of becoming a server-wide bypass.
`write` scope also allows the cache-ingest snapshot, delta, and tombstone routes. `edit` scope allows cache edits on plugin-backed branches when the user's TWC model permission overlay marks that model editable.
Stereotype search accepts either a stereotype id or a stereotype name fragment and can return either lightweight cached element records or full cached item details with `includeDetails=true`.
Key labels, creation time, and last-used time are stored for light auditability, while the full secret is only shown once at creation time.

Workbench uses TWC REST for permission authority only. Background and manual
REST model/element fallback synchronization are disabled. Projects, branches,
models, elements, specifications, usages, and presentation data enter the
shared cache only through Cameo Workbench plugin snapshots. The old REST
fallback status, manual refresh, and model-cache sync routes are not exposed.

The cache API stores the shared branch model payload once and keeps per-user
permission overlays separately. That avoids duplicating the same branch model
for every user while still keeping visibility scoped to the TWC-backed
Workbench user identity.
Project listing is storage-only. Login and the 30-minute active-user refresh
compare TWC's effective current-user permission response with the locally
registered Cameo plugin branches, then atomically replace that user's visibility
overlay. A project published by another Workbench user appears when the viewer's
stored TWC permission snapshot grants access; inaccessible projects remain hidden.
The uploaded project registry is the local `branch_cache_summaries` table and
the per-user result map is `branch_access_records`. Login refreshes the current
user against those registered branches with bounded concurrency. Later project
list reads reuse matching revision records and contact TWC only for a newly
uploaded branch, a changed revision, or an explicit refresh; model elements are
never scanned to determine project visibility.
Each stored user/branch result merges the direct effective-access probe with
the detailed TWC role manifest: direct role assignments, group and nested-group
assignments, view/edit/admin role flags, read-only branch overrides, and the
authenticated session's role/group identity. Workbench enforces the resulting
view/edit/admin flags rather than granting permissions merely because a user is
known to the application.
TWC global Server Administrator authority is kept separate from resource
authority: it does not grant branch editing or project administration without
the corresponding resource-scoped permissions.
Read, edit, access-right administration, and branch/resource administration are
checked independently. An editor cannot refresh the shared permission map
without Manage Owned Resource Access Right (or Manage User Permissions), and a
branch action requires the documented Read Resources, Edit Resources, Edit
Resource Properties, and Administer Resources combination.
At login, the backend probes every plugin-uploaded branch for the authenticated
identity and stores one complete user/server permission snapshot. Request-time
authorization uses only that stored snapshot. A background task refreshes each
active identity every 30 minutes (configurable with
`PERMISSION_SNAPSHOT_REFRESH_MINUTES`) and replaces both branch and model
permission rows in one SQLite transaction. Missing, removed, and revoked grants
are deleted only after a successful authoritative refresh. A gateway error,
credential-refresh interruption, malformed response, or branch-probe failure
is indeterminate rather than proof of revocation, so Workbench retains the last
valid snapshot and retries later. Database transactions remain all-or-nothing,
so readers never receive a partially refreshed permission set.
The server-wide inventory of every role, group, nested membership, and scoped
role assignment is stored separately and refreshed every six hours by default
(`PERMISSION_INVENTORY_REFRESH_HOURS`). A new full branch upload marks that
inventory dirty without discarding its last complete role-ID map and makes
active sessions due for the next background user-permission refresh. If an
active Server Administrator session exists, the application loop queues a
separate `permission_inventory_refresh` job; otherwise the next Server
Administrator login queues it. Login and upload responses never wait for the
global roles/groups scan. A full upload signals the scheduler immediately
instead of waiting for its next one-minute cadence.
The inventory supports discovery and comparison only; fresh current-user
effective permissions and direct branch access remain the 30-minute security
authority, so a stale inventory cannot preserve a revoked grant.
Each revision-bound TWC role manifest is also reused as a derived project ACL
until either the server inventory or branch revision changes. This avoids
rescanning every group and role for every logged-in user while leaving fresh
current-user claims and direct probes authoritative.
On every Server Administrator login, Workbench checks whether the shared
inventory is missing, marked dirty by a full upload, or older than six hours,
then deduplicates and queues the background job when needed. Only a current
Server Administrator TWC session can perform the scan. Regular-user logins and
scheduled user refreshes reuse the last complete inventory and never call the
global administration endpoints. Administrators can inspect the local,
lightweight `GET /api/workspace/permission-inventory/status` result in Settings;
it reports dirty/refreshing/failure state, timestamps, role/group counts, and
the most recent job without triggering an upstream scan. The same panel reports
inventory age, duration and success/failure metrics, warns when a refresh is due
without an active Server Administrator, and offers a non-blocking `Retry Now`
action. `GET /api/workspace/permission-inventory/audit` exposes the append-only
attempt history; it stores before/after hashes, counts, trigger, administrator,
duration, and sanitized failures rather than duplicating permission contents.
At startup, abandoned pending/running jobs are marked interrupted and inventory
work is made due for safe requeue through the next active administrator session.
Terminal jobs older than `JOB_RETENTION_DAYS` (30 by default) are deleted daily;
permission audit records are retained separately.
The UI's Refresh Capabilities action does not run that server-wide inventory
scan. It immediately queues a `permission_refresh` job, refreshes the signed-in
user's effective permission claims, filters
the uploaded registry to matching global/workspace/project Read Resources
scopes, and replaces permissions only for those permitted projects.
That interactive path uses the locally registered uploaded-project/branch
catalog: it does not enumerate the TWC model tree, elements, all users, all
groups, or all roles. A complete current-user permission response requires no
per-branch permission probe. Read-only branches are fetched once per matching
project and reused for all of its registered branches. Older TWC responses that
omit effective permissions use the bounded compatibility probe path only.
The open model and its cached queries remain mounted during this work. The UI
reconciles project, branch, and model access independently, closing only the
selection whose access was authoritatively revoked.
The UI polls `GET /api/workspace/permissions/current` against the stored
snapshot for its selected project/branch/model; this lightweight check performs
no upstream TWC call and also catches scheduled-refresh revocations.
SQLite-backed renewable leases coordinate refresh ownership across backend
workers. Compatibility-probe concurrency is bounded by
`PERMISSION_SNAPSHOT_MAX_PARALLEL_PROBES` (default and effective maximum `2`), with the
selected project/branch queued first. Every completed or indeterminate pass appends a sanitized audit
record containing before/after hashes and grant/revocation deltas; administrators
can query `GET /api/workspace/permission-refresh/audit`. Repeated failures are
surfaced after `PERMISSION_REFRESH_WARNING_FAILURES` attempts or
`PERMISSION_SNAPSHOT_STALE_WARNING_MINUTES` without a valid replacement.
Workbench recognizes explicit `editable` values as well as TWC permission,
allowed-action, and allowed-operation payloads when resolving effective edit
rights.

Every plugin snapshot and delta also stores a revision-bound permission
attachment. Cameo contributes its project/package ACL entries; a successful TWC
role enumeration merges direct users, expanded groups, view/edit, branch-admin,
access-admin, and read-only branch results into that attachment. Login compares
the prior attachment with the newly proven effective access before atomically
replacing the user's permission rows. Attached data never grants access by
itself, and a failed current-user probe is treated as indeterminate while the
last valid snapshot remains in force.
When a delta changes ACL evidence, Workbench marks active user permission
snapshots due without rescanning global roles/groups. A revision-guarded branch
tombstone atomically removes the stored branch, model data, per-user grants,
permission attachment, webhook registration, and access file. Its append-only
record remains available through `GET /api/workspace/branch-tombstones`.
The project tombstone performs the equivalent deletion for every stored branch
in one transaction and retains a project-level record.

Set `PERMISSION_ALERT_WEBHOOK_URL` to forward sanitized repeated global
inventory failures at multiples of `PERMISSION_REFRESH_WARNING_FAILURES`.
Alerts never include role/group contents. Backup, multi-worker restart, and
live-TWC smoke commands are documented in `backend/ops/README.md`.

See the developer-facing cache API guide in [CACHE_API.md](../CACHE_API.md) and the runnable examples in [examples/README.md](../examples/README.md).

Workbench Agent uses only
`C:\Users\Main1\Documents\NI KB base\3DS_KB`. A background integrity gate
serially verifies its controller anchors and all 163,668 manifest rows before
retrieval. Persistent, content-fingerprinted OWUI files contain Workbench
operating instructions, runnable API examples, and the validated corpus control
rails. For every question, Workbench injects query-routed documents from that
corpus into the OWUI system context. A separate permission-scoped file contains
the selected branch's complete tree and native Cameo specifications.

Knowledge pushes run as Workbench background jobs. The Agent tab submits the
job and polls `GET /api/workspace/jobs/{job_id}` with short requests while Open
WebUI processes each file, avoiding reverse-proxy timeouts during branch and
control-rail ingestion. Open WebUI failures are retained in the job message
and returned to the user instead of being reduced to a generic gateway error.

Preset-management authorization is derived from Teamwork Cloud user context and trusted upstream role or group headers when they are available. The backend does not keep a separate hardcoded admin-user list.

Cache refresh is now intentionally view-scoped. Workbench serves cache first, only materializes a full branch cache after a user actually opens that project branch, and only refreshes the actively viewed branch when its revision changes. Automatic webhook-driven background refresh is disabled.

## Verified Contract Boundary

- The adapter uses the verified Teamwork Cloud Swagger surface in `contracts/RealSwagger.json` for resources, workspaces, branches, models, elements, revision diff, and current-user validation.
- Branch rename and branch metadata edit are available on 2024x deployments when the live server accepts the PATCH paths defined in `contracts/RealSwagger.json`.
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
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --no-access-log
```

Linux:

```bash
./.venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --no-access-log
```

Important environment variables are documented in `backend/.env.example` and the repository root `README.md`.
