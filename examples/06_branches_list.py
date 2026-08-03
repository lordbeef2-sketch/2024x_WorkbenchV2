# Created by: Raymond Reeves Engineering Tech 4 2026
from Modules import build_authenticated_client, list_branches, print_json, require_context_fields


def main() -> None:
    client = build_authenticated_client()
    require_context_fields(client.config, "resource_id")
    print_json(list_branches(client))


if __name__ == "__main__":
    main()

# Fully-commented edition notes:
# - File path: examples/06_branches_list.py
# - This branch intentionally carries extra explanatory comments for handoff, review, and training.
# - Keep behavioral changes on main first, then rebase or regenerate this branch so comments never hide logic drift.
# - The normal main branch keeps the production-readable version with only provenance headers.