# Verified API Contract and Implementation Plan

## Teamwork Cloud Targets

- 2022x Refresh 2
- 2024x Refresh 3

## Status

This document is implementation-ready only for the portions backed by the captured main Teamwork Cloud Swagger exports and official documentation.

It is not a full end-to-end sign-off for simulation, Cameo Collaborator, or the internal publish service because those contracts are not present in the current artifact set.

## Architecture Boundaries

- Teamwork Cloud is the product boundary for both authentication and the main REST API.
- The default integration architecture is upstream Teamwork Cloud-authenticated session reuse.
- Optional token or OIDC usage is secondary and non-default.
- The application must preserve per-user identity when calling Teamwork Cloud.
- Cameo Collaborator for Teamwork Cloud is a separate service and must not be merged into the main TWC REST contract.
- The internal publish service is a separate application contract and must not be invented from the main TWC Swagger.

## Deployment and Configuration Rules

- `TWC_BASE_URL=https://<host>:8111/osmc`
- `COLLAB_BASE_URL` only when a separate Cameo Collaborator contract is captured
- `PUBLISH_SERVICE_URL` only for the internal publish service

Verified product documentation in this repo says the default Teamwork Cloud layout is browser UI at `https://<host>:8443` and REST or Swagger at `https://<host>:8111/osmc/swagger`. Do not use `8443` as the main REST base URL.

## Evidence Used

| Evidence | Type | What it verifies |
| --- | --- | --- |
| `contracts/TWC_SWAGGER_DIFF_PACKAGE/scripts/output/twc_2022xR2.json` | OpenAPI export | Main TWC 2022xR2 REST surface |
| `contracts/TWC_SWAGGER_DIFF_PACKAGE/scripts/output/twc_2024xR3.json` | OpenAPI export | Main TWC 2024xR3 REST surface |
| `contracts/TWC_SWAGGER_DIFF_PACKAGE/output/swagger/normalized/twc_2022xR2_normalized.json` | Normalized OpenAPI | 2022xR2 operation summaries, request media types, response codes |
| `contracts/TWC_SWAGGER_DIFF_PACKAGE/output/swagger/normalized/twc_2024xR3_normalized.json` | Normalized OpenAPI | 2024xR3 operation summaries, request media types, response codes |
| `contracts/TWC_SWAGGER_DIFF_PACKAGE/output/diffs/twc_diff.json` | Diff JSON | Version-only and changed operations |
| `contracts/TWC_SWAGGER_DIFF_PACKAGE/output/reports/twc_verified_contract_summary.md` | Repo summary | 264 shared ops, 2 new 2024xR3 ops, major gaps |
| `https://docs.nomagic.com/spaces/TWCloud2024x/pages/137987736/REST%2BAPIs` | Official doc | Swagger is the official bundled machine-readable and human-readable API source at `:8111/osmc/swagger` |
| `https://docs.nomagic.com/spaces/TWCloud2022x/pages/158597352/Reusing%2BTeamwork%2BCloud%2Bsession` | Official doc | Session reuse and logout guidance |
| `https://docs.nomagic.com/spaces/TWCloud2024x/pages/158597297/Reusing%2BTeamwork%2BCloud%2Bsession` | Official doc | Same session reuse guidance in 2024x |
| `https://docs.nomagic.com/spaces/TWCloud2022xR2/pages/127970883/Token-based%2Bauthentication` | Official doc | Same-product optional token and OIDC flow, secondary only |
| `contracts/TWC_TRUE_SOURCE_PACKAGE/docs/KNOWN_PUBLIC_FACTS_AND_GAPS.md` | Repo fact sheet | Publicly verified facts and explicit missing artifacts |
| `contracts/TWC_TRUE_SOURCE_PACKAGE/docs/LIVE_DATA_COLLECTION_CHECKLIST.md` | Repo checklist | Exact live captures still required |

## Contract Status by Feature Area

