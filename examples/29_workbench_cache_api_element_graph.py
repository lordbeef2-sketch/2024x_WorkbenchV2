# Created by: Raymond Reeves Engineering Tech 4 2026
from __future__ import annotations

import json

from workbench_cache_api_common import load_config, request_json, verify_value


def main() -> None:
    config = load_config()
    element_id = str(config.get("element_id", "")).strip()
    if not element_id:
        raise SystemExit("Set element_id in workbench_cache_api_config.json before running this example.")
    payload = request_json(
        "GET",
        config["workbench_base_url"],
        f"/api/cache/servers/{config['server_id']}/projects/{config['project_id']}/branches/{config['branch_id']}/elements/{element_id}/graph",
        config["api_key"],
        verify=verify_value(config),
    )
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()

# Fully-commented edition notes:
# - File path: examples/29_workbench_cache_api_element_graph.py
# - This branch intentionally carries extra explanatory comments for handoff, review, and training.
# - Keep behavioral changes on main first, then rebase or regenerate this branch so comments never hide logic drift.
# - The normal main branch keeps the production-readable version with only provenance headers.