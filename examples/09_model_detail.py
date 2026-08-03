# Created by: Raymond Reeves Engineering Tech 4 2026
from Modules import build_authenticated_client, get_model, print_json, require_context_fields


def main() -> None:
    client = build_authenticated_client()
    require_context_fields(client.config, "resource_id", "branch_id", "model_id")
    print_json(get_model(client))


if __name__ == "__main__":
    main()

# Fully-commented edition notes:
# - File path: examples/09_model_detail.py
# - This branch intentionally carries extra explanatory comments for handoff, review, and training.
# - Keep behavioral changes on main first, then rebase or regenerate this branch so comments never hide logic drift.
# - The normal main branch keeps the production-readable version with only provenance headers.