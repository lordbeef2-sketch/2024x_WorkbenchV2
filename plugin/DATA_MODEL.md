# Workbench Data Model for Cameo Plugin Ingest

## Goal

Store enough normalized data to reconstruct a project branch inside Workbench
while preserving permission boundaries and revision history.

## Core Tables

### `cache_branch_snapshots`

One row per branch snapshot version.

Columns:

- `snapshot_id`
- `server_id`
- `project_id`
- `branch_id`
- `revision_id`
- `source_user`
- `ingested_at`
- `snapshot_type` (`full` or `delta`)
- `status`

### `cache_models`

- `snapshot_id`
- `model_id`
- `name`
- `root_ids`
- `raw_payload`

### `cache_elements`

- `snapshot_id`
- `model_id`
- `element_id`
- `name`
- `item_type`
- `path`
- `owner_id`
- `child_count`
- `raw_payload`

### `cache_relationships`

- `snapshot_id`
- `relationship_id`
- `source_element_id`
- `target_element_id`
- `relationship_type`
- `raw_payload`

### `cache_properties`

- `snapshot_id`
- `element_id`
- `property_key`
- `property_value_json`

### `cache_permissions`

If per-user overlays are needed:

- `snapshot_id`
- `user_id`
- `project_id`
- `branch_id`
- `model_id`
- `element_id`
- `can_read`
- `can_edit`
- `restricted`
- `evaluated_at`

## Minimal First Version

If we want to move faster, phase 1 can be:

- `cache_branch_snapshots`
- `cache_models`
- `cache_elements`

with `raw_payload` carrying the richer detail until deeper normalization is
needed.

## Refresh Behavior

On branch view:

1. load latest cached snapshot for branch
2. compare cached revision to live revision
3. if same revision, serve cache only
4. if changed revision, ingest delta or full snapshot for that branch only

## Cleanup Behavior

Recommended future cleanup:

- retain latest snapshot per branch
- retain recent history window
- prune stale branch snapshots by last viewed time
- provide manual cache clear per project/branch

