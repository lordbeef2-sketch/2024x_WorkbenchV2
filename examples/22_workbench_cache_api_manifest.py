from __future__ import annotations

import json

from workbench_cache_api_common import load_config, request_json, verify_value


def main() -> None:
    config = load_config()
    payload = request_json(
        "GET",
        config["workbench_base_url"],
        "/api/cache",
        config["api_key"],
        verify=verify_value(config),
    )
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
