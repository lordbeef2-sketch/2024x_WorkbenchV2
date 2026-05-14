from __future__ import annotations

import json
from urllib.parse import urlencode

from workbench_cache_api_common import load_config, request_json, verify_value


def main() -> None:
    config = load_config()
    stereotype = str(config.get("stereotype", "Block")).strip()
    query = urlencode(
        {
            "stereotype": stereotype,
            "includeDetails": "true",
            "limit": 100,
            "offset": 0,
        }
    )
    payload = request_json(
        "GET",
        config["workbench_base_url"],
        f"/api/cache/servers/{config['server_id']}/projects/{config['project_id']}/branches/{config['branch_id']}/elements/by-stereotype?{query}",
        config["api_key"],
        verify=verify_value(config),
    )
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
