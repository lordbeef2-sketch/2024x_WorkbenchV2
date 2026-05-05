from Modules import build_authenticated_client, get_elements_batch, print_json, require_context_fields


def main() -> None:
    client = build_authenticated_client()
    require_context_fields(client.config, "resource_id", "branch_id")
    print_json(get_elements_batch(client))


if __name__ == "__main__":
    main()
