from __future__ import annotations

import json
from urllib.parse import quote, urlencode

from workbench_cache_api_common import load_config, request_json, verify_value


def main() -> None:
    config = load_config()
    parent_id = str(config.get("parent_id") or config.get("model_id") or "").strip()
    if not parent_id:
        raise SystemExit("Set parent_id or model_id in workbench_cache_api_config.json.")
    query = urlencode({"modelId": str(config.get("model_id") or "").strip()})
    payload = request_json(
        "GET",
        config["workbench_base_url"],
        f"/api/cache/servers/{config['server_id']}/projects/{config['project_id']}/branches/{config['branch_id']}/nodes/{quote(parent_id, safe='')}/children?{query}",
        config["api_key"],
        verify=verify_value(config),
    )
    print(json.dumps(payload, indent=2))
    print(f"Returned {payload.get('total_children', len(payload.get('items', [])))} direct children for {parent_id}.")


if __name__ == "__main__":
    main()
