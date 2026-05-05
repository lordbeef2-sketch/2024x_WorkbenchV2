from Modules import auth_summary, build_authenticated_client, print_json


def main() -> None:
    client = build_authenticated_client()
    print_json(auth_summary(client))


if __name__ == "__main__":
    main()