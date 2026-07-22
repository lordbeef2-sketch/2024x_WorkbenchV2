# Workbench Ingest and Cached Data API

## Purpose

Workbench receives model exports from the Cameo plugin, writes them into the
database, and exposes cached data through authenticated APIs.

## Authentication

Two access patterns are needed.

### 1. Ingest authentication

Used by the plugin/worker to push snapshots and deltas into Workbench.

Recommended header:

```http
Authorization: Bearer <workbench-ingest-token>
```

Alternative:

- signed internal API key
- short-lived scoped token

The ingest token should not be the same thing as the end-user UI token.
The preferred setup is to generate and rotate this token inside the Workbench admin Settings screen, where it is stored encrypted in app storage. A file-based `.env` token list is only the legacy fallback path.

### 2. Cached data API authentication

Used by clients, the UI, and integrations to read cached model data.

Recommended:

- Workbench app session
- or Workbench-issued token access

```http
Authorization: Bearer <workbench-api-token>
```

## Ingest Endpoints

### POST `/api/cache-ingest/branch-snapshots`

Create or replace a branch snapshot.

Request body:

- server metadata
- project metadata
- branch metadata
- revision metadata
- source user metadata
- `permissionManifest`, containing the uploader identity plus Cameo
  project/package ACL principals, actions, inheritance, and read/write flags
- full model payload
- every loaded 2024x model root returned by `Project.getModels()`, including
  attached-module roots
- each model root identifies whether it is the primary project model or an
  attached usage and includes its resource URI when available; Workbench uses
  this lightweight metadata for the Project Browser usage summary
- `specSections.schemaVersion = "2.0"` for each element, containing:
  - `metamodel.entries`: every Cameo `EStructuralFeature`, including current or
    default value, set state, declaring/value type, multiplicity, ordering,
    uniqueness, editability, and derived/transient/volatile flags
  - `stereotypes`: applied stereotypes in Cameo order with profile identity and
    ordered inherited properties, explicit/default/calculated values, type,
    multiplicity, derived state, and read-only state
- structured element-valued specification fields preserve ID, name, qualified
  name, and metaclass instead of collapsing references to display text

Response:

- ingest id
- branch id
- revision id
- model count
- element count
- status

### POST `/api/cache-ingest/branch-deltas`

Apply a branch delta to an existing snapshot.

Request body:

- branch identity
- source revision
- required baseline snapshot SHA-256 matching the current Workbench branch state
- required target snapshot SHA-256 for the fully materialized post-delta state
- target revision
- changed element set
- added/removed items
- relationship updates
- the current `permissionManifest`

The stored permission attachment follows the server/project/branch record and
is replaced or refreshed with its upload. Workbench may merge a complete TWC
resource-role enumeration into it during login/periodic refresh. This manifest
is comparison and audit data; authorization is always based on the current
authenticated user's TWC REST probe and stored effective snapshot.

Response:

- ingest id
- updated revision id
- changed counts
- status

## Cached Data Read Endpoints

### GET `/api/cache/servers/{serverId}/projects`

Returns cached projects available to the authenticated caller.

### GET `/api/cache/servers/{serverId}/projects/{projectId}/branches/{branchId}/summary`

Returns branch cache summary.

### GET `/api/cache/servers/{serverId}/projects/{projectId}/branches/{branchId}/snapshot`

Returns the cached branch summary plus cached models and permissions.

### GET `/api/cache/servers/{serverId}/projects/{projectId}/branches/{branchId}/models`

Returns cached models for the branch.

### GET `/api/cache/servers/{serverId}/projects/{projectId}/branches/{branchId}/models/{modelId}`

Returns one cached model record.

The authenticated Workbench UI exposes the compact project-usage projection at
`GET /api/workspace/projects/{projectId}/branches/{branchId}/usages`. It returns
the primary model identity plus attached model names, IDs, usage type, and any
available URI/version metadata without returning full element details.

### GET `/api/cache/servers/{serverId}/projects/{projectId}/branches/{branchId}/elements`

Query parameters:

- `modelId`
- `search`
- `limit`
- `offset`

Returns cached element rows.

### GET `/api/cache/servers/{serverId}/projects/{projectId}/branches/{branchId}/elements/{elementId}`

Returns one cached element with its normalized detail view.

## Refresh Rule

Workbench should:

- serve cache first
- only trigger refresh for the branch the user is actively viewing
- only refresh if the cached revision differs from the live branch revision

Background webhook-driven refresh is intentionally disabled in the current plan.
