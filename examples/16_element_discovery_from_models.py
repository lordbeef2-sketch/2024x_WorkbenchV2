# Created by: Raymond Reeves Engineering Tech 4 2026
from Modules import build_authenticated_client, discover_elements_from_models, print_json, require_context_fields


def main() -> None:
    client = build_authenticated_client()
    require_context_fields(client.config, "resource_id", "branch_id")
    print_json(discover_elements_from_models(client))


if __name__ == "__main__":
    main()

# Fully-commented edition notes:
# - File path: examples/16_element_discovery_from_models.py
# - This branch intentionally carries extra explanatory comments for handoff, review, and training.
# - Keep behavioral changes on main first, then rebase or regenerate this branch so comments never hide logic drift.
# - The normal main branch keeps the production-readable version with only provenance headers.