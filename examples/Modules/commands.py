from __future__ import annotations

from collections import deque
from typing import Any

from common import (
    ExampleError,
    TwcExampleClient,
    as_list,
    container_member_ids,
    display_name,
    element_containment_ids,
    payload_entity,
    reference_id,
)
from .nomagic_openapi import MagicDrawJVMConfig, MagicDrawOpenAPI, get_magicdraw_api


def _context_value(client: TwcExampleClient, field_name: str) -> Any:
    return getattr(client.config.context, field_name)


def _resolve_optional_str(client: TwcExampleClient, explicit_value: str | None, field_name: str) -> str:
    candidate = explicit_value if explicit_value is not None else _context_value(client, field_name)
    if isinstance(candidate, str):
        return candidate.strip()
    return ""


def _resolve_required_str(client: TwcExampleClient, explicit_value: str | None, field_name: str) -> str:
    resolved = _resolve_optional_str(client, explicit_value, field_name)
    if not resolved:
        raise ExampleError(f"Provide {field_name} or set context.{field_name} in examples/config.json")
    return resolved


def _render_candidates(client: TwcExampleClient, templates: list[str], **overrides: Any) -> list[str]:
    values = {
        "workspace_id": _resolve_optional_str(client, None, "workspace_id"),
        "resource_id": _resolve_optional_str(client, None, "resource_id"),
        "branch_id": _resolve_optional_str(client, None, "branch_id"),
        "model_id": _resolve_optional_str(client, None, "model_id"),
        "element_id": _resolve_optional_str(client, None, "element_id"),
        "artifact_id": _resolve_optional_str(client, None, "artifact_id"),
        "source_revision": _resolve_optional_str(client, None, "source_revision"),
        "target_revision": _resolve_optional_str(client, None, "target_revision"),
    }
    for key, value in overrides.items():
        if value is not None:
            values[key] = value
    return [template.format(**values) for template in templates]


