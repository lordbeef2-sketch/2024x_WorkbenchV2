from __future__ import annotations

import json
from pathlib import Path

from workbench_cache_api_common import load_config, request_json, verify_value


def main() -> None:
    config = load_config()
    snapshot_path = Path(__file__).resolve().parent / config["snapshot_payload_path"]
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    response = request_json(
        "POST",
        config["workbench_base_url"],
        "/api/cache-ingest/branch-snapshots",
        config["api_key"],
        payload=payload,
        verify=verify_value(config),
    )
    print(json.dumps(response, indent=2))


if __name__ == "__main__":
    main()
