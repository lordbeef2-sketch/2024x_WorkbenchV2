from Modules import build_authenticated_client, get_branch_artifact, print_json, require_context_fields


def main() -> None:
    client = build_authenticated_client()
    require_context_fields(client.config, "workspace_id", "resource_id", "branch_id", "artifact_id")
    print_json(get_branch_artifact(client))


if __name__ == "__main__":
    main()
