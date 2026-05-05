from Modules import build_authenticated_client, print_json, require_context_fields, update_element


def main() -> None:
    client = build_authenticated_client()
    require_context_fields(client.config, "resource_id", "branch_id", "element_id")
    print_json(update_element(client))


if __name__ == "__main__":
    main()
