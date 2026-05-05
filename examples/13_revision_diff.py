from Modules import build_authenticated_client, get_revision_diff, print_json, require_context_fields


def main() -> None:
    client = build_authenticated_client()
    require_context_fields(client.config, "resource_id", "source_revision", "target_revision")
    print_json(get_revision_diff(client))


if __name__ == "__main__":
    main()
