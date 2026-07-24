# TWC 2024x full-package compliance audit

This file records what is proven by the packaged 3DS documentation, what is
proven by `contracts/RealSwagger.json`, what the Workbench source implements,
and what still requires a live TWC/Cameo test. Existing Workbench code is never
treated as proof of the TWC contract.

## Evidence precedence

1. The single authoritative 3DS corpus at
   `C:/Users/Main1/Documents/NI KB base/3DS_KB`.
2. The captured REST contract in `contracts/RealSwagger.json`.
3. Live target-server responses and an installed Cameo 2024x SDK/runtime.
4. Workbench implementation and tests, used only to show conformance to the
   evidence above.

The retained corpus contains 163,671 Markdown documents and 163,668
manifest-controlled evidence files. Its controller, manifest, and validation
anchors were verified, every evidence file was read and hash-checked in
manifest order, and the resulting 163,670-record completion certificate
matched the required SHA-256
`f1798d6892b64d92a239d9604197a32e5a7b4cabde119c7fae0c465850c9e1f5`.
The corpus contains exact Cameo Java OpenAPI release trees, No Magic
documentation spaces and attachments, current authoritative sources, SysML
v2/KerML specifications, and Systems Modeling repositories.

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
| Workbench Agent | The retained 3DS_KB controller defines the corpus gate and query rails. | A background sync serially validates the corpus and uploads only Workbench operating guidance plus validated control rails. Every chat receives path-routed evidence from the retained corpus in its system context plus the permission-scoped selected-branch source. Cameo opens this same Workbench Agent tab instead of bypassing it with direct OWUI chat. OWUI TLS is verified by default and may be host-allowlisted. | Corpus integrity and retrieval are locally testable. Live OWUI upload/chat and retrieval-quality testing remain required. |
| Offline packaging | Repository contains connected prep and offline installer workflows. | Prep tests/builds, creates wheels, verifies `--no-index`, validates the external authoritative 3DS_KB, records its control and certificate hashes without copying the corpus, and creates a ZIP. Installer verifies every package entry and the external KB control hashes, preserves configuration/data, generates a session secret, and installs from the wheelhouse. | Regenerated locally after the authoritative-path change. The isolated wheelhouse installed with `--no-index`; the ZIP contained no copied KB entries and the manifest points to the retained external KB. Target-machine installer smoke testing remains deployment evidence. |
| Presentation | Existing deck is the visual reference. | The speech now describes the documented OIDC flow, single retained 3DS_KB, integrity gate, query-routed evidence, permission overlay, and honest validation boundary. | The PPTX still requires the same copy update and render/overflow QA. The required bundled presentation editor was unavailable in this environment, so the deck was not mutated or falsely claimed as updated. |
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
