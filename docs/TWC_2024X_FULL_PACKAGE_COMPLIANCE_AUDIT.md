# TWC 2024x full-package compliance audit

This file records what is proven by the packaged 3DS documentation, what is
proven by `contracts/RealSwagger.json`, what the Workbench source implements,
and what still requires a live TWC/Cameo test. Existing Workbench code is never
treated as proof of the TWC contract.

## Evidence precedence

1. Packaged official 3DS 2024x documentation under
   `C:/sand/TWC_Data_Sheets/TWC2024x/output/nomagic_owui_kb`.
2. The captured REST contract in `contracts/RealSwagger.json`.
3. Live target-server responses and an installed Cameo 2024x SDK/runtime.
4. Workbench implementation and tests, used only to show conformance to the
   evidence above.

The rebuilt KB manifest contains 3,444 pages and 27,783 valid JSONL chunks:
181 official 2024x Refresh3 Confluence pages and 3,263 2024x Javadoc pages,
including 2,986 class/interface pages. All 26 Java types imported by the
plugin and all 23 audited methods/constants are present in the generated
class-level Javadocs. Eight links emitted by the official all-classes index
point to internal/nested-class pages that return HTTP 404; the failed URLs are
retained in `manifest.json`, and those eight names remain represented in the
captured all-classes index rather than being reported as successfully fetched
class pages.

## Coverage matrix

