# Created by: Raymond Reeves Engineering Tech 4 2026
from __future__ import annotations

import json
import os
from pathlib import Path

import requests


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Set {name} before running this example.")
    return value


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def main() -> None:
    base_url = os.environ.get("TWC_WORKBENCH_URL", "http://localhost:8000").rstrip("/")
    cookie_name = os.environ.get("TWC_WORKBENCH_SESSION_COOKIE_NAME", "twc_session")
    session_cookie = required("TWC_WORKBENCH_SESSION_COOKIE")
    project_id = required("TWC_PROJECT_ID")
    branch_id = required("TWC_BRANCH_ID")
    element_id = required("TWC_ELEMENT_ID")
    model_id = os.environ.get("TWC_MODEL_ID", "").strip()
    include_details = env_bool("TWC_INCLUDE_DETAILS", True)
    include_raw_payload = env_bool("TWC_INCLUDE_RAW_PAYLOAD", False)
    output_file = Path(os.environ.get("TWC_OWNED_ELEMENTS_OUTPUT", "workbench_owned_elements.json"))

    client = requests.Session()
    client.cookies.set(cookie_name, session_cookie)

    params = {
        "projectId": project_id,
        "branchId": branch_id,
        "elementId": element_id,
        "includeDetails": str(include_details).lower(),
        "includeRawPayload": str(include_raw_payload).lower(),
    }
    if model_id:
        params["modelId"] = model_id

    response = client.get(
        f"{base_url}/api/workspace/model-cache/owned-elements",
        params=params,
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()
    output_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Saved {output_file.resolve()}")
    print(
        f"Found {payload.get('total_owned_elements', 0)} owned element(s) under "
        f"{payload.get('element_id')} in {payload.get('project_id')} / {payload.get('branch_id')}."
    )
    unresolved = payload.get("unresolved_element_ids") or []
    if unresolved:
        print(f"Unresolved owned element id(s): {', '.join(unresolved)}")


if __name__ == "__main__":
    main()
