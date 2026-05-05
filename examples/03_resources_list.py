from Modules import build_authenticated_client, list_resources, print_json


def main() -> None:
    client = build_authenticated_client()
    print_json(list_resources(client))


if __name__ == "__main__":
    main()
