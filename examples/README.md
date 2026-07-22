# TWC REST Examples

This folder contains runnable examples for the fixed Teamwork Cloud REST calls
the project makes directly.

The numbered scripts are now thin examples around the reusable Python functions in
`examples/Modules/`. That `Modules` package is the application-facing layer you can
import from other Python code instead of copying request logic into each script.

Everything here reads from [config.json](config.json)
and uses the same AuthServer SSO pattern as the app:

1. open the TWC Authentication Server authorize URL,
2. complete the configured SAML login,
3. receive an authorization code on the local callback,
4. exchange that code at `/authentication/api/token` using
   `authentication.client.secret`,
5. call `/osmc/...` with `Authorization: Token <id_token>`.

## Before you run anything

Fill in at least:

- `base_url`
- `auth.client_id`
- `auth.client_secret`
- `context.workspace_id`
- `context.resource_id`
- `context.branch_id`

Add `model_id`, `element_id`, `artifact_id`, `source_revision`, `target_revision`,
or `element_ids` only for the scripts that need them.

## Run examples

From this folder:

```powershell
python .\00_auth_and_current_user.py
python .\01_version.py
python .\16_element_discovery_from_models.py
python .\18_authserver_token_flow.py
python .\20_all_elements_list.py
python .\21_all_elements_payloads.py
```

## Reusable Modules

For a browser-friendly reference page that lists the commands, what they do, and how to call them, open
[commands_reference.html](commands_reference.html).

Import from `Modules` when you want to call the same commands from another app:

```python
from Modules import build_authenticated_client, get_current_user, list_workspaces

client = build_authenticated_client()
current_user = get_current_user(client)
workspaces = list_workspaces(client)
```

Available command functions in `Modules`:

- `get_current_user`
- `get_version`
- `list_workspaces`
- `list_resources`
- `list_workspace_resources`
- `get_resource`
- `list_branches`
- `get_branch`
- `list_models`
- `get_model`
- `get_element`
- `get_elements_batch`
- `get_all_elements`
- `list_all_elements`
- `patch_element`
- `put_element`
- `update_element`
- `get_revision_diff`
- `list_branch_artifacts`
- `get_branch_artifact`
- `discover_elements_from_models`
- `run_contract_operation`

Auth and client helpers in `Modules`:

- `build_authenticated_client`
- `authorize_request_url`
- `token_endpoint`
- `exchange_code`
- `refresh_token`
- `token_summary`
- `auth_summary`

Optional No Magic 2024x helpers in `Modules`:

- `MagicDrawJVMConfig`
- `MagicDrawOpenAPI`
- `build_magicdraw_openapi`
- `NoMagicOpenApiError`
- `get_magicdraw_api`

Those helpers bridge the local MagicDraw or Cameo Java OpenAPI from
`https://jdocs.nomagic.com/2024x/` into Python by using `jpype1`.
They are separate from the TWC REST examples in this folder.

See [NOMAGIC_2024X_PYTHON.md](NOMAGIC_2024X_PYTHON.md)
and run:

```powershell
python .\19_nomagic_openapi_project_summary.py
```

## Coverage

These examples cover the hardcoded REST calls used by the app and extractor:

- `/authentication/authorize`
- `/authentication/api/token`
- `/osmc/admin/currentUser?permission=true`
- `/osmc/version`
- `/osmc/workspaces?includeBody=true`
- `/osmc/resources?includeBody=true&includeRemovedResource=false`
- `/osmc/workspaces/{workspaceId}/resources?...`
- `/osmc/resources/{resourceId}`
- `/osmc/resources/{resourceId}/branches`
- `/osmc/resources/{resourceId}/branches/{branchId}`
- `/osmc/resources/{resourceId}/branches/{branchId}/models`
- `/osmc/resources/{resourceId}/branches/{branchId}/models/{modelId}`
- `/osmc/resources/{resourceId}/branches/{branchId}/elements/{elementId}`
- `POST /osmc/resources/{resourceId}/branches/{branchId}/elements`
- `PATCH` and `PUT /osmc/resources/{resourceId}/branches/{branchId}/elements/{elementId}`
- `/osmc/resources/{resourceId}/revisiondiff?...`
- `/osmc/workspaces/{workspaceId}/resources/{resourceId}/branches/{branchId}/artifacts`
- `/osmc/workspaces/{workspaceId}/resources/{resourceId}/branches/{branchId}/artifacts/{artifactId}`

