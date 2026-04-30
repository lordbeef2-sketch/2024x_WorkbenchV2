from common import build_client, print_json, require_context_fields


def main() -> None:
    client = build_client()
    require_context_fields(client.config, "resource_id", "branch_id")
    element_ids = [item.strip() for item in client.config.context.element_ids if item.strip()]
    if not element_ids and client.config.context.element_id.strip():
        element_ids = [client.config.context.element_id.strip()]
    if not element_ids:
        raise RuntimeError("Set context.element_ids or context.element_id in examples/config.json")

    candidates = []
    if client.config.context.workspace_id.strip():
        candidates.append("/osmc/workspaces/{workspace_id}/resources/{resource_id}/branches/{branch_id}/elements")
    candidates.append("/osmc/resources/{resource_id}/branches/{branch_id}/elements")
    payload = client.request_json(
        "POST",
        client.render_candidates(candidates),
        text_body=",".join(element_ids),
        timeout=max(client.config.request_timeout_seconds, 60),
    )
    print_json(payload)


if __name__ == "__main__":
    main()
