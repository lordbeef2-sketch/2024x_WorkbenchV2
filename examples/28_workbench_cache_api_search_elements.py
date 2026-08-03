# Created by: Raymond Reeves Engineering Tech 4 2026
from __future__ import annotations

import json
from urllib.parse import urlencode

from workbench_cache_api_common import load_config, request_json, verify_value


def main() -> None:
    config = load_config()
    query = urlencode(
        {
            "q": str(config.get("query", "")).strip(),
            "includeDetails": "true",
            "limit": 100,
            "offset": 0,
        }
    )
    payload = request_json(
        "GET",
        config["workbench_base_url"],
        f"/api/cache/servers/{config['server_id']}/projects/{config['project_id']}/branches/{config['branch_id']}/elements/search?{query}",
        config["api_key"],
        verify=verify_value(config),
    )
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()

# Fully-commented edition notes:
# - File path: examples/28_workbench_cache_api_search_elements.py
# - This branch intentionally carries extra explanatory comments for handoff, review, and training.
# - Keep behavioral changes on main first, then rebase or regenerate this branch so comments never hide logic drift.
# - The normal main branch keeps the production-readable version with only provenance headers.