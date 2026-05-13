# Cameo Plugin Specification

## Objective

Build a Cameo/MDK-driven extractor that can pull the full model for a selected
TWC project branch into TWC Workbench, and later emit deltas so Workbench can
stay cache-first without re-reading the entire branch unnecessarily.

## Principles

1. TWC Workbench owns storage and API access.
2. The plugin owns extraction from the live Cameo/TWC model context.
3. Cached data should be refreshed only for the branch the user is viewing.
4. Permission scope must remain aligned with the TWC user context.
5. Full snapshot first, diff optimization second.

## Runtime Model

The plugin runs inside Cameo/MDK and uses the currently opened project context.

Primary lifecycle hooks:

1. `project open`
   - register project session state
   - record the source project id, branch id, and revision if available
   - optionally prepare a baseline fingerprint

2. `manual export`
   - export the currently open project branch snapshot
   - send it to Workbench ingest API

3. `project save/commit/close`
   - gather current state
   - compute change summary if possible
   - emit branch delta or full snapshot fallback
   - send it to Workbench ingest API

## Plugin Responsibilities

The plugin should:

- resolve current TWC server / project / branch / revision context
- use the TWC resource id as the Workbench `project_id` key so cached data lines up with the existing Workbench project browser
- traverse the full model through Cameo/MDK APIs
- export model data in a Workbench-owned JSON shape
- include enough identity/scope metadata for permission enforcement
- emit either:
  - full branch snapshot
  - branch delta
- retry or queue locally if Workbench ingest is temporarily unavailable

The plugin should not:

- become the long-term query API
- expose direct unauthenticated data access
- bypass Workbench permission checks

## Export Modes

### 1. Full branch snapshot

Used for:

- first ingest for a branch
- recovery from sync drift
- fallback when diffing is not trustworthy

Includes:

- server identity
- project identity
- branch identity
- revision identity
- models
- elements
- containment
- ownership
- relationships
- properties
- stereotypes
- documentation
- diagram references if available
- raw source fragments where useful

### 2. Branch delta

Used for:

- project close
- post-save or post-commit refresh
- branch revisit when baseline exists

Includes:

- changed elements
- added elements
- removed elements
- changed relationships
- updated revision metadata

If delta cannot be trusted, the plugin should fall back to a full snapshot.

## Permission Strategy

Preferred rule:

- extraction happens in the active Cameo/TWC user context

That gives the cleanest match to visible model scope.

Workbench should still store:

- `source_user`
- `extracted_for_user`
- `project_id`
- `branch_id`
- `revision_id`

If a shared elevated account is ever used, Workbench must apply a second-layer
permission filter before serving cached data.

## Delivery Sequence

Phase 1:

- full branch snapshot export
- ingest into Workbench
- cache-first reads from Workbench

Phase 2:

- close-triggered branch delta
- revision-aware incremental update

Phase 3:

- richer diagram/presentation data
- background retry queue
- operator diagnostics
