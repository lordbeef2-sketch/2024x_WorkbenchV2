from __future__ import annotations

import json

from workbench_cache_api_common import load_config, request_json, verify_value


def main() -> None:
    config = load_config()
    if config.get("confirm_project_tombstone") is not True:
        raise SystemExit("Set confirm_project_tombstone to true before removing every stored branch in a project.")
    payload = {
        "serverId": config["server_id"],
        "projectId": config["project_id"],
        "expectedBranchIds": config.get("expected_branch_ids") or [],
        "sourceUser": config["source_user"],
        "reason": config.get("tombstone_reason") or "Project removed through the Workbench API example",
    }
    response = request_json(
        "POST",
        config["workbench_base_url"],
        "/api/cache-ingest/project-tombstones",
        config["api_key"],
        payload=payload,
        verify=verify_value(config),
    )
    print(json.dumps(response, indent=2))


if __name__ == "__main__":
    main()
