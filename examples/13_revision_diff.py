from common import build_client, print_json, require_context_fields


def main() -> None:
    client = build_client()
    require_context_fields(client.config, "resource_id", "source_revision", "target_revision")
    payload = client.request_json(
        "GET",
        client.render_candidates(
            [
                "/osmc/resources/{resource_id}/revisiondiff?source={source_revision}&target={target_revision}",
            ]
        ),
    )
    print_json(payload)


if __name__ == "__main__":
    main()
