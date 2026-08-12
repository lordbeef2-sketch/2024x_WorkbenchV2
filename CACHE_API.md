<!-- Created by: Raymond Reeves Engineering Tech 4 2026 -->
# Workbench Cache API

This page is the quick developer guide for the Workbench cache API.

## What it is

Workbench now exposes a cache-first API for scripts, notebooks, AI agents, and
other integrations that need model data without talking to Teamwork Cloud
directly on every request.

The important model is:

- **Plugin or Workbench sync populates one shared branch cache**
- **Workbench keeps a separate per-user visibility/editability overlay**
- **API keys act as that Workbench user**

That means Workbench does **not** store the same branch model twenty times just
because twenty people open it. The shared branch snapshot is stored once per:

- `server_id`
- `project_id`
- `branch_id`
- `revision_id`

Per-user access is enforced through cached permission overlays, not by
duplicating the whole model payload per user.

## Where the model data comes from

Workbench can serve cached data from two places:

1. **Plugin-backed cache**  
   The Cameo plugin publishes a full recursive semantic model snapshot to
   Workbench and later publishes deltas.

2. **Workbench TWC REST fallback cache**
   A nightly background job materializes the model data TWC REST exposes until
   a Cameo snapshot is available. A TWC Server Administrator can also start the
   background job manually from Workbench Settings.

For plugin-backed branches, the plugin export is authoritative. REST refreshes
skip those branches and cannot overwrite them, including when a snapshot arrives
while a REST refresh is running.

## API key scopes

Users create API keys from Workbench Settings or the `Developer API` tab.

Each key can carry one or more scopes. The scopes are intentionally narrow:

- `read`
  - authenticate Workbench `GET`, `HEAD`, and `OPTIONS` read routes with
    `Authorization: Bearer <api-key>`
  - read cached servers, projects, branches, models, elements, the cache
    manifest, workspace comparison data, and workspace model-cache read helpers
    that accept the same query parameters as the browser
- `write`
  - publish branch snapshots, branch deltas, and tombstones into Workbench
    through the cache-ingest routes only
- `edit`
  - edit cached element content on **plugin-backed** branches when the user's
    cached TWC visibility overlay marks the model editable
  - does not create a general browser/admin write session

Every key has:

- a label
- a token hint
- created time
- last-used time

That gives Workbench a lightweight usage audit trail without storing the full
secret after creation.

## Authentication

Use:

```text
Authorization: Bearer <api-key>
```

The bearer key maps back to the Workbench user who created it. Reads stay scoped
to that user's cached visibility and, for Workbench admin users, the same
Workbench-local admin model visibility used by the browser.

For workspace read routes that do not include `{server_id}` in the path, pass
the server explicitly with `serverId=<id>` or `server_id=<id>`, or with
`x-workbench-server-id` / `x-twc-server-id`. If omitted, Workbench falls back to
the API-key owner's selected/last server and then the first configured server.

Bearer API keys are not accepted as a blanket write/admin session. Browser and
admin mutations still require a live Workbench browser session and CSRF token
unless the specific route is a documented cache-ingest or cache-edit API route
that checks `write` or `edit` scope.

## Core endpoints

### Manifest and discovery

- `GET /api/cache`
- `GET /api/cache/servers`
- `GET /api/cache/servers/{server_id}/projects`

### Branch cache reads

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

### Workspace read helpers

These are browser-backed Workbench read helpers that also accept
`Authorization: Bearer <api-key>` when the key has `read` scope:

- `GET /api/workspace/model-cache/owned-elements?serverId={server_id}&projectId={project_id}&branchId={branch_id}&elementId={element_id}`
- `GET /api/workspace/compare/branches?serverId={server_id}&leftProjectId={project_id}&leftBranchId={branch_id}&rightProjectId={project_id}&rightBranchId={branch_id}`

Use the query parameters from the API Explorer/examples exactly. These routes
use the API-key owner for permission filtering instead of the browser user.

### Plugin/cache write endpoints

- `POST /api/cache-ingest/branch-snapshots`
- `POST /api/cache-ingest/branch-deltas`
- `POST /api/cache-ingest/branch-tombstones`
- `POST /api/cache-ingest/project-tombstones`

Both payloads accept `permissionManifest`. The attachment is stored with the
branch revision and can contain Cameo package ACL entries plus TWC resource-role
entries. It is never treated as a grant: login and the 30-minute active-session
refresh replace each user's effective access from the current TWC REST result.
ACL-changing deltas mark active permission snapshots due immediately. Use the
tombstone route when a branch is deleted or intentionally removed from
Workbench. Include `serverId`, `projectId`, `branchId`, `sourceUser`, `reason`,
and preferably `expectedRevisionId`; a revision mismatch returns `409` instead
of deleting a newer upload. Tombstoning removes cached content and every stored
grant for that branch atomically while retaining an administrator-readable
audit record.
Project tombstones accept `expectedBranchIds` as an optional concurrency guard
and remove all stored branches for that project in one database transaction.

### Cache edit endpoint

- `PATCH /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/{element_id}`

## Hybrid refresh policy

