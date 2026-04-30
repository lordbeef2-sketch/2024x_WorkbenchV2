# TWC REST Examples

This folder contains runnable examples for the fixed Teamwork Cloud REST calls
the project makes directly.

Everything here reads from [config.json](/C:/sand/fresh/New%20Project/examples/config.json)
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

## Not included on purpose

- OSLC examples are not in this folder because the app uses OAuth 1.0a for OSLC,
  not the AuthServer SSO/token flow above.
- API Explorer is dynamic and can execute any Swagger operation in
  `RealSwagger.json`; the closest example here is
  [17_contract_operation.py](/C:/sand/fresh/New%20Project/examples/17_contract_operation.py),
  which lets you run one arbitrary REST operation from `config.json`.
