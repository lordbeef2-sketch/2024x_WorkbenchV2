from __future__ import annotations

import json
import os
import time

import httpx


def required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def main() -> int:
    base_url = required_environment("WORKBENCH_SMOKE_BASE_URL").rstrip("/")
    server_id = required_environment("TWC_SMOKE_SERVER_ID")
    token = required_environment("TWC_SMOKE_TOKEN")
    verify_tls = os.getenv("WORKBENCH_SMOKE_VERIFY_TLS", "true").strip().lower() not in {"0", "false", "no"}
    results: dict[str, object] = {}

    with httpx.Client(base_url=base_url, verify=verify_tls, timeout=60.0, follow_redirects=True) as client:
        health = client.get("/healthz")
        health.raise_for_status()
        results["workbench_health"] = health.json()

        login = client.post("/api/auth/token", json={"server_id": server_id, "token": token})
        login.raise_for_status()
        session = login.json()
        csrf_token = str(session["csrf_token"])
        results["authenticated_user"] = session.get("user", {}).get("preferred_username")
        results["server_id"] = session.get("server", {}).get("id")

        projects = client.get("/api/workspace/projects")
        projects.raise_for_status()
        project_payload = projects.json()
        results["visible_project_count"] = len(project_payload)

        refresh = client.post(
            "/api/workspace/capabilities/refresh",
            headers={"X-CSRF-Token": csrf_token},
            json={},
        )
        refresh.raise_for_status()
        refresh_payload = refresh.json()
        job_id = refresh_payload.get("permission_refresh_job_id")
        results["permission_refresh_job_id"] = job_id
        if job_id:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                job_response = client.get(f"/api/workspace/jobs/{job_id}")
                job_response.raise_for_status()
                job = job_response.json()
                if job.get("status") in {"succeeded", "failed", "cancelled"}:
                    results["permission_refresh_status"] = job.get("status")
                    results["permission_refresh_message"] = job.get("message")
                    break
                time.sleep(2)
            else:
                results["permission_refresh_status"] = "timeout"

        inventory = client.get("/api/workspace/permission-inventory/status")
        results["inventory_status_http"] = inventory.status_code
        if inventory.status_code == 200:
            inventory_payload = inventory.json()
            results["inventory_state"] = inventory_payload.get("state")
            results["role_count"] = inventory_payload.get("role_count")
            results["group_count"] = inventory_payload.get("group_count")

        logout = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})
        logout.raise_for_status()

    passed = results.get("permission_refresh_status") == "succeeded"
    results["passed"] = passed
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