| Feature area | Status | Verified now | Still blocked |
| --- | --- | --- | --- |
| Authentication and session model | Partial | `/osmc/login`, `/osmc/logout`, `/osmc/admin/currentUser`, session reuse guidance | Live cookie names, cross-port session behavior, real logout payloads |
| Project and model browsing | Strong | workspaces, projects, branches, revisions, elements, models, stereotypes, tags | Dedicated model search endpoint and real browse failure payloads |
| Write and edit operations | Partial | workspace, project, branch, element, tag CRUD families | 409 conflict contract, capability restriction payloads, branch PATCH request body |
| Simulation API | Blocked | only existence of separate public simulation Swagger pages | live or captured simulation OpenAPI and payloads |
| Collaborator and document features | Blocked | none in current main Swagger artifacts | collaborator contract and payloads |
| Publish and document generation | Blocked | none in current main Swagger artifacts | Cameo Collaborator publish contract and internal publish service contract |
| Error and permission behavior | Partial | some permission endpoints, `404` and `422` on 2024 branch PATCH | `401`, `403`, `409`, validation body shapes, capability restriction payloads |

## A. Shared Contract

### 1. Authentication and Session Model

#### Verified primary model

The main product docs for both 2022x and 2024x explicitly say:

- logging in creates a Teamwork Cloud session,
- the session remains open after a REST call returns,
- the correct REST usage pattern is to log in once, reuse the returned cookie for subsequent calls, and log out when finished.

This supports the required default architecture: reuse already-authenticated TWC user context and preserve per-user authorization when calling TWC.

#### Verified secondary model

The 2022xR2 token-auth doc also describes a same-product token flow under the TWC authentication server and says the REST API can be called with `Authorization: Token <received_id_token>`. That flow is optional and secondary. It must not be treated as the default architecture.

#### Shared auth operations

| Path | Method | Auth or session behavior | Request schema | Response schema | Notes |
| --- | --- | --- | --- | --- | --- |
| `/osmc/login` | `GET` | Starts a TWC REST session | none in captured OpenAPI | `204` only | Official docs show login returning a session cookie that must be reused |
| `/osmc/login` | `POST` | Starts a TWC REST session | query params: `username`, `password` | `204` only | Captured OpenAPI does not describe cookie body details |
| `/osmc/logout` | `GET` | Terminates the active TWC REST session | none | `204` only | Docs say logout is required to close the session cleanly |
| `/osmc/admin/currentUser` | `GET` | Uses the active authenticated user context | query param: `permission` | `307` redirect to `/osmc/admin/users/{username}` | Useful bootstrap call after login or forwarded-session attachment |

#### Verified headers and lifecycle rules

- Verified by docs: session cookie reuse is the primary REST session mechanism.
- Verified by docs: one login, many requests, one logout.
- Verified by docs: sessions staying open affects license consumption.
- Verified by docs: optional token auth uses `Authorization: Token <received_id_token>`.
- Unverified: the exact cookie names, domains, and whether a browser session established on `8443` is directly reusable against `8111` in your environment without proxy mediation.

#### Implementation rule

Build the application around an upstream authenticated TWC user context first. Do not implement SAML in the app. Do not assume anonymous access. Do not use system-wide credentials for user-scoped repository browsing.

### 2. Project and Model Browsing

#### Verified shared repository and model families

