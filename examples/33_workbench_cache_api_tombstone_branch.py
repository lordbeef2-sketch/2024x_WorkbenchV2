# Created by: Raymond Reeves Engineering Tech 4 2026
from __future__ import annotations

import json

from workbench_cache_api_common import load_config, request_json, verify_value


def main() -> None:
    config = load_config()
    if config.get("confirm_tombstone") is not True:
        raise SystemExit("Set confirm_tombstone to true in the example config before removing a stored branch.")
    payload = {
        "serverId": config["server_id"],
        "projectId": config["project_id"],
        "branchId": config["branch_id"],
        "expectedRevisionId": config.get("expected_revision_id"),
        "sourceUser": config["source_user"],
        "reason": config.get("tombstone_reason") or "Removed through the Workbench API example",
    }
    response = request_json(
        "POST",
        config["workbench_base_url"],
        "/api/cache-ingest/branch-tombstones",
        config["api_key"],
        payload=payload,
        verify=verify_value(config),
    )
    print(json.dumps(response, indent=2))


if __name__ == "__main__":
    main()

# Fully-commented edition notes:
# - File path: examples/33_workbench_cache_api_tombstone_branch.py
# - This branch intentionally carries extra explanatory comments for handoff, review, and training.
# - Keep behavioral changes on main first, then rebase or regenerate this branch so comments never hide logic drift.
# - The normal main branch keeps the production-readable version with only provenance headers.