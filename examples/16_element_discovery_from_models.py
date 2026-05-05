from Modules import build_authenticated_client, discover_elements_from_models, print_json, require_context_fields


def main() -> None:
    client = build_authenticated_client()
    require_context_fields(client.config, "resource_id", "branch_id")
    print_json(discover_elements_from_models(client))


if __name__ == "__main__":
    main()
