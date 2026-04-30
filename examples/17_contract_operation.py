from common import build_client, print_json


def main() -> None:
    client = build_client()
    contract = client.config.context.contract_example or {}
    method = str(contract.get("method") or "").strip().upper()
    path = str(contract.get("path") or "").strip()
    query_params = contract.get("query_params") if isinstance(contract.get("query_params"), dict) else {}
    json_body = contract.get("json_body")
    text_body = contract.get("text_body")

    if not method:
        raise RuntimeError("Set context.contract_example.method in examples/config.json")
    if not path:
        raise RuntimeError("Set context.contract_example.path in examples/config.json")

    payload = client.request_json(
        method,
        [path],
        params=query_params,
        json_body=json_body,
        text_body=text_body if isinstance(text_body, str) else None,
    )
    print_json(payload)


if __name__ == "__main__":
    main()