def _resolve_update_payload(client: TwcExampleClient, explicit_payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = explicit_payload if explicit_payload is not None else client.config.context.update_payload
    if not isinstance(payload, dict) or not payload:
        raise ExampleError("Provide payload or set context.update_payload in examples/config.json")
    return payload


def _resolve_element_ids(
    client: TwcExampleClient,
    explicit_ids: list[str] | None = None,
    explicit_element_id: str | None = None,
) -> list[str]:
    if explicit_ids is not None:
        values = explicit_ids
    else:
        values = client.config.context.element_ids

    element_ids = [str(item).strip() for item in values if str(item).strip()]
    if element_ids:
        return list(dict.fromkeys(element_ids))

    fallback_element_id = _resolve_optional_str(client, explicit_element_id, "element_id")
    if fallback_element_id:
        return [fallback_element_id]

    raise ExampleError("Provide element_ids or element_id, or set context.element_ids/context.element_id in examples/config.json")


def get_current_user(client: TwcExampleClient, include_permission: bool = True) -> Any:
    suffix = "?permission=true" if include_permission else ""
    return client.request_json("GET", [f"/osmc/admin/currentUser{suffix}"])


def get_version(client: TwcExampleClient) -> Any:
    return client.request_json("GET", ["/osmc/version"])


def list_workspaces(client: TwcExampleClient) -> Any:
    return client.request_json("GET", ["/osmc/workspaces?includeBody=true"])


def list_resources(client: TwcExampleClient) -> Any:
    return client.request_json(
        "GET",
        [
            "/osmc/resources?includeBody=true&includeRemovedResource=false",
            "/osmc/resources?includeBody=true",
            "/osmc/resources",
        ],
    )


def list_workspace_resources(client: TwcExampleClient, workspace_id: str | None = None) -> Any:
    resolved_workspace_id = _resolve_required_str(client, workspace_id, "workspace_id")
    return client.request_json(
        "GET",
        _render_candidates(
            client,
            [
                "/osmc/workspaces/{workspace_id}/resources?includeBody=true&includeRemovedResource=false",
                "/osmc/workspaces/{workspace_id}/resources?includeBody=true",
                "/osmc/workspaces/{workspace_id}/resources",
            ],
            workspace_id=resolved_workspace_id,
        ),
    )


def get_resource(
    client: TwcExampleClient,
    resource_id: str | None = None,
    workspace_id: str | None = None,
) -> Any:
    resolved_resource_id = _resolve_required_str(client, resource_id, "resource_id")
    resolved_workspace_id = _resolve_optional_str(client, workspace_id, "workspace_id")
    candidates: list[str] = []
    if resolved_workspace_id:
        candidates.append("/osmc/workspaces/{workspace_id}/resources/{resource_id}")
    candidates.append("/osmc/resources/{resource_id}")
    return client.request_json(
        "GET",
        _render_candidates(
            client,
            candidates,
            workspace_id=resolved_workspace_id or None,
            resource_id=resolved_resource_id,
        ),
    )


def list_branches(
    client: TwcExampleClient,
    resource_id: str | None = None,
    workspace_id: str | None = None,
) -> Any:
    resolved_resource_id = _resolve_required_str(client, resource_id, "resource_id")
    resolved_workspace_id = _resolve_optional_str(client, workspace_id, "workspace_id")
    candidates: list[str] = []
    if resolved_workspace_id:
        candidates.append("/osmc/workspaces/{workspace_id}/resources/{resource_id}/branches")
    candidates.append("/osmc/resources/{resource_id}/branches")
    return client.request_json(
        "GET",
        _render_candidates(
            client,
            candidates,
            workspace_id=resolved_workspace_id or None,
            resource_id=resolved_resource_id,
        ),
    )


def get_branch(
    client: TwcExampleClient,
    resource_id: str | None = None,
    branch_id: str | None = None,
    workspace_id: str | None = None,
) -> Any:
    resolved_resource_id = _resolve_required_str(client, resource_id, "resource_id")
    resolved_branch_id = _resolve_required_str(client, branch_id, "branch_id")
    resolved_workspace_id = _resolve_optional_str(client, workspace_id, "workspace_id")
    candidates: list[str] = []
    if resolved_workspace_id:
        candidates.append("/osmc/workspaces/{workspace_id}/resources/{resource_id}/branches/{branch_id}")
    candidates.append("/osmc/resources/{resource_id}/branches/{branch_id}")
    return client.request_json(
        "GET",
        _render_candidates(
            client,
            candidates,
            workspace_id=resolved_workspace_id or None,
            resource_id=resolved_resource_id,
            branch_id=resolved_branch_id,
        ),
    )


def list_models(
    client: TwcExampleClient,
    resource_id: str | None = None,
    branch_id: str | None = None,
    workspace_id: str | None = None,
) -> Any:
    resolved_resource_id = _resolve_required_str(client, resource_id, "resource_id")
    resolved_branch_id = _resolve_required_str(client, branch_id, "branch_id")
    resolved_workspace_id = _resolve_optional_str(client, workspace_id, "workspace_id")
    candidates: list[str] = []
    if resolved_workspace_id:
        candidates.append("/osmc/workspaces/{workspace_id}/resources/{resource_id}/branches/{branch_id}/models")
    candidates.extend(
        [
            "/osmc/resources/{resource_id}/branches/{branch_id}/models",
            "/osmc/resources/{resource_id}/models",
        ]
    )
    return client.request_json(
        "GET",
        _render_candidates(
            client,
            candidates,
            workspace_id=resolved_workspace_id or None,
            resource_id=resolved_resource_id,
            branch_id=resolved_branch_id,
        ),
    )


def get_model(
    client: TwcExampleClient,
    model_id: str | None = None,
    resource_id: str | None = None,
    branch_id: str | None = None,
    workspace_id: str | None = None,
) -> Any:
    resolved_model_id = _resolve_required_str(client, model_id, "model_id")
    resolved_resource_id = _resolve_required_str(client, resource_id, "resource_id")
    resolved_branch_id = _resolve_required_str(client, branch_id, "branch_id")
    resolved_workspace_id = _resolve_optional_str(client, workspace_id, "workspace_id")
    candidates: list[str] = []
    if resolved_workspace_id:
        candidates.append("/osmc/workspaces/{workspace_id}/resources/{resource_id}/branches/{branch_id}/models/{model_id}")
    candidates.extend(
        [
            "/osmc/resources/{resource_id}/branches/{branch_id}/models/{model_id}",
            "/osmc/resources/{resource_id}/models/{model_id}",
        ]
    )
    return client.request_json(
        "GET",
        _render_candidates(
            client,
            candidates,
            workspace_id=resolved_workspace_id or None,
            resource_id=resolved_resource_id,
            branch_id=resolved_branch_id,
            model_id=resolved_model_id,
        ),
    )


def get_element(
    client: TwcExampleClient,
    element_id: str | None = None,
    resource_id: str | None = None,
    branch_id: str | None = None,
    workspace_id: str | None = None,
) -> Any:
    resolved_element_id = _resolve_required_str(client, element_id, "element_id")
    resolved_resource_id = _resolve_required_str(client, resource_id, "resource_id")
    resolved_branch_id = _resolve_required_str(client, branch_id, "branch_id")
    resolved_workspace_id = _resolve_optional_str(client, workspace_id, "workspace_id")
    candidates: list[str] = []
    if resolved_workspace_id:
        candidates.append("/osmc/workspaces/{workspace_id}/resources/{resource_id}/branches/{branch_id}/elements/{element_id}")
    candidates.extend(
        [
            "/osmc/resources/{resource_id}/branches/{branch_id}/elements/{element_id}",
            "/osmc/resources/{resource_id}/elements/{element_id}",
        ]
    )
    return client.request_json(
        "GET",
        _render_candidates(
            client,
            candidates,
            workspace_id=resolved_workspace_id or None,
            resource_id=resolved_resource_id,
            branch_id=resolved_branch_id,
            element_id=resolved_element_id,
        ),
    )


def get_elements_batch(
    client: TwcExampleClient,
    element_ids: list[str] | None = None,
    *,
    element_id: str | None = None,
    resource_id: str | None = None,
    branch_id: str | None = None,
    workspace_id: str | None = None,
) -> Any:
    resolved_resource_id = _resolve_required_str(client, resource_id, "resource_id")
    resolved_branch_id = _resolve_required_str(client, branch_id, "branch_id")
    resolved_workspace_id = _resolve_optional_str(client, workspace_id, "workspace_id")
    resolved_element_ids = _resolve_element_ids(client, element_ids, element_id)

    candidates: list[str] = []
    if resolved_workspace_id:
        candidates.append("/osmc/workspaces/{workspace_id}/resources/{resource_id}/branches/{branch_id}/elements")
    candidates.append("/osmc/resources/{resource_id}/branches/{branch_id}/elements")
    return client.request_json(
        "POST",
        _render_candidates(
            client,
            candidates,
            workspace_id=resolved_workspace_id or None,
            resource_id=resolved_resource_id,
            branch_id=resolved_branch_id,
        ),
        text_body=",".join(resolved_element_ids),
        timeout=max(client.config.request_timeout_seconds, 60),
    )


def patch_element(
    client: TwcExampleClient,
    payload: dict[str, Any] | None = None,
    *,
    element_id: str | None = None,
    resource_id: str | None = None,
    branch_id: str | None = None,
) -> Any:
    resolved_element_id = _resolve_required_str(client, element_id, "element_id")
    resolved_resource_id = _resolve_required_str(client, resource_id, "resource_id")
    resolved_branch_id = _resolve_required_str(client, branch_id, "branch_id")
    resolved_payload = _resolve_update_payload(client, payload)
    candidates = _render_candidates(
        client,
        ["/osmc/resources/{resource_id}/branches/{branch_id}/elements/{element_id}"],
        resource_id=resolved_resource_id,
        branch_id=resolved_branch_id,
        element_id=resolved_element_id,
    )
    return client.request_json("PATCH", candidates, json_body=resolved_payload)


def put_element(
    client: TwcExampleClient,
    payload: dict[str, Any] | None = None,
    *,
    element_id: str | None = None,
    resource_id: str | None = None,
    branch_id: str | None = None,
) -> Any:
    resolved_element_id = _resolve_required_str(client, element_id, "element_id")
    resolved_resource_id = _resolve_required_str(client, resource_id, "resource_id")
    resolved_branch_id = _resolve_required_str(client, branch_id, "branch_id")
    resolved_payload = _resolve_update_payload(client, payload)
    candidates = _render_candidates(
        client,
        ["/osmc/resources/{resource_id}/branches/{branch_id}/elements/{element_id}"],
        resource_id=resolved_resource_id,
        branch_id=resolved_branch_id,
        element_id=resolved_element_id,
    )
    return client.request_json("PUT", candidates, json_body=resolved_payload)


def update_element(
    client: TwcExampleClient,
    payload: dict[str, Any] | None = None,
    *,
    element_id: str | None = None,
    resource_id: str | None = None,
    branch_id: str | None = None,
) -> Any:
    last_error: Exception | None = None
    for method in (patch_element, put_element):
        try:
            return method(
                client,
                payload,
                element_id=element_id,
                resource_id=resource_id,
                branch_id=branch_id,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    if last_error is not None:
        raise last_error
    raise ExampleError("Element update did not produce a response.")


def get_revision_diff(
    client: TwcExampleClient,
    resource_id: str | None = None,
    source_revision: str | None = None,
    target_revision: str | None = None,
) -> Any:
    resolved_resource_id = _resolve_required_str(client, resource_id, "resource_id")
    resolved_source_revision = _resolve_required_str(client, source_revision, "source_revision")
    resolved_target_revision = _resolve_required_str(client, target_revision, "target_revision")
    return client.request_json(
        "GET",
        _render_candidates(
            client,
            [
                "/osmc/resources/{resource_id}/revisiondiff?source={source_revision}&target={target_revision}",
            ],
            resource_id=resolved_resource_id,
            source_revision=resolved_source_revision,
            target_revision=resolved_target_revision,
        ),
    )


def list_branch_artifacts(
    client: TwcExampleClient,
    workspace_id: str | None = None,
    resource_id: str | None = None,
    branch_id: str | None = None,
) -> Any:
    resolved_workspace_id = _resolve_required_str(client, workspace_id, "workspace_id")
    resolved_resource_id = _resolve_required_str(client, resource_id, "resource_id")
    resolved_branch_id = _resolve_required_str(client, branch_id, "branch_id")
    return client.request_json(
        "GET",
        _render_candidates(
            client,
            [
                "/osmc/workspaces/{workspace_id}/resources/{resource_id}/branches/{branch_id}/artifacts",
            ],
            workspace_id=resolved_workspace_id,
            resource_id=resolved_resource_id,
            branch_id=resolved_branch_id,
        ),
    )


def get_branch_artifact(
    client: TwcExampleClient,
    artifact_id: str | None = None,
    *,
    workspace_id: str | None = None,
    resource_id: str | None = None,
    branch_id: str | None = None,
    download: bool = False,
) -> Any:
    resolved_workspace_id = _resolve_required_str(client, workspace_id, "workspace_id")
    resolved_resource_id = _resolve_required_str(client, resource_id, "resource_id")
    resolved_branch_id = _resolve_required_str(client, branch_id, "branch_id")
    resolved_artifact_id = _resolve_required_str(client, artifact_id, "artifact_id")
    return client.request_json(
        "GET",
        _render_candidates(
            client,
            [
                "/osmc/workspaces/{workspace_id}/resources/{resource_id}/branches/{branch_id}/artifacts/{artifact_id}",
            ],
            workspace_id=resolved_workspace_id,
            resource_id=resolved_resource_id,
            branch_id=resolved_branch_id,
            artifact_id=resolved_artifact_id,
        ),
        params={"download": "true" if download else "false"},
    )


def _discover_elements_state(
    client: TwcExampleClient,
    resource_id: str | None = None,
    branch_id: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    resolved_resource_id = _resolve_required_str(client, resource_id, "resource_id")
    resolved_branch_id = _resolve_required_str(client, branch_id, "branch_id")
    resolved_workspace_id = _resolve_optional_str(client, workspace_id, "workspace_id")

    model_payload = list_models(
        client,
        resource_id=resolved_resource_id,
        branch_id=resolved_branch_id,
        workspace_id=resolved_workspace_id or None,
    )
    model_ids = container_member_ids(model_payload)
    if not model_ids:
        raise ExampleError("No model IDs were discovered for the configured resource and branch.")

    seed_ids: list[str] = []
    for model_id in model_ids:
        model_detail = get_model(
            client,
            model_id=model_id,
            resource_id=resolved_resource_id,
            branch_id=resolved_branch_id,
            workspace_id=resolved_workspace_id or None,
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
        raise ExampleError("No root element IDs were discovered from the model list.")

    queue = deque(seed_ids)
    discovered_ids = list(seed_ids)
    visited_ids: set[str] = set()
    seen_ids = set(seed_ids)
    payloads_by_id: dict[str, Any] = {}

    while queue:
        current_element_id = queue.popleft()
        if current_element_id in visited_ids:
            continue

        element_payload = get_element(
            client,
            element_id=current_element_id,
            resource_id=resolved_resource_id,
            branch_id=resolved_branch_id,
            workspace_id=resolved_workspace_id or None,
        )
        payloads_by_id[current_element_id] = element_payload
        visited_ids.add(current_element_id)

        for child_id in element_containment_ids(element_payload):
            if child_id in seen_ids:
                continue
            seen_ids.add(child_id)
            discovered_ids.append(child_id)
            queue.append(child_id)

    hydrated = get_elements_batch(
        client,
        element_ids=discovered_ids,
        resource_id=resolved_resource_id,
        branch_id=resolved_branch_id,
        workspace_id=resolved_workspace_id or None,
    )
    if isinstance(hydrated, dict):
        payloads_by_id.update({str(key): value for key, value in hydrated.items()})

    return {
        "workspace_id": resolved_workspace_id or None,
        "resource_id": resolved_resource_id,
        "branch_id": resolved_branch_id,
        "model_ids": model_ids,
        "seed_ids": seed_ids,
        "discovered_ids": discovered_ids,
        "payloads_by_id": payloads_by_id,
    }


def _element_entries_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    discovered_ids = state.get("discovered_ids")
    payloads_by_id = state.get("payloads_by_id")
    if not isinstance(discovered_ids, list) or not isinstance(payloads_by_id, dict):
        raise ExampleError("Element discovery did not return the expected state.")

    entries = [
        {
            "element_id": element_id,
            "name": display_name(payloads_by_id.get(element_id), element_id),
        }
        for element_id in discovered_ids
    ]
    entries.sort(key=lambda item: (item["name"].lower(), item["element_id"].lower()))
    return entries


def discover_elements_from_models(
    client: TwcExampleClient,
    resource_id: str | None = None,
    branch_id: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    state = _discover_elements_state(
        client,
        resource_id=resource_id,
        branch_id=branch_id,
        workspace_id=workspace_id,
    )
    entries = _element_entries_from_state(state)
    discovered_ids = state["discovered_ids"]

    return {
        "workspace_id": state["workspace_id"],
        "resource_id": state["resource_id"],
        "branch_id": state["branch_id"],
        "model_ids": state["model_ids"],
        "seed_ids": state["seed_ids"],
        "total_ids": len(discovered_ids),
        "entries": entries,
    }


def list_all_elements(
    client: TwcExampleClient,
    resource_id: str | None = None,
    branch_id: str | None = None,
    workspace_id: str | None = None,
) -> list[dict[str, Any]]:
    state = _discover_elements_state(
        client,
        resource_id=resource_id,
        branch_id=branch_id,
        workspace_id=workspace_id,
    )
    return _element_entries_from_state(state)


def get_all_elements(
    client: TwcExampleClient,
    resource_id: str | None = None,
    branch_id: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    state = _discover_elements_state(
        client,
        resource_id=resource_id,
        branch_id=branch_id,
        workspace_id=workspace_id,
    )
    entries = _element_entries_from_state(state)
    discovered_ids = state["discovered_ids"]
    payloads_by_id = state["payloads_by_id"]
    elements = {
        element_id: payloads_by_id.get(element_id)
        for element_id in discovered_ids
        if element_id in payloads_by_id
    }
    return {
        "workspace_id": state["workspace_id"],
        "resource_id": state["resource_id"],
        "branch_id": state["branch_id"],
        "model_ids": state["model_ids"],
        "seed_ids": state["seed_ids"],
        "total_ids": len(discovered_ids),
        "entries": entries,
        "elements": elements,
    }


def run_contract_operation(
    client: TwcExampleClient,
    contract: dict[str, Any] | None = None,
) -> Any:
    resolved_contract = contract if isinstance(contract, dict) else client.config.context.contract_example or {}
    method = str(resolved_contract.get("method") or "").strip().upper()
    path = str(resolved_contract.get("path") or "").strip()
    query_params = resolved_contract.get("query_params") if isinstance(resolved_contract.get("query_params"), dict) else {}
    json_body = resolved_contract.get("json_body")
    text_body = resolved_contract.get("text_body")

    if not method:
        raise ExampleError("Set contract.method or context.contract_example.method in examples/config.json")
    if not path:
        raise ExampleError("Set contract.path or context.contract_example.path in examples/config.json")

    return client.request_json(
        method,
        [path],
        params=query_params,
        json_body=json_body,
        text_body=text_body if isinstance(text_body, str) else None,
    )


def _resolve_magicdraw_api(
    api: MagicDrawOpenAPI | None = None,
    config: MagicDrawJVMConfig | None = None,
) -> MagicDrawOpenAPI:
    if api is not None:
        return api
    return get_magicdraw_api(config)


def get_active_project(
    *,
    api: MagicDrawOpenAPI | None = None,
    config: MagicDrawJVMConfig | None = None,
) -> Any:
    return _resolve_magicdraw_api(api, config).active_project()


def list_open_projects(
    *,
    api: MagicDrawOpenAPI | None = None,
    config: MagicDrawJVMConfig | None = None,
) -> list[Any]:
    return _resolve_magicdraw_api(api, config).open_projects()


def get_project_summary(
    project: Any | None = None,
    *,
    api: MagicDrawOpenAPI | None = None,
    config: MagicDrawJVMConfig | None = None,
) -> dict[str, Any]:
    return _resolve_magicdraw_api(api, config).project_summary(project)


def list_project_models(
    project: Any | None = None,
    *,
    api: MagicDrawOpenAPI | None = None,
    config: MagicDrawJVMConfig | None = None,
) -> list[Any]:
    return _resolve_magicdraw_api(api, config).project_models(project)


def list_project_diagrams(
    project: Any | None = None,
    diagram_type: str | None = None,
    *,
    api: MagicDrawOpenAPI | None = None,
    config: MagicDrawJVMConfig | None = None,
) -> list[Any]:
    return _resolve_magicdraw_api(api, config).project_diagrams(project, diagram_type)


def get_element_by_id(
    element_id: str,
    project: Any | None = None,
    *,
    api: MagicDrawOpenAPI | None = None,
    config: MagicDrawJVMConfig | None = None,
) -> Any:
    return _resolve_magicdraw_api(api, config).get_element_by_id(element_id, project)


def list_factory_methods(
    project: Any | None = None,
    *,
    api: MagicDrawOpenAPI | None = None,
    config: MagicDrawJVMConfig | None = None,
) -> list[str]:
    return _resolve_magicdraw_api(api, config).available_factory_methods(project)


def create_class(
    parent: Any,
    name: str,
    *,
    project: Any | None = None,
    session_name: str | None = None,
    api: MagicDrawOpenAPI | None = None,
    config: MagicDrawJVMConfig | None = None,
) -> Any:
    return _resolve_magicdraw_api(api, config).create_class(parent, name, project=project, session_name=session_name)


def create_package(
    parent: Any,
    name: str,
    *,
    project: Any | None = None,
    session_name: str | None = None,
    api: MagicDrawOpenAPI | None = None,
    config: MagicDrawJVMConfig | None = None,
) -> Any:
    return _resolve_magicdraw_api(api, config).create_package(parent, name, project=project, session_name=session_name)


def create_operation(
    parent: Any,
    name: str,
    *,
    project: Any | None = None,
    session_name: str | None = None,
    api: MagicDrawOpenAPI | None = None,
    config: MagicDrawJVMConfig | None = None,
) -> Any:
    return _resolve_magicdraw_api(api, config).create_operation(parent, name, project=project, session_name=session_name)


def create_diagram(
    parent: Any,
    diagram_type: str,
    *,
    open_diagram: bool = False,
    open_in_active_tab: bool = False,
    project: Any | None = None,
    session_name: str | None = None,
    api: MagicDrawOpenAPI | None = None,
    config: MagicDrawJVMConfig | None = None,
) -> Any:
    return _resolve_magicdraw_api(api, config).create_diagram(
        parent,
        diagram_type,
        open_diagram=open_diagram,
        open_in_active_tab=open_in_active_tab,
        project=project,
        session_name=session_name,
    )


def get_profile(
    profile_name: str,
    project: Any | None = None,
    *,
    api: MagicDrawOpenAPI | None = None,
    config: MagicDrawJVMConfig | None = None,
) -> Any:
    return _resolve_magicdraw_api(api, config).get_profile(profile_name, project)


def get_stereotype(
    stereotype_name: str,
    *,
    profile_name: str | None = None,
    project: Any | None = None,
    api: MagicDrawOpenAPI | None = None,
    config: MagicDrawJVMConfig | None = None,
) -> Any:
    return _resolve_magicdraw_api(api, config).get_stereotype(
        stereotype_name,
        profile_name=profile_name,
        project=project,
    )


def list_element_stereotypes(
    element: Any,
    *,
    api: MagicDrawOpenAPI | None = None,
    config: MagicDrawJVMConfig | None = None,
) -> list[Any]:
    return _resolve_magicdraw_api(api, config).element_stereotypes(element)


def has_stereotype(
    element: Any,
    stereotype_name: str,
    *,
    profile_name: str | None = None,
    project: Any | None = None,
    api: MagicDrawOpenAPI | None = None,
    config: MagicDrawJVMConfig | None = None,
) -> bool:
    return _resolve_magicdraw_api(api, config).has_stereotype(
        element,
        stereotype_name,
        profile_name=profile_name,
        project=project,
    )


def apply_stereotype(
    element: Any,
    stereotype_name: str,
    *,
    profile_name: str | None = None,
    project: Any | None = None,
    session_name: str | None = None,
    api: MagicDrawOpenAPI | None = None,
    config: MagicDrawJVMConfig | None = None,
) -> Any:
    return _resolve_magicdraw_api(api, config).apply_stereotype(
        element,
        stereotype_name,
        profile_name=profile_name,
        project=project,
        session_name=session_name,
    )


def remove_stereotype(
    element: Any,
    stereotype_name: str,
    *,
    profile_name: str | None = None,
    project: Any | None = None,
    session_name: str | None = None,
    api: MagicDrawOpenAPI | None = None,
    config: MagicDrawJVMConfig | None = None,
) -> bool:
    return _resolve_magicdraw_api(api, config).remove_stereotype(
        element,
        stereotype_name,
        profile_name=profile_name,
        project=project,
        session_name=session_name,
    )


def get_stereotype_property(
    element: Any,
    stereotype_name: str,
    property_name: str,
    *,
    profile_name: str | None = None,
    project: Any | None = None,
    api: MagicDrawOpenAPI | None = None,
    config: MagicDrawJVMConfig | None = None,
) -> Any:
    return _resolve_magicdraw_api(api, config).get_stereotype_property(
        element,
        stereotype_name,
        property_name,
        profile_name=profile_name,
        project=project,
    )


def set_stereotype_property(
    element: Any,
    stereotype_name: str,
    property_name: str,
    value: Any,
    *,
    profile_name: str | None = None,
    project: Any | None = None,
    session_name: str | None = None,
    api: MagicDrawOpenAPI | None = None,
    config: MagicDrawJVMConfig | None = None,
) -> Any:
    return _resolve_magicdraw_api(api, config).set_stereotype_property(
        element,
        stereotype_name,
        property_name,
        value,
        profile_name=profile_name,
        project=project,
        session_name=session_name,
    )