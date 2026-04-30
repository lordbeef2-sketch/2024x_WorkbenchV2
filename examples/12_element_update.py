from common import build_client, print_json, require_context_fields


def main() -> None:
    client = build_client()
    require_context_fields(client.config, "resource_id", "branch_id", "element_id")
    payload = client.config.context.update_payload or {}
    if not payload:
        raise RuntimeError("Set context.update_payload in examples/config.json")

    candidates = client.render_candidates(
        ["/osmc/resources/{resource_id}/branches/{branch_id}/elements/{element_id}"]
    )

    last_error: Exception | None = None
    for method in ("PATCH", "PUT"):
        try:
            result = client.request_json(method, candidates, json_body=payload)
            print_json(result)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc

    if last_error is not None:
        raise last_error
    raise RuntimeError("Element update did not produce a response.")


if __name__ == "__main__":
    main()
