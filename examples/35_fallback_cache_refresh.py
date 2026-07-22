from __future__ import annotations

import json
import os
import time

import requests


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Set {name} before running this example.")
    return value


def main() -> None:
    base_url = os.environ.get("TWC_WORKBENCH_URL", "http://localhost:8000").rstrip("/")
    cookie_name = os.environ.get("TWC_WORKBENCH_SESSION_COOKIE_NAME", "twc_session")
    client = requests.Session()
    client.cookies.set(cookie_name, required("TWC_WORKBENCH_SESSION_COOKIE"))
    csrf_token = required("TWC_WORKBENCH_CSRF_TOKEN")

    status_response = client.get(f"{base_url}/api/workspace/fallback-cache/status", timeout=30)
    status_response.raise_for_status()
    fallback_status = status_response.json()
    if not fallback_status.get("current_user_can_refresh"):
        raise PermissionError("The active Workbench session is not a current TWC Server Administrator.")
    print(json.dumps(fallback_status, indent=2))

    response = client.post(
        f"{base_url}/api/workspace/fallback-cache/refresh",
        headers={"X-CSRF-Token": csrf_token},
        json={},
        timeout=30,
    )
    response.raise_for_status()
    job_id = response.json()["id"]

    while True:
        status_response = client.get(f"{base_url}/api/workspace/fallback-cache/status", timeout=30)
        status_response.raise_for_status()
        refresh_status = status_response.json()
        job_status = refresh_status.get("last_job_status")
        print(f"{job_status}: {refresh_status.get('last_job_message') or ''}")
        if refresh_status.get("last_job_id") == job_id and job_status not in {"pending", "running"}:
            print(json.dumps(refresh_status, indent=2))
            if job_status != "succeeded":
                raise RuntimeError(refresh_status.get("last_job_message") or "Fallback cache refresh failed.")
            return
        time.sleep(2)


if __name__ == "__main__":
    main()
