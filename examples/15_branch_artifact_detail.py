from common import build_client, print_json, require_context_fields


def main() -> None:
    client = build_client()
    require_context_fields(client.config, "workspace_id", "resource_id", "branch_id", "artifact_id")
    payload = client.request_json(
        "GET",
        client.render_candidates(
            [
                "/osmc/workspaces/{workspace_id}/resources/{resource_id}/branches/{branch_id}/artifacts/{artifact_id}",
            ]
        ),
        params={"download": "false"},
    )
    print_json(payload)


if __name__ == "__main__":
    main()