| Path | Method | Auth or session behavior | Request schema | Response schema | Notes |
| --- | --- | --- | --- | --- | --- |
| `/osmc/workspaces` | `GET` | active TWC session or delegated user token | query param: `includeBody` | `200` `application/ld+json`, schema `arrayOfWorkspaces` | Workspace discovery |
| `/osmc/workspaces/{workspaceId}/resources` | `GET` | active user context | query params: `includeBody`, `includeRemovedResource`, `modifiedDate`, `permissions` | `200` `application/ld+json`, schema `Workspace` | Workspace-scoped project listing. `permissions` is explicitly supported here |
| `/osmc/resources` | `GET` | active user context | query params: `includeBody`, `includeRemovedResource`, `modifiedDate` | `200` `application/ld+json`, schema `Resource` | Project listing |
| `/osmc/resources/{resourceId}` | `GET` | active user context | none | `200` `application/ld+json`, schema `Resource` | Project details |
| `/osmc/resources/{resourceId}/branches` | `GET` | active user context | none | `200` `application/ld+json` | Branch list |
| `/osmc/resources/{resourceId}/branches/{branchId}` | `GET` | active user context | none | `200` `application/ld+json` | Branch details |
| `/osmc/resources/{resourceId}/branches/{branchId}/revisions` | `GET` | active user context | none | `301` redirect | Revision list is present but modeled as redirect-oriented in the captured spec |
| `/osmc/resources/{resourceId}/branches/{branchId}/revisions/{revision}` | `GET` | active user context | none | `200` `application/ld+json` | Revision details |
| `/osmc/resources/{resourceId}/branches/{branchId}/elements/{elementId}` | `GET` | active user context | none | `200` `application/ld+json` | Direct element lookup |
| `/osmc/resources/{resourceId}/branches/{branchId}/elements` | `POST` | active user context | 2022xR2: `text/plain` `arrayOfUuid`; 2024xR3: `application/json` `arrayOfUuid` | `200` `application/ld+json` keyed by element id | Verified batch element lookup and one of the key version deltas |
| `/osmc/resources/{resourceId}/branches/{branchId}/models` | `GET` | active user context | none | `200` `application/ld+json`, schema `Models` | Model list for a branch |
| `/osmc/resources/{resourceId}/branches/{branchId}/models/{modelId}` | `GET` | active user context | none | `200` `application/ld+json`, schema `OneOfModels` | Model details |
| `/osmc/resources/{resourceId}/branches/{branchId}/elements/{elementId}/stereotypes` | `GET` | active user context | none | `200` `application/ld+json`, schema `Stereotypes` | Stereotype discovery |
| `/osmc/resources/{resourceId}/branches/{branchId}/elements/{elementId}/stereotypes/{stereotypeId}/tags` | `GET` | active user context | none | `200` `application/ld+json`, schema `Tags` | Tag-value inspection |

#### Verified aliases

The captured Swagger also exposes workspace-qualified equivalents for most repository and model operations under:

- `/osmc/workspaces/{workspaceId}/resources/...`

Implementation should choose one canonical internal route family and map aliases consistently.

#### Search status

No dedicated project, model, or element search contract is verified in the current main TWC Swagger exports.

The only verified `search` paths in the current main exports are LDAP administration endpoints:

- `GET /osmc/admin/ldaps/{ldapId}/lookup`
- `GET /osmc/admin/ldaps/{ldapId}/search`

Model search therefore remains UNVERIFIED and must not be guessed.

#### Model tree status

No dedicated tree, decomposition, containment, or membership endpoint was verified from the captured main Swagger exports. Tree-building likely has to be assembled from the model and element resources above, but the exact tree contract remains UNVERIFIED until browse payload samples are captured.

### 3. Write and Edit Operations

#### Verified shared write families

| Path | Method | Auth or session behavior | Request schema | Response schema | Notes |
| --- | --- | --- | --- | --- | --- |
| `/osmc/workspaces` | `POST` | active user context with permission to create workspaces | `application/ld+json`, schema `Workspace` | `201` `application/ld+json`, schema `Workspace` | Workspace creation |
| `/osmc/workspaces/{workspaceId}/resources` | `POST` | active user context with project-create permission | `application/ld+json`, schema `Resource` | `201` `application/ld+json` | Project creation inside a workspace |
| `/osmc/resources/{resourceId}/branches` | `POST` | active user context with branch-create permission | `application/ld+json`, schema `Branch` | `201` `application/ld+json` | Branch creation |
| `/osmc/resources/{resourceId}/branches/{branchId}/elements/{elementId}` | `POST` | active user context with write permission on target branch | `application/ld+json`, schema `Element` | `201` `application/ld+json` | Element creation at a branch-scoped location |
| `/osmc/resources/{resourceId}/branches/{branchId}/elements/{elementId}` | `PATCH` | active user context with write permission on target branch | `application/ld+json`, schema `Element` | `200` `application/ld+json` | Partial element update |
| `/osmc/resources/{resourceId}/branches/{branchId}/elements/{elementId}` | `PUT` | active user context with write permission on target branch | `application/ld+json`, schema `Element` | `200` `application/ld+json` | Full element replacement |
| `/osmc/resources/{resourceId}/branches/{branchId}/elements/{elementId}` | `DELETE` | active user context with delete permission on target branch | query param: `comment` | `204` | Only the delete operation in this sampled set explicitly shows a `comment` query param |
| `/osmc/resources/{resourceId}/tags` | `POST` | active user context | dual purpose: 2022xR2 supports `application/ld+json` `Tag` or `text/plain` `arrayOfUuid`; 2024xR3 supports `application/ld+json` `Tag` or `application/json` `arrayOfUuid` | `200` batch lookup or `201` tag create | This is both a create endpoint and a batch retrieval endpoint |
| `/osmc/resources/{resourceId}/tags/{tagId}` | `PATCH` | active user context | `application/ld+json`, schema `Tag` | `200` `application/ld+json`, schema `Tag` | Tag metadata update |

