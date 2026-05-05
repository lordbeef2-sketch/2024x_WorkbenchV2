from Modules import build_authenticated_client, list_branch_artifacts, print_json, require_context_fields


def main() -> None:
    client = build_authenticated_client()
    require_context_fields(client.config, "workspace_id", "resource_id", "branch_id")
    print_json(list_branch_artifacts(client))


if __name__ == "__main__":
    main()
