from Modules import build_authenticated_client, list_workspace_resources, print_json, require_context_fields


def main() -> None:
    client = build_authenticated_client()
    require_context_fields(client.config, "workspace_id")
    print_json(list_workspace_resources(client))


if __name__ == "__main__":
    main()