#### Branch targeting and version targeting

- Verified write operations are branch-scoped.
- Verified revision endpoints are read-oriented and useful for immutable reads.
- No explicit ETag or `If-Match` contract was verified in the captured main Swagger.
- No shared `409` conflict response was declared in the captured main Swagger.

#### Concurrency handling conclusion

Branch context is verified. Revision-scoped reads are verified. Explicit optimistic concurrency headers, version tokens, and conflict payloads are NOT verified.

Do not invent a concurrency token scheme. Capture real `409` or equivalent payloads before finalizing conflict handling.

### 4. Errors and Permissions

#### Verified permission-related operations

| Path | Method | Verified use |
| --- | --- | --- |
| `/osmc/admin/currentUser` | `GET` | Resolve active user identity under the current session |
| `/osmc/admin/permissions` | `GET` | Enumerate known server permissions, query param `resourceScope` |
| `/osmc/resources/{resourceId}/roles` | `GET` | List roles available to a project |
| `/osmc/resources/{resourceId}/roles/{roleId}/users` | `GET` | List users assigned to a project role |
| `/osmc/resources/{resourceId}/roles/{roleId}/usergroups` | `GET` | List user groups assigned to a project role |
| `/osmc/workspaces/{workspaceId}/resources` | `GET` | Accepts `permissions` query param on project listing |

#### Verified error surface from captured main Swagger

| Status | Verified in captured main Swagger? | Evidence |
| --- | --- | --- |
| `401` | No | No sampled main-TWC operation in the normalized 2024xR3 export declared `401` |
| `403` | No | No sampled main-TWC operation in the normalized 2024xR3 export declared `403` |
| `404` | Yes, partial | Only verified on the new 2024xR3 branch PATCH operations |
| `409` | No | Not declared in the captured normalized main export |
| `422` | Yes, partial | Only verified on the new 2024xR3 branch PATCH operations |

#### Restricted capability responses

The captured main Swagger does not define a machine-readable restricted-capability response contract for user-facing repository or model operations.

Implementation must therefore:

- treat TWC as the source of truth for authorization,
- use runtime status codes and successful browse results to shape UI capabilities,
- avoid inventing a synthetic restriction payload format.

## B. Version Differences

### 2022xR2 only

- No 2022xR2-only operations were found in `twc_diff.json`.
- Legacy request-body encoding remains part of 2022xR2 for the changed operation families listed below.

### 2024xR3 only

Verified 2024xR3-only operations:

- `PATCH /osmc/resources/{resourceId}/branches/{branchId}`
- `PATCH /osmc/workspaces/{workspaceId}/resources/{resourceId}/branches/{branchId}`

Verified 2024xR3-only schemas:

- `WebhookScopeBranchedEObject`
- `jsonArrayOfString`

#### Important note on branch PATCH

The operation exists, but the normalized captured contract does not declare a request media type or request schema. Only the following responses are declared:

- `200`
- `404`
- `422`

The request body for branch rename or metadata update remains UNVERIFIED.

### Changed between versions

The diff reports 23 changed shared operations. The dominant difference is request-body modernization from `text/plain` in 2022xR2 to `application/json` in 2024xR3.

#### Group 1. Admin configuration and batch updates