The REST fallback runs only in the configured nightly window. The manual
Workbench trigger is the explicit exception and requires a current TWC Server
Administrator session. Both paths are background jobs and preserve the last
complete fallback if an upstream branch traversal fails.

## Example flows

### Read cached element data

```bash
curl -H "Authorization: Bearer <key>" \
  https://your-workbench-host/api/cache/servers/<server_id>/projects/<project_id>/branches/<branch_id>/elements
```

### Search cached elements by stereotype

```bash
curl -H "Authorization: Bearer <key>" \
  "https://your-workbench-host/api/cache/servers/<server_id>/projects/<project_id>/branches/<branch_id>/elements/by-stereotype?stereotype=Block&includeDetails=true"
```

Use either a stereotype id or a stereotype name fragment in `stereotype`. Set
`includeDetails=true` when you want full cached item details back instead of
just the lightweight cached element records.

### Reconstruct the containment tree

```bash
curl -H "Authorization: Bearer <key>" \
  "https://your-workbench-host/api/cache/servers/<server_id>/projects/<project_id>/branches/<branch_id>/tree?includeOrphans=true"
```

Useful query params:

- `modelId`
- `rootId`
- `depth`
- `includeOrphans`

This returns a normalized tree built from the published snapshot's model roots,
ownership, and contained-element links.

Omit `depth` for the complete accessible branch tree. Use `depth=0` for model
headers only, or a positive depth when an integration intentionally needs a
bounded response. Workbench's Model Browser uses the complete response so tree
filtering and selection cover every published node.

### Search the reconstructed branch model

```bash
curl -H "Authorization: Bearer <key>" \
  "https://your-workbench-host/api/cache/servers/<server_id>/projects/<project_id>/branches/<branch_id>/elements/search?q=system&itemType=package&includeDetails=true"
```

Supported filters:

- `q`
- `itemType`
- `metaclass`
- `stereotype`
- `ownerId`
- `includeDetails`

### Read normalized details for one element

```bash
curl -H "Authorization: Bearer <key>" \
  "https://your-workbench-host/api/cache/servers/<server_id>/projects/<project_id>/branches/<branch_id>/elements/<element_id>/details"
```

This returns the Workbench-presentable item structure instead of the raw cached
element record. Plugin snapshots using specification schema `2.0` expose the
native payload under `source_payload.spec_sections`:

- `metamodel.entries` contains every Cameo metamodel feature, including unset
  defaults and derived/read-only metadata.
- `stereotypes[]` contains each applied stereotype and its ordered inherited,
  explicit, default, and calculated property values.

Workbench renders these as **All Cameo Properties** and **Stereotypes / Tags**
beside the compatibility sections used by older snapshots.

### Read the local graph around one element

```bash
curl -H "Authorization: Bearer <key>" \
  "https://your-workbench-host/api/cache/servers/<server_id>/projects/<project_id>/branches/<branch_id>/elements/<element_id>/graph"
```

The graph response includes:

- owner chain
- contained elements
- type/classifier references
- related elements
- incoming references
- stereotype references

### Publish a snapshot

```bash
curl -X POST \
  -H "Authorization: Bearer <key>" \
  -H "Content-Type: application/json" \
  https://your-workbench-host/api/cache-ingest/branch-snapshots \
  -d @branch-snapshot.json
```

Publishing snapshots with a bearer token requires the plugin ingest token or a
Workbench API key that carries `write` scope. General Workbench Settings/admin
POST routes are not opened by API keys.

### Edit cached plugin-backed element content

```bash
curl -X PATCH \
  -H "Authorization: Bearer <key>" \
  -H "Content-Type: application/json" \
  https://your-workbench-host/api/cache/servers/<server_id>/projects/<project_id>/branches/<branch_id>/elements/<element_id> \
  -d "{\"documentation\":\"Updated from automation\"}"
```

Editing cached plugin-backed content requires `edit` scope and the user's
effective edit permission overlay for that model. It is not a substitute for a
browser admin session.

## Ready-to-run examples

See:

- [examples/22_workbench_cache_api_manifest.py](examples/22_workbench_cache_api_manifest.py)
- [examples/23_workbench_cache_api_list_elements.py](examples/23_workbench_cache_api_list_elements.py)
- [examples/24_workbench_cache_api_edit_element.py](examples/24_workbench_cache_api_edit_element.py)
- [examples/25_workbench_cache_api_ingest_snapshot.py](examples/25_workbench_cache_api_ingest_snapshot.py)
- [examples/26_workbench_cache_api_search_by_stereotype.py](examples/26_workbench_cache_api_search_by_stereotype.py)
- [examples/27_workbench_cache_api_tree.py](examples/27_workbench_cache_api_tree.py)
- [examples/28_workbench_cache_api_search_elements.py](examples/28_workbench_cache_api_search_elements.py)
- [examples/29_workbench_cache_api_element_graph.py](examples/29_workbench_cache_api_element_graph.py)
- [examples/30_workbench_cache_api_tree_children.py](examples/30_workbench_cache_api_tree_children.py)
- [examples/31_workbench_cache_api_native_specifications.py](examples/31_workbench_cache_api_native_specifications.py)
- [examples/workbench_cache_api_config.json](examples/workbench_cache_api_config.json)
