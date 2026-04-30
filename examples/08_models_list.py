from common import build_client, print_json, require_context_fields


def main() -> None:
    client = build_client()
    require_context_fields(client.config, "resource_id", "branch_id")
    candidates = []
    if client.config.context.workspace_id.strip():
        candidates.append("/osmc/workspaces/{workspace_id}/resources/{resource_id}/branches/{branch_id}/models")
    candidates.extend(
        [
            "/osmc/resources/{resource_id}/branches/{branch_id}/models",
            "/osmc/resources/{resource_id}/models",
        ]
    )
    payload = client.request_json("GET", client.render_candidates(candidates))
    print_json(payload)


if __name__ == "__main__":
    main()
