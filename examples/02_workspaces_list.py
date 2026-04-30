from common import build_client, print_json


def main() -> None:
    client = build_client()
    payload = client.request_json("GET", ["/osmc/workspaces?includeBody=true"])
    print_json(payload)


if __name__ == "__main__":
    main()
