<!-- Created by: Raymond Reeves Engineering Tech 4 2026 -->
Use this when the coding agent needs to ask for additional artifacts without being vague:

Request the following missing artifacts as a concise checklist:
- live 2022xR2 Swagger/OpenAPI export
- live 2024xR3 Swagger/OpenAPI export
- one successful browse payload per version
- one successful write/update payload per version
- one conflict/version error payload
- one permission error payload
- one simulation run/status/result payload per version
- collaborator/document payloads if that feature is in scope
- internal publish service request/response contract

Rules:
- ask only for artifacts that are still missing
- say exactly why each missing artifact matters
- do not ask for secrets
- ask for sanitized HAR, curl, Postman, or JSON if easiest

<!--
  Fully-commented edition notes:
  - File path: contracts/TWC_TRUE_SOURCE_PACKAGE/prompts/MISSING_ARTIFACT_REQUEST_PROMPT.md
  - This branch intentionally carries extra explanatory comments for handoff, review, and training.
  - Keep behavioral changes on main first, then rebase or regenerate this branch so comments never hide logic drift.
  - The normal main branch keeps the production-readable version with only provenance headers.
-->