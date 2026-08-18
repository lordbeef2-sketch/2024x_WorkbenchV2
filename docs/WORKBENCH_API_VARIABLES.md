# Created by: Raymond Reeves Engineering Tech 4 2026

# Workbench API Variables

Use this as the quick variable map when writing Workbench API calls, scripts, API Explorer examples, or agent tools.

For creating new Workbench routes, use [WORKBENCH_API_ENDPOINT_AUTHORING.md](WORKBENCH_API_ENDPOINT_AUTHORING.md).

The same catalog is available from Workbench after login:

```text
GET /api/workspace/api-variable-catalog
```

## Base URL and auth

| Variable | Where | Used for | Notes |
| --- | --- | --- | --- |
| `WORKBENCH_BASE_URL` | Script/config | Root Workbench URL | Example: `http://localhost:8000`. |
| `WORKBENCH_PUBLIC_URL` | Settings > Servers | Public browser-facing Workbench URL for SSO callbacks and redirects | Example: `https://workbench.company.com:8050`; set this when Caddy/reverse proxy fronts backend port `8000`. |
| `auth_method` | Settings > Servers | Per-server auth setup selector | Use `authentication_id`, `openid`, or `oauth`; this controls which auth fields the Settings page shows. |
| `TWC_AUTH_APPLICATION_IDS` | Settings > Servers / legacy env | TWC Configs Application ID(s) value used for the Workbench AuthServer link | Settings owns this per server; env is only bootstrap/compatibility fallback. Defaults to `twcworkbench`; `TWC_AUTH_CLIENT_ID` remains a compatibility alias. |
| `SESSION_COOKIE` | Cookie | Browser/session-authenticated `/api/workspace/...` routes | Created by local Workbench login, TWC token login, or TWC SSO callback. |
| `X-CSRF-Token` | Header | Session-authenticated writes | Get `csrf_token` from `/api/auth/session` or the login response. Required for `POST`, `PUT`, `PATCH`, and `DELETE` routes using session auth. |
| `WORKBENCH_API_BEARER_TOKEN` | `Authorization` header | Workbench read routes and scoped cache automation routes | Format: `Authorization: Bearer <api_key>`. A `read` key works on Workbench `GET`/`HEAD`/`OPTIONS` read routes. `write` and `edit` are honored only by documented cache-ingest/cache-edit routes. |

## Main selectors

| Workbench variable | Common aliases | Example | Source | Meaning |
| --- | --- | --- | --- | --- |
| `serverId` | `server_id` | `localhost` | Settings > Servers, `/api/servers`, `/api/cache/servers` | Workbench server profile id. |
| `projectId` | `project_id`, `resourceId` | `Property Based Requirements.mdzip` | `/api/workspace/projects` | Stored Workbench project id. In TWC language this often maps to resource id. |
| `branchId` | `branch_id` | `master`, `trunk` | `/api/workspace/projects/{projectId}/branches` | Stored branch id/name for a project. Use the value returned by the branch endpoint. |
| `workspaceId` | `workspace_id` | optional TWC workspace id | Project/branch responses when live TWC context exists | Optional for most cached/plugin reads. |
| `modelId` | `model_id` | `eee_1045467100313_135436_1` | Project dump, model cache, item `source_payload.model_id` | Cached model identifier. Helps disambiguate duplicate element ids. |
| `itemId` | `elementId`, `element_id` | `_19_0beta_...` | Tree node id, item details id, cached elements, Cameo snapshot | Model element id used by item/detail endpoints. |

## Common query flags

| Flag | Type | Default | Used by | Meaning |
| --- | --- | --- | --- | --- |
| `refresh` | boolean | `false` | project, branch, tree, item routes where supported | Ask Workbench to refresh allowed state. Do not spam it in loops. |
| `depth` | integer | omitted | tree route | Optional tree depth limit. Omit where full accessible tree is wanted. |
| `limit` | integer | endpoint-specific | search/diagnostic routes | Max rows/elements returned. |
| `offset` | integer | `0` | list/search routes | Pagination offset. |
| `includeTree` | boolean | `true` | project dump | Include containment tree. |
| `includeElements` | boolean | `true` | project dump | Include cached element records. |
| `includeDetails` | boolean | `true` | project dump/spec diagnostic | Include derived Workbench `ItemDetails`. |
| `includeRawPayload` | boolean | `true` | project dump/spec diagnostic | Include raw Cameo/plugin snapshot payloads. |
| `includePermissions` | boolean | `true` | project dump | Include attached permission/access records visible to the caller. |
| `download` | boolean | `false` | project dump | Return JSON as an attachment. |

## Common calls