| Surface | Packaged or contract evidence | Implemented behavior | Status / remaining proof |
| --- | --- | --- | --- |
| Authentication | Official 2024x Refresh3 Developer Guide documents OIDC discovery, `/authentication/oidc/authorize`, `/authentication/api/oidc/token`, `client_secret_basic`, `scope=openid`, authorization-code/refresh grants, OIDC client registration, and `Authorization: Token <ID token>` for TWC REST. `RealSwagger.json` documents current-user validation. | Workbench discovers OIDC endpoints, performs authorization-code exchange with HTTP Basic client authentication, refreshes the ID token, validates `/osmc/admin/currentUser`, and retains explicit token login. | Source-aligned. The target deployment's redirect URI, TLS chain, discovery response, and proxy behavior require live proof. OAuth 1.0a consumer-key/request-token authentication is not exposed. |
| Project registry | Swagger defines workspaces/resources and branch inventory. | Workbench persists imported plugin project/branch identities and uses REST inventory for access reconciliation rather than downloading model elements. | Implemented. Live pagination and identifier-shape verification remain. |
| User permissions | 3DS documents permissions assigned to roles; users and groups receive roles with global, category, resource, or branch scopes. | Login captures current-user claims; background refresh replaces the user's stored authorization snapshot. | Implemented for returned claims. Live payload proof remains for every target role/permission representation. |
| All roles and groups | Swagger exposes administrator role, user-group, project-role, direct-user, direct-group, and resolved read-only-branch surfaces. Its workspace role endpoints explicitly describe the workspace as a category. | Server inventory loads all roles and all groups, expands nested membership, merges global and scoped role assignments, direct project principals, and resolved branch permissions. Project matching tests both the resource ID and its imported workspace/category ID. | Implemented and unit-tested for global, category/workspace, resource, and nested-group cases. Live target payload verification remains. |
| Predefined roles | 3DS documents Resource Creator, Resource Manager, Security Manager, Server Administrator, User Manager, and their individual permissions. Security Manager includes List All Resources; Server Administrator alone is Configure Server. | Access is computed from expanded permission objects. Exact predefined-role fallbacks apply only when the server omits permission objects. Canonical `read.resource` and `edit.resource` operations and documented labels are recognized. | Source-aligned. Workbench does not infer project read access from the words `Server Administrator`. |
| Branch identity | Swagger branch records use an ID distinct from display name such as `trunk`. | Plugin sends `EsiBranchInfo.getID()` for remote branches and uses `master` only if no ID is exposed. | Implemented. Compile/live capture against the installed Cameo SDK remains. |
| Model acquisition | Swagger exposes resource/branch model endpoints, but REST model data is not claimed as a full Cameo project copy. | Automatic REST model/element fallback refresh is disabled. Its fallback/manual/model-sync routes and example were removed. Full Workbench model content comes from plugin snapshots/deltas. | Corrected boundary. Background permission refresh is limited to current user, roles, groups, scoped project/branch access, and read-only branch evidence; it does not traverse model elements. |
| Full model tree | Cameo class-level Javadocs confirm the loaded-model and owned-element APIs used by the plugin. | Plugin walks every `project.getModels()` root recursively through `getOwnedElement()`. Backend reconstruction honors recorded `ownedElementIds` order before repair-only extras. | Method-level source evidence is present. Installed-SDK compilation and live visual tree comparison remain required. |
| Native specifications | Class-level Javadocs confirm the UML/metamodel, stereotype, tag, and ordered-value helper APIs used by the plugin. | Snapshot records regular metamodel features, native specification features, documentation, stereotypes, ordered tag values, references, defaults, and derived/read-only metadata using guarded reads. | Method-level source evidence is present. Installed-Cameo comparison on representative elements remains required. |
| Diagrams | Class-level Javadocs confirm `getDiagram`, `ensureLoaded`, `getDiagramType`, `getUsedModelElements`, and PNG image export. | Snapshot records diagram metadata, used elements, and PNG previews when available. | Implemented with live-runtime proof outstanding. |
| Project usages | Model/resource payload parsing and plugin model roots provide usage references. | Project summaries expose compact attached-usage information without expanding the entire model. | Implemented; live validation across used-project and module variants remains. |
| Compare/diff | Swagger defines revision diff. | Workbench supports revision/item, branch-to-branch, and project-to-project selection while applying each side's permission scope. | Implemented. Cross-project live smoke tests remain. |
| Edit/commit | Swagger-defined edit paths and plugin ingestion define distinct write boundaries. | UI/API exposes only capability-backed edits; plugin snapshots/deltas update the shared model cache. | Implemented boundary. Live conflict, lock, revision, and permission-loss behavior remains. |
| Developer API and examples | Routes are grounded in Workbench contracts and `RealSwagger.json`. | Scoped per-user API keys and Python examples cover tree/spec/cache operations and documented TWC model calls. Unsupported workspace-latest-model routes were removed. | Source-aligned; examples require live target-server smoke tests. |
| API information visibility | Documentation is text; mutations and API keys remain permission-bearing operations. | Non-admin users may read developer guidance while admin contract exploration and administrative actions remain gated. | Implemented; UI-role smoke test remains. |
| Workbench Agent | 3DS KB artifacts and Workbench examples are local source material. | Agent splits the complete source set into bounded files, checkpoints every processed segment, resumes interrupted uploads, and attaches every reference segment plus a separate permission-scoped selected-branch source to each chat. Cameo opens this same Workbench Agent tab instead of bypassing it with direct OWUI chat. OWUI TLS is verified by default and may be host-allowlisted. | Unit-tested structurally. Live OWUI upload/chat, file-count limits, retrieval quality, and gateway behavior require end-to-end proof. |
| Offline packaging | Repository contains connected prep and offline installer workflows. | Prep tests/builds, creates wheels, verifies `--no-index`, embeds the complete verified 3DS KB, records source/KB provenance and hashes, and creates a ZIP. Installer verifies every manifest entry, replaces the packaged KB, preserves configuration/data, generates a session secret, and installs from the wheelhouse. Pip and nested PEP 517 builds use the native Windows trust store without disabling TLS verification. | The final ZIP was hash-verified, extracted, installed to a clean path strictly from its wheelhouse, and import-tested. The installed KB contained all 3,444 pages and 27,783 chunks. |
| Presentation | Existing deck is the visual reference. | Deck and speech now describe the documented OIDC flow, segmented complete KB reference set, permission overlay, and honest validation boundary. | All 13 slides were rendered, affected slides were visually inspected, and the presentation overflow test passed. Live product screenshots remain deployment evidence, not a source-contract claim. |
| Operations | Repository contains restart/lease, SQLite backup verification, live TWC smoke, and sanitized alert-forwarding checks. | Local multi-worker lease/restart check passed; a generated current-schema SQLite database and its backup matched table counts, integrity, and SHA-256 reporting; alert sanitization is unit-tested. | Live TWC smoke and delivery to an actual alert receiver remain environment-gated. |

## Security invariants

- A permission refresh replaces the user's prior authorization snapshot; it
  does not append stale privileges.
- Project visibility is granted only after matching current user, direct role,
  group/nested-group role, or resolved branch permission evidence to the saved
  project/branch identity.
- Permission loss removes access on the next completed refresh; background work
  must not freeze the UI.
- A cached plugin snapshot is shared model content. User access remains a
  separate permission overlay and must never be inferred from the publisher.
- `List All Resources` grants visibility, not edit authority. `Configure Server`
  by itself does not grant model visibility.

## Release blockers

1. Compile the plugin against the exact installed Cameo/TWC 2024x SDK and run
   snapshot, delta, branch-ID, specification, diagram, and permission-manifest
   smoke tests.
2. Capture live administrator payloads for all roles, all groups, nested groups,
   category/workspace scopes, project scopes, and resolved branch permissions.
3. Run live AuthServer code-flow, redirect, TLS, and token-refresh tests.
4. Run live multi-user visibility/permission-loss, cross-branch/project diff,
   OWUI knowledge push, and delivery to the production alert receiver.
