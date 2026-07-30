from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode

import requests

from workbench_cache_api_common import bearer_headers, build_url, load_config, verify_value


def main() -> None:
    config = load_config()
    branch_id = str(config.get("branch_id") or "trunk").strip() or "trunk"
    output_file = Path(str(config.get("project_dump_output") or "workbench_project_trunk_dump.json"))
    query = urlencode(
        {
            "branchId": branch_id,
            "includeTree": "true",
            "includeElements": "true",
            "includeDetails": "true",
            "includeRawPayload": "true",
            "includePermissions": "true",
        }
    )
    response = requests.get(
        build_url(
            config["workbench_base_url"],
            f"/api/cache/servers/{config['server_id']}/projects/{config['project_id']}/dump?{query}",
        ),
        headers=bearer_headers(config["api_key"]),
        timeout=600,
        verify=verify_value(config),
    )
    response.raise_for_status()
    payload = response.json()
    output_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    selection = payload.get("selection", {})
    resolved = payload.get("resolved", {})
    print(f"Saved {output_file.resolve()}")
    print(
        "Dumped "
        f"{selection.get('visible_model_count', 0)} models and "
        f"{selection.get('visible_element_count', 0)} elements from "
        f"{resolved.get('project_id')} / {resolved.get('branch_name') or resolved.get('branch_id')}."
    )


if __name__ == "__main__":
    main()