- `PUT /osmc/admin/config/{key}`
- `PUT /osmc/admin/usergroups`
- `PUT /osmc/workspaces`

Implementation rule:

- 2022xR2 expects legacy text payloads for these changed endpoints.
- 2024xR3 expects JSON payloads.

#### Group 2. LDAP resync operations

- `PATCH /osmc/admin/ldaps/{ldapId}/resync/usergroups`
- `PATCH /osmc/admin/ldaps/{ldapId}/resync/users`

Verified delta:

- 2022xR2: `text/plain`, schema `arrayOfString`
- 2024xR3: `application/json`, schema `jsonArrayOfUuid`

#### Group 3. Role assignment operations

- `POST /osmc/admin/roles/{roleId}/usergroups`
- `POST /osmc/admin/roles/{roleId}/users`
- `POST /osmc/resources/{resourceId}/roles/{roleId}/usergroups`
- `POST /osmc/resources/{resourceId}/roles/{roleId}/users`
- `POST /osmc/workspaces/{workspaceId}/roles/{roleId}/usergroups`
- `POST /osmc/workspaces/{workspaceId}/roles/{roleId}/users`
- `POST /osmc/workspaces/{workspaceId}/resources/{resourceId}/roles/{roleId}/usergroups`
- `POST /osmc/workspaces/{workspaceId}/resources/{resourceId}/roles/{roleId}/users`

Verified delta:

- 2022xR2 uses text payloads
- 2024xR3 uses JSON payloads
- some schema names also change from `arrayOfString` to `jsonArrayOfString`

#### Group 4. Batch element retrieval operations

- `POST /osmc/resources/{resourceId}/branches/{branchId}/elements`
- `POST /osmc/resources/{resourceId}/branches/{branchId}/revisions/{revision}/elements`
- `POST /osmc/resources/{resourceId}/elements`
- `POST /osmc/resources/{resourceId}/revisions/{revision}/elements`
- `POST /osmc/workspaces/{workspaceId}/resources/{resourceId}/branches/{branchId}/elements`
- `POST /osmc/workspaces/{workspaceId}/resources/{resourceId}/branches/{branchId}/revisions/{revision}/elements`
- `POST /osmc/workspaces/{workspaceId}/resources/{resourceId}/elements`
- `POST /osmc/workspaces/{workspaceId}/resources/{resourceId}/revisions/{revision}/elements`

Verified delta:

- 2022xR2: `text/plain` UUID lists
- 2024xR3: `application/json` UUID arrays

#### Group 5. Tag batch lookup dual-mode change

- `POST /osmc/resources/{resourceId}/tags`
- `POST /osmc/workspaces/{workspaceId}/resources/{resourceId}/tags`

Verified delta:

- tag create remains `application/ld+json`
- batch lookup encoding moves from `text/plain` in 2022xR2 to `application/json` in 2024xR3

## C. Evidence Notes

### Swagger-backed evidence

- The main captured exports verify 264 shared operations and 2 additional 2024xR3 operations.
- The main captured exports verify repository, model management, MD resources, admin, authentication, and webhook families.
- The main captured exports do not verify simulation, collaborator, comment, attachment, or publish operations.

### Documentation-backed evidence

- The 2024x REST APIs doc says Swagger bundled with Teamwork Cloud at `https://<host>:8111/osmc/swagger` is the official machine-readable and human-readable API source.
- The 2022x and 2024x session-reuse docs both say the TWC session remains open after REST calls and must be reused and logged out.
- The 2022xR2 token-auth doc documents a same-product optional token flow and the `Authorization: Token <received_id_token>` header.

### Sample-level evidence currently available

- Cookie-based session reuse samples exist in official docs.
- No captured live success and failure JSON payloads for the required feature areas exist in the current repo.

## D. Unverified Gaps

### Missing artifacts that block full contract finalization

