from __future__ import annotations

import json
from urllib.parse import quote

from workbench_cache_api_common import load_config, request_json, verify_value


def main() -> None:
    config = load_config()
    element_id = str(config.get("element_id") or "").strip()
    if not element_id:
        raise SystemExit("Set element_id in workbench_cache_api_config.json.")

    details = request_json(
        "GET",
        config["workbench_base_url"],
        (
            f"/api/cache/servers/{config['server_id']}/projects/{config['project_id']}"
            f"/branches/{config['branch_id']}/elements/{quote(element_id, safe='')}/details"
        ),
        config["api_key"],
        verify=verify_value(config),
    )
    source_payload = details.get("source_payload") or {}
    specification = source_payload.get("spec_sections") or source_payload.get("specSections") or {}
    print(json.dumps(specification, indent=2))

    metamodel_entries = ((specification.get("metamodel") or {}).get("entries") or [])
    stereotype_sections = specification.get("stereotypes") or []
    stereotype_property_count = sum(len(section.get("entries") or []) for section in stereotype_sections)
    print(
        f"Native specification schema {specification.get('schemaVersion', 'legacy')}: "
        f"{len(metamodel_entries)} metamodel properties and "
        f"{stereotype_property_count} stereotype properties."
    )


if __name__ == "__main__":
    main()
