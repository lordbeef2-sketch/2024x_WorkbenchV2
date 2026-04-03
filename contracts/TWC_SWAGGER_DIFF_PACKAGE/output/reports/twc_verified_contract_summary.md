# Verified Contract Summary: TWC 2022xR2 vs 2024xR3

## Evidence used
- Source spec: `contracts/TWC_SWAGGER_DIFF_PACKAGE/scripts/output/twc_2022xR2.json`
- Source spec: `contracts/TWC_SWAGGER_DIFF_PACKAGE/scripts/output/twc_2024xR3.json`
- Normalized diff JSON: `contracts/TWC_SWAGGER_DIFF_PACKAGE/output/diffs/twc_diff.json`
- Raw diff report: `contracts/TWC_SWAGGER_DIFF_PACKAGE/output/reports/twc_diff_report.md`

## Shared contract
The two exported OpenAPI documents share 264 operations.

Verified shared feature groups in both versions:
- Authentication: login and logout operations are present.
- Administration: config, current user, health, LDAP, users, user groups, roles, permissions, locks, TLS, version, and related admin endpoints are present.
- Repository management: workspaces, resources, branches, revisions, tags, and related hierarchy operations are present.
- Model management: artifacts, elements, revisiondiff, branch-scoped and revision-scoped model operations are present.
- MD resources: models, stereotypes, and stereotype tag endpoints are present.
- Webhooks: webhook management endpoints are present.

Verified absent from these two exported main Teamwork Cloud specs:
- No simulation endpoints were found in these exports.
- No collaborator document endpoints were found in these exports.
- No comment endpoints were found in these exports.
- No attachment endpoints beyond model artifacts were found in these exports.
- No publish endpoints were found in these exports.

## Version-specific differences
### 2024xR3-only operations
The diff shows two operations present only in 2024xR3:
- `PATCH /osmc/resources/{resourceId}/branches/{branchId}`
- `PATCH /osmc/workspaces/{workspaceId}/resources/{resourceId}/branches/{branchId}`

These are documented as branch rename or metadata-update operations.

### Changed shared operations
There are 23 changed shared operations. The dominant pattern is request-body modernization in 2024xR3.

#### Pattern 1: `text/plain` batch inputs in 2022xR2 became `application/json` in 2024xR3
Affected endpoint families include:
- LDAP resync endpoints
- role assignment POST endpoints
- batch element retrieval POST endpoints
- workspace and admin batch PUT endpoints
- tag batch POST endpoints

#### Pattern 2: string-list schema names changed for user assignment
Examples:
- 2022xR2 uses `arrayOfString`
- 2024xR3 uses `jsonArrayOfString`

Affected families include role-to-user assignment endpoints.

#### Pattern 3: UUID-list submission moved to JSON bodies
Examples:
- LDAP resync endpoints moved from `text/plain` name lists in 2022xR2 to `application/json` payloads in 2024xR3.
- Batch element retrieval moved from `text/plain` UUID lists to `application/json` UUID arrays.

#### Pattern 4: tag POST remains dual-purpose, but batch retrieval encoding changed
For tag endpoints, create semantics still include `application/ld+json`, but the batch retrieval side moved from `text/plain` in 2022xR2 to `application/json` in 2024xR3.

### 2024xR3-only schemas
The diff reports two schemas only on the 2024xR3 side:
- `WebhookScopeBranchedEObject`
- `jsonArrayOfString`

`WebhookScopeBranchedEObject` documents a webhook scope type named `branched_eobject`, with `resourceId`, `eobjectId`, `branchIds`, and `effective_recursively`.

## Risks and unknowns
The exported OpenAPI documents are enough to verify operation presence and many request-shape differences, but not enough to safely finalize all implementation behavior.

Still unverified from the exported specs alone:
- exact auth or session cookies and redirect behavior in your live environment
- exact 401, 403, 404, 409, and 422 payload bodies
- exact request body examples for the new 2024xR3 branch PATCH operations
- any simulation contract served from a separate simulation Swagger
- any collaborator, document, comment, or publish contract outside the main TWC Swagger
- hotfix-specific runtime behavior not reflected in the exported schema alone

## Implementation guidance
- Treat the 264 shared operations as the stable cross-version contract surface.
- Add explicit version-aware request serialization for endpoints that changed from `text/plain` in 2022xR2 to `application/json` in 2024xR3.
- Do not assume 2024xR3 JSON request bodies are backward compatible with 2022xR2 for the changed endpoint families.
- Gate branch rename or branch metadata edit UI and service methods behind 2024xR3 capability detection, because those PATCH endpoints are not present in the 2022xR2 export.
- Keep tag handling dual-mode: LDP JSON for create semantics, version-aware batch lookup encoding for retrieval semantics.
- Do not model simulation, collaborator, comment, document, or publish features as part of the verified main Teamwork Cloud contract unless those are backed by separate captured specs or live payload evidence.
- Treat the new webhook `branched_eobject` scope as 2024xR3-specific until a 2022xR2 equivalent is proven.

## Recommended next captures
- Export the separate simulation Swagger for both versions if your deployment exposes it.
- Capture live request and response samples for the 23 changed shared operations.
- Capture at least one successful and one failing example for the new 2024xR3 branch PATCH endpoints.
- Capture representative 401, 403, 404, 409, and 422 payloads.
- Capture any collaborator and publish API contracts if those capabilities are part of the product workflow.
