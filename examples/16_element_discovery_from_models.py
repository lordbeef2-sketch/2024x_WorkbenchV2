from collections import deque
from typing import Any

from common import (
    as_list,
    build_client,
    container_member_ids,
    display_name,
    payload_entity,
    print_json,
    reference_id,
    require_context_fields,
)


def main() -> None:
    client = build_client()
    require_context_fields(client.config, "resource_id", "branch_id")

    model_candidates = []
    if client.config.context.workspace_id.strip():
        model_candidates.append("/osmc/workspaces/{workspace_id}/resources/{resource_id}/branches/{branch_id}/models")
    model_candidates.extend(
        [
            "/osmc/resources/{resource_id}/branches/{branch_id}/models",
            "/osmc/resources/{resource_id}/models",
        ]
    )
    model_payload = client.request_json("GET", client.render_candidates(model_candidates))
    model_ids = container_member_ids(model_payload)
    if not model_ids:
        raise RuntimeError("No model IDs were discovered for the configured resource and branch.")

    seed_ids: list[str] = []
    for model_id in model_ids:
        detail_candidates = []
        if client.config.context.workspace_id.strip():
            detail_candidates.append("/osmc/workspaces/{workspace_id}/resources/{resource_id}/branches/{branch_id}/models/{model_id}")
        detail_candidates.extend(
            [
                "/osmc/resources/{resource_id}/branches/{branch_id}/models/{model_id}",
                "/osmc/resources/{resource_id}/models/{model_id}",
            ]
        )
        model_detail = client.request_json(
            "GET",
            [candidate.format_map({"workspace_id": client.config.context.workspace_id, "resource_id": client.config.context.resource_id, "branch_id": client.config.context.branch_id, "model_id": model_id}) for candidate in detail_candidates],
        )
        entity = payload_entity(model_detail)
        if not isinstance(entity, dict):
            continue
        for root in as_list(entity.get("models:roots")):
            if not isinstance(root, dict):
                continue
            root_id = reference_id(root.get("models:root") or root.get("@id"))
            if root_id and root_id not in seed_ids:
                seed_ids.append(root_id)

    if not seed_ids:
        raise RuntimeError("No root element IDs were discovered from the model list.")

    queue = deque(seed_ids)
    discovered_ids = list(seed_ids)
    visited_ids: set[str] = set()
    seen_ids = set(seed_ids)
    payloads_by_id: dict[str, Any] = {}

    while queue:
        element_id = queue.popleft()
        if element_id in visited_ids:
            continue

        element_candidates = []
        if client.config.context.workspace_id.strip():
            element_candidates.append("/osmc/workspaces/{workspace_id}/resources/{resource_id}/branches/{branch_id}/elements/{element_id}")
        element_candidates.extend(
            [
                "/osmc/resources/{resource_id}/branches/{branch_id}/elements/{element_id}",
                "/osmc/resources/{resource_id}/elements/{element_id}",
            ]
        )
        element_payload = client.request_json(
            "GET",
            [candidate.format_map({"workspace_id": client.config.context.workspace_id, "resource_id": client.config.context.resource_id, "branch_id": client.config.context.branch_id, "element_id": element_id}) for candidate in element_candidates],
        )
        payloads_by_id[element_id] = element_payload
        visited_ids.add(element_id)

        for child_id in container_member_ids(element_payload):
            if child_id in seen_ids:
                continue
            seen_ids.add(child_id)
            discovered_ids.append(child_id)
            queue.append(child_id)

    batch_candidates = []
    if client.config.context.workspace_id.strip():
        batch_candidates.append("/osmc/workspaces/{workspace_id}/resources/{resource_id}/branches/{branch_id}/elements")
    batch_candidates.append("/osmc/resources/{resource_id}/branches/{branch_id}/elements")
    hydrated = client.request_json(
        "POST",
        client.render_candidates(batch_candidates),
        text_body=",".join(discovered_ids),
        timeout=max(client.config.request_timeout_seconds, 60),
    )

    if isinstance(hydrated, dict):
        payloads_by_id.update({str(key): value for key, value in hydrated.items()})

    entries = [
        {
            "element_id": element_id,
            "name": display_name(payloads_by_id.get(element_id), element_id),
        }
        for element_id in discovered_ids
    ]
    entries.sort(key=lambda item: (item["name"].lower(), item["element_id"].lower()))

    print_json(
        {
            "workspace_id": client.config.context.workspace_id or None,
            "resource_id": client.config.context.resource_id,
            "branch_id": client.config.context.branch_id,
            "model_ids": model_ids,
            "seed_ids": seed_ids,
            "total_ids": len(discovered_ids),
            "entries": entries,
        }
    )


if __name__ == "__main__":
    main()
