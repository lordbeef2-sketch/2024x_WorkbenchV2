from Modules import build_authenticated_client, get_version, print_json


def main() -> None:
    client = build_authenticated_client()
    print_json(get_version(client))


if __name__ == "__main__":
    main()
