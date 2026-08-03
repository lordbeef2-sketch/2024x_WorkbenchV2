# Created by: Raymond Reeves Engineering Tech 4 2026
from Modules import build_authenticated_client, print_json, run_contract_operation


def main() -> None:
    client = build_authenticated_client()
    print_json(run_contract_operation(client))


if __name__ == "__main__":
    main()

# Fully-commented edition notes:
# - File path: examples/17_contract_operation.py
# - This branch intentionally carries extra explanatory comments for handoff, review, and training.
# - Keep behavioral changes on main first, then rebase or regenerate this branch so comments never hide logic drift.
# - The normal main branch keeps the production-readable version with only provenance headers.