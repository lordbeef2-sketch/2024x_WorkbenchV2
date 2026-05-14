from __future__ import annotations

import json

from workbench_cache_api_common import load_config, request_json, verify_value


def main() -> None:
    config = load_config()
    payload = request_json(
        "PATCH",
        config["workbench_base_url"],
        f"/api/cache/servers/{config['server_id']}/projects/{config['project_id']}/branches/{config['branch_id']}/elements/{config['element_id']}",
        config["api_key"],
        payload={
            "documentation": "Updated from the Workbench cache API example script.",
        },
        verify=verify_value(config),
    )
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
