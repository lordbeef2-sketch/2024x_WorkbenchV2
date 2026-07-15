from __future__ import annotations

import json
from urllib.parse import urlencode

from workbench_cache_api_common import load_config, request_json, verify_value


def main() -> None:
    config = load_config()
    query_params = {"includeOrphans": "true"}
    root_id = str(config.get("root_id", "")).strip()
    if root_id:
        query_params["rootId"] = root_id
    # Omit depth for the complete accessible containment tree. Set a nonnegative
    # tree_depth in config only when a caller intentionally wants a bounded view.
    tree_depth = config.get("tree_depth")
    if tree_depth is not None and str(tree_depth).strip():
        query_params["depth"] = str(tree_depth)
    query = urlencode(query_params)
    payload = request_json(
        "GET",
        config["workbench_base_url"],
        f"/api/cache/servers/{config['server_id']}/projects/{config['project_id']}/branches/{config['branch_id']}/tree?{query}",
        config["api_key"],
        verify=verify_value(config),
    )
    print(json.dumps(payload, indent=2))
    print(f"Returned {payload.get('total_nodes', 0)} accessible model-tree nodes.")


if __name__ == "__main__":
    main()