- no additional main TWC Swagger exports are required for 2022xR2 or 2024xR3 because those real exports are already present in this repo and were used for this report
- 2022xR2 simulation Swagger or OpenAPI export
- 2024xR3 simulation Swagger or OpenAPI export
- live auth capture showing whether the application receives a reusable TWC cookie, a delegated token header, or both
- exact cookie names, domains, paths, and same-site behavior for upstream authenticated session reuse
- proof of whether the browser-facing TWC session on `8443` is directly reusable against `8111` in your deployment or must be re-established through a proxy or explicit REST login
- one successful and one failure browse payload per version for projects, branches, tree or decomposition flows, element lookup, and search
- dedicated model search endpoint or payload evidence if search is required
- create, update, validation-failure, permission-failure, and conflict-failure payloads for write operations
- explicit `409` or equivalent concurrency conflict contract
- explicit capability restriction payloads
- request schema or example for the 2024xR3 branch PATCH operations
- collaborator document, attachment, comment, and version-history contract
- Cameo Collaborator publish trigger, polling, and result contract
- internal publish service request and response contract for PPT and document generation

### Minimum additional inputs to request now

- no additional main TWC Swagger is needed unless you want to replace the current captures with newer server exports
- simulation Swagger JSON for 2022xR2 and 2024xR3
- sample success and failure payloads for auth, browse, and write flows
- real `401`, `403`, `404`, `409`, validation, and capability-restriction payloads
- internal publish service contract

## Implementation Plan

### Phase 1. Establish the product boundary correctly

1. Treat Teamwork Cloud as the single source of truth for identity, permissions, and repository access.
2. Use `TWC_BASE_URL` for all main REST calls.
3. Keep `COLLAB_BASE_URL` and `PUBLISH_SERVICE_URL` separate from the main TWC client.

### Phase 2. Implement the primary auth model

1. Build the main client around upstream authenticated TWC session reuse.
2. Forward only user-scoped credentials to TWC.
3. Preserve user identity on every TWC call.
4. Do not implement SAML in the app.
5. Do not use anonymous access.
6. Do not use a system-wide admin credential for user-scoped browse or edit flows.
7. Support optional same-product token auth only as a secondary mode behind explicit configuration.

### Phase 3. Implement the verified shared browse surface

1. Implement workspace, project, branch, revision, element, model, stereotype, and tag browsing using only the verified paths in this document.
2. Support workspace-qualified aliases where appropriate.
3. Use revision-scoped endpoints for immutable reads and compare-oriented workflows.
4. Do not implement dedicated model search until a real contract is captured.
5. Do not claim a dedicated tree endpoint; assemble tree views only from verified resources and captured browse payloads.

### Phase 4. Implement the verified shared write surface

1. Implement workspace, project, branch, element, and tag writes using only the verified branch-scoped and workspace-scoped operations.
2. Serialize changed request families differently by version.
3. Treat 2024xR3 branch PATCH as a version-gated feature and keep it disabled until its request body is captured.
4. Do not invent ETag or concurrency headers.
5. Add runtime handling for conflict and permission failures only after real payloads are captured.

### Phase 5. Gate unsupported areas explicitly

1. Mark simulation as blocked until simulation Swagger and payloads are captured.
2. Mark Collaborator document features as blocked until separate collaborator contracts are captured.
3. Mark Cameo Collaborator publish actions as blocked until that service contract is captured.
4. Mark the internal publish service as blocked until its request and response contract is provided.

### Phase 6. Required next captures before coding the remaining features

1. Export simulation Swagger for both target versions.
2. Capture one success and one failure for browse operations.
3. Capture one create, one update, one permission failure, one validation failure, and one conflict failure for write operations.
4. Capture real error payloads for `401`, `403`, `404`, `409`, validation, and capability restriction.
5. Capture the exact internal publish service contract.

## Final Conclusion

The main Teamwork Cloud contract is strong enough to implement a verified shared core for:

- upstream user-context session attachment,
- workspace and project browsing,
- branch and revision browsing,
- element and model access,
- branch-scoped element writes,
- tag operations,
- 2024xR3-only branch metadata patch gating,
- version-aware serialization for the 23 changed operations.

It is not sufficient to finalize:

- simulation,
- collaborator and document features,
- publish workflows,
- full error handling,
- conflict handling,
- capability restriction behavior,
- exact upstream browser-session reuse mechanics in your deployment.

Those areas require the additional live artifacts listed above and must remain explicitly UNVERIFIED until captured.