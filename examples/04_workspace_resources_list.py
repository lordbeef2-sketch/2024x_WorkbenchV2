from common import build_client, print_json, require_context_fields


def main() -> None:
    client = build_client()
    require_context_fields(client.config, "workspace_id")
    payload = client.request_json(
        "GET",
        client.render_candidates(
            [
                "/osmc/workspaces/{workspace_id}/resources?includeBody=true&includeRemovedResource=false",
                "/osmc/workspaces/{workspace_id}/resources?includeBody=true",
                "/osmc/workspaces/{workspace_id}/resources",
            ]
        ),
    )
    print_json(payload)


if __name__ == "__main__":
    main()
