from Modules import build_authenticated_client, list_workspaces, print_json


def main() -> None:
    client = build_authenticated_client()
    print_json(list_workspaces(client))


if __name__ == "__main__":
    main()