The numbered files map to those commands one-to-one, with `18_authserver_token_flow.py`
covering the reusable auth-client setup and token metadata. `20_all_elements_list.py`
and `21_all_elements_payloads.py` cover the no-element-id discovery wrappers.

## Workbench Cache API examples

Workbench now also exposes a cache-first API for plugin-backed model data and
other cached branch content. Those examples use a bearer API key created from
Workbench Settings rather than the TWC AuthServer flow above. Keys can carry
`read`, `write`, and `edit` scopes, and Workbench tracks their labels plus
last-used timestamps for basic usage audit.

Files:

- `22_workbench_cache_api_manifest.py`
- `23_workbench_cache_api_list_elements.py`
- `24_workbench_cache_api_edit_element.py`
- `25_workbench_cache_api_ingest_snapshot.py`
- `26_workbench_cache_api_search_by_stereotype.py`
- `27_workbench_cache_api_tree.py`
- `28_workbench_cache_api_search_elements.py`
- `29_workbench_cache_api_element_graph.py`
- `30_workbench_cache_api_tree_children.py`
- `31_workbench_cache_api_native_specifications.py`
- `32_permission_refresh_job.py` (session-authenticated background refresh and status polling)
- `33_workbench_cache_api_tombstone_branch.py` (revision-guarded stored-branch removal; requires explicit confirmation)
- `34_workbench_cache_api_tombstone_project.py` (atomic all-branch project removal; requires explicit confirmation)

They read from:

- [workbench_cache_api_config.json](workbench_cache_api_config.json)

The helper module is:

- [workbench_cache_api_common.py](workbench_cache_api_common.py)

Quick run examples:

```powershell
python .\22_workbench_cache_api_manifest.py
python .\23_workbench_cache_api_list_elements.py
python .\24_workbench_cache_api_edit_element.py
python .\25_workbench_cache_api_ingest_snapshot.py
python .\27_workbench_cache_api_tree.py
python .\28_workbench_cache_api_search_elements.py
python .\29_workbench_cache_api_element_graph.py
python .\30_workbench_cache_api_tree_children.py
python .\31_workbench_cache_api_native_specifications.py
python .\32_permission_refresh_job.py
# Destructive: configure expected_revision_id and confirm_tombstone=true first.
python .\33_workbench_cache_api_tombstone_branch.py
# More destructive: removes every stored branch in the configured project.
python .\34_workbench_cache_api_tombstone_project.py
```

More background is in:

- [CACHE_API.md](../CACHE_API.md)

`27_workbench_cache_api_tree.py` omits `depth` by default and therefore returns
the complete accessible model tree. Set `tree_depth` in the cache API config
only when a bounded response is intentional. Script 30 demonstrates the direct
children endpoint used by incremental tree clients.

## Not included on purpose

- OSLC examples are not in this folder because the app uses OAuth 1.0a for OSLC,
  not the AuthServer SSO/token flow above.
- No Magic desktop OpenAPI calls are not part of the Teamwork Cloud REST transport.
   They are exposed separately through `Modules.nomagic_openapi` so they do not get
   mixed into the REST client layer.
- API Explorer is dynamic and can execute any Swagger operation in
  `RealSwagger.json`; the closest example here is
  [17_contract_operation.py](17_contract_operation.py),
  which lets you run one arbitrary REST operation from `config.json`.
