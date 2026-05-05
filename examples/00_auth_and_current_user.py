from Modules import build_authenticated_client, get_current_user, print_json


def main() -> None:
    client = build_authenticated_client()
    print_json(get_current_user(client))


if __name__ == "__main__":
    main()