```text
GET /api/auth/session
GET /api/workspace/projects
GET /api/workspace/projects/{projectId}/branches
GET /api/workspace/tree?projectId={projectId}&branchId={branchId}
GET /api/workspace/tree/children?projectId={projectId}&branchId={branchId}&parentId={itemId}
GET /api/workspace/items/{itemId}?projectId={projectId}&branchId={branchId}
GET /api/workspace/model-cache/project-dump?projectId={projectId}&branchId={branchId}
GET /api/workspace/model-cache/owned-elements?serverId={serverId}&projectId={projectId}&branchId={branchId}&elementId={itemId}
GET /api/workspace/model-cache/spec-diagnostic?projectId={projectId}&branchId={branchId}&elementId={itemId}
GET /api/workspace/api-variable-catalog
```

## Owned Element property lookup

Use this when someone asks: “Given this element id, show me everything under its Cameo `Owned Element` property.”

```text
GET /api/workspace/model-cache/owned-elements?serverId={serverId}&projectId={projectId}&branchId={branchId}&elementId={itemId}
```

Optional query parameters:

| Parameter | Default | Meaning |
| --- | --- | --- |
| `serverId` | selected/last server fallback | Required for bearer API-key scripts unless relying on the key owner's stored server selection. |
| `modelId` | omitted | Disambiguates the parent element when multiple cached models contain the same id. |
| `includeDetails` | `true` | Include derived Workbench `ItemDetails` for each owned element. |
| `includeRawPayload` | `false` | Include raw Cameo/plugin snapshot payload for each owned element. |

The endpoint checks the parent element's stored plugin snapshot fields in this order:

1. `payload.owned_element_ids`
2. `payload.ownedElementIds`
3. `payload.references.ownedElement`
4. `payload.spec_sections.metamodel.entries` where the entry is named `Owned Element`
5. derived `ItemDetails.contained_elements`

Response shape:

```json
{
  "schema_version": "workbench-owned-elements.v1",
  "project_id": "Project.mdzip",
  "branch_id": "master",
  "element_id": "_parent_id",
  "property": "Owned Element",
  "owned_element_ids": ["_child_id"],
  "unresolved_element_ids": [],
  "total_owned_elements": 1,
  "items": [
    {
      "record": {},
      "derived_item_details": {}
    }
  ]
}
```

## Permission words

| Term | Meaning |
| --- | --- |
| `viewer` | Can see a stored project/branch in Workbench. |
| `editor` | Can update editable Workbench item fields where edit routes permit it. |
| `project_admin` | Can manage Workbench-local access assignments for assigned project branches. |
| `workbench_admin` | Can manage Workbench system settings. Has catalog visibility for stored models but does not automatically grant TWC project authority. |
| `group_manager` | Can manage assigned Workbench groups only. |

## Naming rules

- Workbench route query parameters use camelCase: `projectId`, `branchId`, `modelId`, `elementId`.
- Backend/Python internals usually use snake_case: `project_id`, `branch_id`, `model_id`, `element_id`.
- Teamwork Cloud RealSwagger often uses `resourceId` where Workbench examples say `projectId`.
- Cameo/plugin payloads may use `element_id`, `local_id`, `@id`, or `id`; Workbench item routes use the resolved `itemId`/`elementId`.
- Do not send passwords to Workbench automation routes. Use session cookies plus CSRF, or scoped Workbench API bearer keys.
- Bearer API keys are accepted by read routes only (`GET`, `HEAD`, `OPTIONS`) unless a route explicitly documents `write` or `edit` scope. Browser/admin mutations still require a live Workbench session and CSRF token.

## Minimal Python pattern

```python
import requests

BASE_URL = "http://localhost:8000"

session = requests.Session()
login = session.post(
    f"{BASE_URL}/api/auth/local",
    json={"server_id": "localhost", "username": "admin", "password": "admin"},
    timeout=30,
)
login.raise_for_status()
csrf_token = login.json()["csrf_token"]

projects = session.get(f"{BASE_URL}/api/workspace/projects", timeout=30)
projects.raise_for_status()

headers = {"X-CSRF-Token": csrf_token}
# Use headers on mutating routes only.
```

## Minimal read-key Python pattern

```python
import requests

BASE_URL = "https://your-workbench-host"
API_KEY = "<workbench-read-api-key>"

session = requests.Session()
session.trust_env = False

response = session.get(
    f"{BASE_URL}/api/workspace/model-cache/owned-elements",
    params={
        "serverId": "twc-2024x",
        "projectId": "Property Based Requirements.mdzip",
        "branchId": "master",
        "elementId": "_element_id",
        "includeDetails": "true",
        "includeRawPayload": "false",
    },
    headers={"Authorization": f"Bearer {API_KEY}"},
    timeout=120,
    verify=False,
)
response.raise_for_status()
print(response.json())
```
