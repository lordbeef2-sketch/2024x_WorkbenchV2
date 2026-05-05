from Modules import build_authenticated_client, print_json, run_contract_operation


def main() -> None:
    client = build_authenticated_client()
    print_json(run_contract_operation(client))


if __name__ == "__main__":
    main()
