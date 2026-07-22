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
    session_cookie = required("TWC_WORKBENCH_SESSION_COOKIE")
    csrf_token = required("TWC_WORKBENCH_CSRF_TOKEN")
    selected_project_id = os.environ.get("TWC_PROJECT_ID", "").strip()
    selected_branch_id = os.environ.get("TWC_BRANCH_ID", "").strip()
    selected_model_id = os.environ.get("TWC_MODEL_ID", "").strip()

    client = requests.Session()
    client.cookies.set(cookie_name, session_cookie)
    response = client.post(
        f"{base_url}/api/workspace/capabilities/refresh",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "selected_project_id": selected_project_id or None,
            "selected_branch_id": selected_branch_id or None,
            "selected_model_id": selected_model_id or None,
        },
        timeout=60,
    )
    response.raise_for_status()
    job_id = response.json().get("permission_refresh_job_id")
    if not job_id:
        raise RuntimeError("Workbench did not return a permission refresh job id.")

    while True:
        job_response = client.get(f"{base_url}/api/workspace/jobs/{job_id}", timeout=30)
        job_response.raise_for_status()
        job = job_response.json()
        print(f"{job['progress']:>3}% {job['status']}: {job['message']}")
        if job["status"] not in {"pending", "running"}:
            print(json.dumps(job.get("result"), indent=2))
            if job["status"] != "succeeded":
                raise RuntimeError(job.get("message") or "Permission refresh failed.")
            return
        time.sleep(2)


if __name__ == "__main__":
    main()
