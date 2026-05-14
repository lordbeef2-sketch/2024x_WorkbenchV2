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

2. **Workbench direct branch cache**  
   Legacy live `/osmc` traversal can still build a branch cache for branches
   that are not configured as plugin-only.

For plugin-backed branches, the plugin export is the primary model source.

## API key scopes

Users create API keys from Workbench Settings or the `Developer API` tab.

Each key can carry one or more scopes:

- `read`
  - read cached servers, projects, branches, models, elements, and the cache
    manifest
- `write`
  - publish branch snapshots and branch deltas into Workbench
- `edit`
  - edit cached element content on **plugin-backed** branches when the user's
    cached TWC visibility overlay marks the model editable

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

The bearer key maps back to the Workbench user who created it. Cache reads stay
scoped to that user's cached visibility.

## Core endpoints

### Manifest and discovery

- `GET /api/cache`
- `GET /api/cache/servers`
- `GET /api/cache/servers/{server_id}/projects`

### Branch cache reads

- `GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/summary`
- `GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/snapshot`
- `GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/models`
- `GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/models/{model_id}`
- `GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements`
- `GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/by-stereotype`
- `GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/{element_id}`

### Plugin/cache write endpoints

- `POST /api/cache-ingest/branch-snapshots`
- `POST /api/cache-ingest/branch-deltas`

### Cache edit endpoint

- `PATCH /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/{element_id}`

## Plugin-only targets

When you want specific branches to refuse live `/osmc` fallback and require a
plugin snapshot first, configure:

```env
TWC_PLUGIN_ONLY_CACHE_TARGETS={"twc-2022x":{"project_ids":["project-a"],"branch_ids":{"project-b":["master","feature-1"]}}}
```

For those targets:

- tree loading
- element discovery
- item details

will refuse live fallback until a plugin snapshot is present.

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

### Publish a snapshot

```bash
curl -X POST \
  -H "Authorization: Bearer <key>" \
  -H "Content-Type: application/json" \
  https://your-workbench-host/api/cache-ingest/branch-snapshots \
  -d @branch-snapshot.json
```

### Edit cached plugin-backed element content

```bash
curl -X PATCH \
  -H "Authorization: Bearer <key>" \
  -H "Content-Type: application/json" \
  https://your-workbench-host/api/cache/servers/<server_id>/projects/<project_id>/branches/<branch_id>/elements/<element_id> \
  -d "{\"documentation\":\"Updated from automation\"}"
```

## Ready-to-run examples

See:

- [examples/22_workbench_cache_api_manifest.py](/C:/sand/fresh/New%20Project/examples/22_workbench_cache_api_manifest.py)
- [examples/23_workbench_cache_api_list_elements.py](/C:/sand/fresh/New%20Project/examples/23_workbench_cache_api_list_elements.py)
- [examples/24_workbench_cache_api_edit_element.py](/C:/sand/fresh/New%20Project/examples/24_workbench_cache_api_edit_element.py)
- [examples/25_workbench_cache_api_ingest_snapshot.py](/C:/sand/fresh/New%20Project/examples/25_workbench_cache_api_ingest_snapshot.py)
- [examples/26_workbench_cache_api_search_by_stereotype.py](/C:/sand/fresh/New%20Project/examples/26_workbench_cache_api_search_by_stereotype.py)
- [examples/workbench_cache_api_config.json](/C:/sand/fresh/New%20Project/examples/workbench_cache_api_config.json)
