from __future__ import annotations

import asyncio
import json
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import structlog

from app.models.domain import (
    AttachmentInfo,
    Capability,
    CapabilityState,
    CapabilitySummary,
    CollaboratorDocument,
    CommentEntry,
    CompareDifference,
    CompareResult,
    ElementDiscoveryEntry,
    ElementDiscoveryResult,
    DocumentVersion,
    ItemReference,
    ItemDetails,
    ProjectSummary,
    PublishPreset,
    SearchResponse,
    SearchResult,
    ServerProfile,
    SimulationConfig,
    SimulationParameter,
    SimulationRunRequest,
    TreeNode,
    TWCVersion,
    utcnow,
)
from app.models.domain import BranchSummary, TokenBundle

ProgressReporter = Callable[[int, str], Awaitable[None]]
CancelChecker = Callable[[], bool]

logger = structlog.get_logger(__name__)


UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
ELEMENT_DISCOVERY_MAX_WORKERS = 8
ELEMENT_DISCOVERY_THROTTLE_EVERY = 100
ELEMENT_DISCOVERY_THROTTLE_SECONDS = 2.0


@dataclass
class CurrentUserContext:
    preferred_username: str | None = None
    roles: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)


def _first_list(payload: dict[str, Any], *keys: str) -> list[Any] | None:
    for key in keys:
        if isinstance(payload.get(key), list):
            return payload[key]
    return None


def _first_list_recursive(payload: dict[str, Any], *keys: str) -> list[Any] | None:
    direct = _first_list(payload, *keys)
    if direct is not None:
        return direct
    for value in payload.values():
        if isinstance(value, dict):
            nested = _first_list_recursive(value, *keys)
            if nested is not None:
                return nested
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    nested = _first_list_recursive(item, *keys)
                    if nested is not None:
                        return nested
    return None


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
    return ""


def _payload_dicts(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _payload_list(payload: Any, *keys: str) -> list[Any] | None:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return _first_list_recursive(payload, *keys)
    return None


def _payload_shape(payload: Any, depth: int = 2) -> Any:
    if isinstance(payload, dict):
        if depth <= 0:
            return {"type": "object", "keys": list(payload.keys())[:20]}
        summary: dict[str, Any] = {}
        for key, value in list(payload.items())[:20]:
            summary[key] = _payload_shape(value, depth - 1)
        if len(payload) > 20:
            summary["..."] = f"{len(payload) - 20} more keys"
        return summary
    if isinstance(payload, list):
        if depth <= 0:
            return {"type": "array", "length": len(payload)}
        return {
            "type": "array",
            "length": len(payload),
            "sample": [_payload_shape(item, depth - 1) for item in payload[:3]],
        }
    return type(payload).__name__


def _looks_like_identifier(value: str) -> bool:
    candidate = value.strip()
    if not candidate:
        return False
    if UUID_PATTERN.fullmatch(candidate):
        return True
    return candidate.startswith("_")


def _payload_entity(payload: Any, *markers: str) -> dict[str, Any] | None:
    objects = _payload_dicts(payload)
    if not objects:
        return None

    normalized_markers = tuple(marker.lower() for marker in markers if marker)
    if normalized_markers:
        for item in reversed(objects):
            raw_types = " ".join(_normalize_types(item.get("@type"))).lower()
            if any(marker in raw_types for marker in normalized_markers):
                return item

    for item in reversed(objects):
        if any(
            key in item
            for key in (
                "kerml:esiData",
                "dcterms:title",
                "ID",
                "id",
                "title",
                "name",
                "body_markdown",
                "bodyMarkdown",
                "content",
                "file_name",
                "fileName",
                "author",
            )
        ):
            return item

    return objects[-1]


def _reference_id(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("@id", "id", "resourceId", "resourceID", "value", "href", "models:root", "resource", "kerml:resource"):
            identifier = _reference_id(value.get(key))
            if identifier:
                return identifier
        links = value.get("links")
        if isinstance(links, dict):
            identifier = _reference_id(links.get("self"))
            if identifier:
                return identifier
        rdf_resource = value.get("rdf:resource")
        if rdf_resource is not None:
            identifier = _reference_id(rdf_resource)
            if identifier:
                return identifier
        return None
    if isinstance(value, list):
        for item in value:
            identifier = _reference_id(item)
            if identifier:
                return identifier
        return None
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.startswith("#"):
        candidate = candidate[1:]
    parsed = urlparse(candidate)
    if parsed.fragment and parsed.fragment != "it":
        return parsed.fragment
    path = parsed.path or candidate
    segments = [segment for segment in path.split("/") if segment not in {"", ".", ".."}]
    return segments[-1] if segments else candidate


def extract_resource_list(payload: Any) -> list[Any] | None:
    data: Any = None

    if isinstance(payload, list):
        data = payload
    elif isinstance(payload, dict):
        if "ldp:contains" in payload:
            data = payload["ldp:contains"]
        elif "kerml:resources" in payload:
            data = payload["kerml:resources"]
        elif "resources" in payload:
            data = payload["resources"]
        elif "items" in payload:
            data = payload["items"]

    return data if isinstance(data, list) else None


def _workspace_objects(payload: Any) -> list[Any]:
    candidates: list[Any] = []

    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        nested = _first_list_recursive(payload, "ldp:contains", "items", "workspaces", "data")
        if nested is not None:
            candidates = nested
        elif isinstance(payload.get("kerml:resources"), list):
            candidates = [payload]

    workspaces: list[Any] = []
    for item in candidates:
        entity = _payload_entity(item, "workspace") if isinstance(item, (dict, list)) else None
        if entity is None and isinstance(item, (dict, list)):
            entity = _payload_entity(item)
        if not isinstance(entity, dict):
            continue
        raw_types = " ".join(_normalize_types(entity.get("@type"))).lower()
        if isinstance(entity.get("kerml:resources"), list) or "workspace" in raw_types or _reference_id(entity.get("@id") or entity.get("id")):
            workspaces.append(item)

    return workspaces


def _workspace_resource_ids(workspace_payload: Any) -> list[str]:
    resource_ids: list[str] = []
    entity = _payload_entity(workspace_payload, "workspace") if isinstance(workspace_payload, (dict, list)) else None
    raw_resources = entity.get("kerml:resources") if isinstance(entity, dict) else None
    if not isinstance(raw_resources, list):
        return resource_ids

    for raw_resource in raw_resources:
        resource_id = _reference_id(raw_resource)
        if resource_id and resource_id not in {"it"} and resource_id not in resource_ids:
            resource_ids.append(resource_id)

    return resource_ids


def _resource_id_from_payload(payload: Any) -> str | None:
    entity = _payload_entity(payload, "resource") if isinstance(payload, (dict, list)) else None
    if entity is None:
        entity = _payload_entity(payload) if isinstance(payload, (dict, list)) else None
    if not isinstance(entity, dict):
        return _reference_id(payload)

    for key in ("__resource_id", "resourceID", "resourceId", "ID", "@base", "kerml:resource", "resource", "id", "@id"):
        identifier = _reference_id(entity.get(key))
        if identifier and identifier != "it":
            return identifier
    return None


def _container_member_ids(payload: Any) -> list[str]:
    identifiers: list[str] = []
    data = extract_resource_list(payload) or []

    for item in data:
        candidate = ""
        if isinstance(item, dict):
            for key in ("branchID", "modelID", "ID", "id", "@id"):
                value = item.get(key)
                if isinstance(value, (str, int)):
                    candidate = str(value).strip()
                    if candidate:
                        break
        elif isinstance(item, (str, int)):
            candidate = str(item).strip()

        if not candidate:
            continue
        if "#" in candidate:
            candidate = candidate.split("#", 1)[-1]
        if "/" in candidate:
            candidate = candidate.rstrip("/").split("/")[-1]
        if candidate and candidate != "it" and candidate not in identifiers:
            identifiers.append(candidate)
    return identifiers


def _element_containment_ids(payload: Any) -> list[str]:
    identifiers: list[str] = []

    for item in _payload_dicts(payload):
        for key in ("ldp:contains", "kerml:ownedElement", "kerml:packagedElement"):
            for reference in _as_list(item.get(key)):
                candidate = _reference_id(reference)
                if candidate and candidate != "it" and candidate not in identifiers:
                    identifiers.append(candidate)

    if identifiers:
        return identifiers

    return _container_member_ids(payload)


def map_projects(payload: Any) -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []

    if not isinstance(payload, list):
        logger.error(f"Expected list payload, got {type(payload)}")
        return projects

    logger.info(f"Raw items: {len(payload)}")

    for item in payload:
        if not isinstance(item, dict):
            continue

        metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
        resource_id = _resource_id_from_payload(item)
        workspace_id = item.get("__workspace_id") if isinstance(item.get("__workspace_id"), str) else None
        name = _first_text(metadata.get("name"), item.get("dcterms:title"), item.get("name"), resource_id or "")
        branch_uuid = _reference_id(metadata.get("mdResourceBranchUUID"))

        if name and resource_id:
            projects.append(
                {
                    "id": resource_id,
                    "name": name,
                    "branch_uuid": branch_uuid,
                    "workspace_id": workspace_id,
                    "resource_id": resource_id,
                    "categories": item.get("categoryID") if item.get("categoryID") is not None else item.get("kerml:categories"),
                    "description": _first_text(item.get("dcterms:description"), item.get("description")),
                }
            )

    logger.info(f"Parsed project count: {len(projects)}")
    if not projects and payload:
        logger.error(f"SAMPLE ITEM: {payload[0]}")

    return projects


def _normalize_types(value: Any) -> list[str]:
    return [str(item) for item in _as_list(value) if str(item).strip()]


def _is_uuid_like(value: str) -> bool:
    return bool(UUID_PATTERN.fullmatch(value.strip()))


def _claim_text(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        if text and not _is_uuid_like(text):
            return [text]
        return []
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            items.extend(_claim_text(item))
        return items
    if isinstance(value, dict):
        items: list[str] = []
        for key in ("name", "displayName", "authority", "groupName", "roleName", "description", "value"):
            items.extend(_claim_text(value.get(key)))
        return items
    return []


def _humanize_type(raw_type: str) -> str:
    tail = raw_type.split(":")[-1].rsplit("/", 1)[-1]
    normalized = tail.replace("_", " ").replace("-", " ").strip().lower()
    return normalized or "item"


def _flatten_tree_nodes(nodes: list[TreeNode]) -> list[TreeNode]:
    flattened: list[TreeNode] = []
    for node in nodes:
        flattened.append(node)
        if node.children:
            flattened.extend(_flatten_tree_nodes(node.children))
    return flattened


class FallbackWorkspaceStore:
    def __init__(self, base_dir: Path, server_id: str) -> None:
        self.base_dir = base_dir / "fallback" / server_id
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_file = self.base_dir / "workspace.json"

    def ensure_seeded(self) -> None:
        if self.workspace_file.exists():
            return
        payload = {
            "projects": [
                {
                    "id": "aircraft-systems",
                    "name": "Aircraft Systems",
                    "description": "Reference architecture for flight controls and resilience trade studies.",
                    "favorite": True,
                    "branches": [
                        {"id": "main", "name": "main", "description": "Production baseline"},
                        {"id": "analysis", "name": "analysis", "description": "Simulation-driven branch"},
                    ],
                },
                {
                    "id": "mission-ops",
                    "name": "Mission Ops",
                    "description": "Operational procedures, readiness views, and collaborator-ready documentation.",
                    "favorite": False,
                    "branches": [
                        {"id": "main", "name": "main", "description": "Operational release"},
                    ],
                },
            ],
            "tree": [
                {
                    "id": "pkg-context",
                    "label": "System Context",
                    "node_type": "package",
                    "path": "Aircraft Systems/System Context",
                    "metadata": {"project_id": "aircraft-systems", "branch_id": "main"},
                    "children": [
                        {
                            "id": "item-context-diagram",
                            "label": "Context Diagram",
                            "node_type": "diagram",
                            "path": "Aircraft Systems/System Context/Context Diagram",
                            "metadata": {"project_id": "aircraft-systems", "branch_id": "main"},
                            "children": [],
                        },
                        {
                            "id": "item-stakeholders",
                            "label": "Stakeholder Needs",
                            "node_type": "requirements",
                            "path": "Aircraft Systems/System Context/Stakeholder Needs",
                            "metadata": {"project_id": "aircraft-systems", "branch_id": "main"},
                            "children": [],
                        },
                    ],
                },
                {
                    "id": "pkg-flight-control",
                    "label": "Flight Control",
                    "node_type": "package",
                    "path": "Aircraft Systems/Logical Architecture/Flight Control",
                    "metadata": {"project_id": "aircraft-systems", "branch_id": "analysis"},
                    "children": [
                        {
                            "id": "item-fcs-model",
                            "label": "Flight Control Model",
                            "node_type": "block",
                            "path": "Aircraft Systems/Logical Architecture/Flight Control/Flight Control Model",
                            "metadata": {"project_id": "aircraft-systems", "branch_id": "analysis"},
                            "children": [],
                        },
                        {
                            "id": "item-fcs-sim",
                            "label": "Stability Margin Study",
                            "node_type": "simulation",
                            "path": "Aircraft Systems/Logical Architecture/Flight Control/Stability Margin Study",
                            "metadata": {"project_id": "aircraft-systems", "branch_id": "analysis"},
                            "children": [],
                        },
                    ],
                },
            ],
            "items": {
                "item-context-diagram": {
                    "id": "item-context-diagram",
                    "name": "Context Diagram",
                    "item_type": "diagram",
                    "path": "Aircraft Systems/System Context/Context Diagram",
                    "project_id": "aircraft-systems",
                    "branch_id": "main",
                    "description": "High-level context framing external systems, operators, and constraints.",
                    "documentation_markdown": "# Context Diagram\n\nThis view captures the operational system boundary, external interfaces, and mission constraints.",
                    "metadata": {"owner": "Architecture", "status": "Published", "classifier": "Operational View"},
                    "relationships": [{"type": "refines", "target": "item-stakeholders"}],
                    "version": "3.2",
                    "editable": False,
                    "attachment_supported": True,
                    "collaborators": ["ops.lead", "chief.arch"],
                },
                "item-stakeholders": {
                    "id": "item-stakeholders",
                    "name": "Stakeholder Needs",
                    "item_type": "requirements",
                    "path": "Aircraft Systems/System Context/Stakeholder Needs",
                    "project_id": "aircraft-systems",
                    "branch_id": "main",
                    "description": "Critical needs driving system architecture and downstream simulation scenarios.",
                    "documentation_markdown": "# Stakeholder Needs\n\n- Reduce operator workload\n- Maintain degraded-mode controllability\n- Publish collaborator-ready evidence packs",
                    "metadata": {"owner": "Systems Engineering", "status": "Approved", "priority": "High"},
                    "relationships": [{"type": "satisfies", "target": "item-fcs-model"}],
                    "version": "2.1",
                    "editable": False,
                    "attachment_supported": True,
                    "collaborators": ["systems.lead"],
                },
                "item-fcs-model": {
                    "id": "item-fcs-model",
                    "name": "Flight Control Model",
                    "item_type": "block",
                    "path": "Aircraft Systems/Logical Architecture/Flight Control/Flight Control Model",
                    "project_id": "aircraft-systems",
                    "branch_id": "analysis",
                    "description": "Control law decomposition with redundancy channels and actuator voting.",
                    "documentation_markdown": "# Flight Control Model\n\nEditable branch artifact used for simulation and publish validation.",
                    "metadata": {"owner": "Avionics", "status": "In Review", "safety_class": "DAL-B"},
                    "relationships": [{"type": "verifiedBy", "target": "item-fcs-sim"}],
                    "version": "4.7",
                    "editable": True,
                    "attachment_supported": True,
                    "collaborators": ["avionics.owner", "safety.analyst"],
                },
                "item-fcs-sim": {
                    "id": "item-fcs-sim",
                    "name": "Stability Margin Study",
                    "item_type": "simulation",
                    "path": "Aircraft Systems/Logical Architecture/Flight Control/Stability Margin Study",
                    "project_id": "aircraft-systems",
                    "branch_id": "analysis",
                    "description": "Simulation configuration for handling quality and stability margin sweeps.",
                    "documentation_markdown": "# Stability Margin Study\n\nParameterised study for gain, damping, and disturbance sensitivity.",
                    "metadata": {"owner": "Simulation Team", "status": "Ready", "last_run": "successful"},
                    "relationships": [{"type": "validates", "target": "item-fcs-model"}],
                    "version": "1.9",
                    "editable": True,
                    "attachment_supported": False,
                    "collaborators": ["simulation.owner"],
                },
            },
            "documents": [
                {
                    "id": "doc-flight-control",
                    "title": "Flight Control Architecture Overview",
                    "item_id": "item-fcs-model",
                    "project_id": "aircraft-systems",
                    "branch_id": "analysis",
                    "body_markdown": "# Flight Control Architecture Overview\n\n## Purpose\nThis collaborator document explains the control law decomposition, redundancy channels, and simulation readiness package.\n\n## Key Messages\n- The analysis branch is editable.\n- Simulation evidence is attached to the control model.\n- Publish presets can package this view for review boards.",
                    "breadcrumbs": ["Aircraft Systems", "Logical Architecture", "Flight Control"],
                    "toc": ["Purpose", "Key Messages"],
                    "editable": True,
                    "attachments_supported": True,
                    "versions": [
                        {"id": "v1", "label": "1.0", "created_at": utcnow().isoformat(), "summary": "Initial draft"},
                        {"id": "v2", "label": "1.1", "created_at": utcnow().isoformat(), "summary": "Refined publish notes"},
                    ],
                }
            ],
            "attachments": {
                "doc-flight-control": [
                    {
                        "id": "att-control-matrix",
                        "document_id": "doc-flight-control",
                        "file_name": "control-matrix.xlsx",
                        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        "size_bytes": 48211,
                        "uploaded_at": utcnow().isoformat(),
                        "source": "fallback",
                    }
                ]
            },
            "comments": {
                "doc-flight-control": [
                    {
                        "id": uuid4().hex,
                        "document_id": "doc-flight-control",
                        "author": "chief.arch",
                        "content": "Publish this view with the safety narrative attached.",
                        "created_at": utcnow().isoformat(),
                    }
                ]
            },
        }
        self.workspace_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load(self) -> dict[str, Any]:
        self.ensure_seeded()
        return json.loads(self.workspace_file.read_text(encoding="utf-8"))

    def _save(self, payload: dict[str, Any]) -> None:
        self.workspace_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def projects(self) -> list[ProjectSummary]:
        data = self._load()
        return [ProjectSummary.model_validate(item) for item in data["projects"]]

    def update_branch(self, project_id: str, branch_id: str, name: str | None, description: str | None) -> BranchSummary | None:
        data = self._load()
        for project in data["projects"]:
            if project.get("id") != project_id:
                continue
            for branch in project.get("branches", []):
                if branch.get("id") != branch_id:
                    continue
                if name is not None:
                    branch["name"] = name
                if description is not None:
                    branch["description"] = description
                self._save(data)
                return BranchSummary.model_validate(branch)
        return None

    def tree(self, project_id: str | None = None, branch_id: str | None = None) -> list[TreeNode]:
        data = self._load()
        nodes = [TreeNode.model_validate(item) for item in data["tree"]]
        if not project_id and not branch_id:
            return nodes

        def filter_node(node: TreeNode) -> TreeNode | None:
            node_project = node.metadata.get("project_id")
            node_branch = node.metadata.get("branch_id")
            filtered_children = [child for candidate in node.children if (child := filter_node(candidate))]
            if (project_id and node_project != project_id) and not filtered_children:
                return None
            if (branch_id and node_branch != branch_id) and not filtered_children:
                return None
            node.children = filtered_children
            return node

        return [candidate for item in nodes if (candidate := filter_node(item))]

    def items(self) -> dict[str, ItemDetails]:
        data = self._load()
        return {key: ItemDetails.model_validate(value) for key, value in data["items"].items()}

    def save_item(self, item: ItemDetails) -> ItemDetails:
        data = self._load()
        data.setdefault("items", {})[item.id] = item.model_dump(mode="json")
        self._save(data)
        return item

    def documents(self) -> list[CollaboratorDocument]:
        data = self._load()
        documents = []
        for item in data["documents"]:
            versions = [DocumentVersion.model_validate(version) for version in item.get("versions", [])]
            item["versions"] = versions
            documents.append(CollaboratorDocument.model_validate(item))
        return documents

    def save_document(self, document: CollaboratorDocument) -> CollaboratorDocument:
        data = self._load()
        replaced = False
        serialized = document.model_dump(mode="json")
        for index, existing in enumerate(data["documents"]):
            if existing["id"] == document.id:
                data["documents"][index] = serialized
                replaced = True
                break
        if not replaced:
            data["documents"].append(serialized)
        self._save(data)
        return document

    def attachments(self, document_id: str) -> list[AttachmentInfo]:
        data = self._load()
        return [AttachmentInfo.model_validate(item) for item in data["attachments"].get(document_id, [])]

    def add_attachment(self, document_id: str, file_name: str, content_type: str, content: bytes) -> AttachmentInfo:
        attachments_dir = self.base_dir / "attachments" / document_id
        attachments_dir.mkdir(parents=True, exist_ok=True)
        attachment = AttachmentInfo(
            id=uuid4().hex,
            document_id=document_id,
            file_name=file_name,
            content_type=content_type,
            size_bytes=len(content),
            source="fallback",
        )
        (attachments_dir / attachment.id).write_bytes(content)
        data = self._load()
        data.setdefault("attachments", {}).setdefault(document_id, []).append(attachment.model_dump(mode="json"))
        self._save(data)
        return attachment

    def delete_attachment(self, document_id: str, attachment_id: str) -> bool:
        attachments_dir = self.base_dir / "attachments" / document_id
        file_path = attachments_dir / attachment_id
        if file_path.exists():
            file_path.unlink()
        data = self._load()
        existing = data.setdefault("attachments", {}).get(document_id, [])
        updated = [item for item in existing if item["id"] != attachment_id]
        changed = len(existing) != len(updated)
        data["attachments"][document_id] = updated
        self._save(data)
        return changed

    def attachment_path(self, document_id: str, attachment_id: str) -> Path | None:
        file_path = self.base_dir / "attachments" / document_id / attachment_id
        return file_path if file_path.exists() else None

    def comments(self, document_id: str) -> list[CommentEntry]:
        data = self._load()
        return [CommentEntry.model_validate(item) for item in data["comments"].get(document_id, [])]

    def add_comment(self, document_id: str, author: str, content: str) -> CommentEntry:
        comment = CommentEntry(document_id=document_id, author=author, content=content)
        data = self._load()
        data.setdefault("comments", {}).setdefault(document_id, []).append(comment.model_dump(mode="json"))
        self._save(data)
        return comment


@dataclass(slots=True)
class AdapterContext:
    server: ServerProfile
    tokens: TokenBundle
    storage_dir: Path


class TeamworkAdapter:
    def __init__(self, context: AdapterContext) -> None:
        self.context = context
        self._detected_version: str | None = None
        self._last_project_list_issue: str | None = None
        self.verify = (
            context.server.ca_bundle_path if context.server.verify_tls and context.server.ca_bundle_path else context.server.verify_tls
        )

    @property
    def headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, application/ld+json;q=0.9, text/plain;q=0.5",
        }
        if self.context.tokens.access_token:
            headers["Authorization"] = f"{self.context.tokens.token_type} {self.context.tokens.access_token}"
        return headers

    def _candidate_url(self, candidate: str) -> str:
        if candidate.startswith(("http://", "https://")):
            return candidate
        return f"{self.context.server.base_url.rstrip('/')}{candidate}"

    def _candidate_path(self, candidate: str) -> str:
        if candidate.startswith(("http://", "https://")):
            parsed = urlparse(candidate)
            return parsed.path or candidate
        return candidate

    async def _contract_version(self) -> str:
        return await self.detect_version()

    def _is_batch_elements_path(self, path: str) -> bool:
        return path.startswith("/osmc/") and path.endswith("/elements") and "/elements/" not in path

    def _serialize_text_payload(self, payload: Any) -> str:
        if isinstance(payload, str):
            return payload
        if isinstance(payload, (list, tuple, set)):
            return ",".join(str(item) for item in payload)
        if isinstance(payload, dict):
            if "value" in payload:
                return str(payload["value"])
            return json.dumps(payload, separators=(",", ":"))
        return str(payload)

    def _request_body_mode(self, method: str, path: str, payload: Any, version: str) -> str:
        upper_method = method.upper()
        if upper_method in {"PATCH", "PUT", "POST"} and "/elements/" in path:
            return "ld_json"
        if upper_method in {"PATCH", "PUT"} and self._is_batch_elements_path(path):
            return "ld_json"
        if upper_method == "POST" and self._is_batch_elements_path(path):
            return "json" if version == "2024x" else "text_plain"
        if upper_method == "PUT" and path.startswith("/osmc/admin/config/"):
            return "json" if version == "2024x" else "text_plain"
        if upper_method == "PATCH" and path.startswith("/osmc/admin/ldaps/") and path.endswith(("/resync/users", "/resync/usergroups")):
            return "json" if version == "2024x" else "text_plain"
        if upper_method == "POST" and "/roles/" in path and path.endswith(("/users", "/usergroups")):
            return "json" if version == "2024x" else "text_plain"
        if upper_method == "PUT" and path in {"/osmc/admin/usergroups", "/osmc/workspaces"}:
            return "json" if version == "2024x" else "text_plain"
        if upper_method == "POST" and path.endswith("/tags"):
            if isinstance(payload, list):
                return "json" if version == "2024x" else "text_plain"
            return "ld_json"
        return "json"

    def _decode_response(self, response: httpx.Response) -> dict[str, Any] | list[Any]:
        if response.status_code == 204 or not response.content:
            return {"ok": True}
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type or "application/ld+json" in content_type or "application/problem+json" in content_type:
            return response.json()
        return {"raw": response.text}

    async def _request_raw_candidates(
        self,
        method: str,
        candidates: list[str],
        *,
        json_payload: Any | None = None,
        content_payload: str | bytes | None = None,
        files: Any | None = None,
        extra_headers: dict[str, str] | None = None,
        timeout: float = 20.0,
    ) -> tuple[httpx.Response, str] | None:
        if not candidates:
            return None
        client_kwargs: dict[str, Any] = {
            "timeout": timeout,
            "verify": self.verify,
            "follow_redirects": True,
        }
        if self.context.tokens.session_cookies:
            client_kwargs["cookies"] = self.context.tokens.session_cookies
        async with httpx.AsyncClient(**client_kwargs) as client:
            for candidate in candidates:
                url = self._candidate_url(candidate)
                headers = dict(self.headers)
                if extra_headers:
                    headers.update(extra_headers)
                request_kwargs: dict[str, Any] = {}
                if files is not None:
                    request_kwargs["files"] = files
                elif content_payload is not None:
                    request_kwargs["content"] = content_payload
                elif json_payload is not None:
                    version = await self._contract_version()
                    body_mode = self._request_body_mode(method, self._candidate_path(candidate), json_payload, version)
                    if body_mode == "text_plain":
                        headers["Content-Type"] = "text/plain"
                        request_kwargs["content"] = self._serialize_text_payload(json_payload)
                    elif body_mode == "ld_json":
                        headers["Content-Type"] = "application/ld+json"
                        request_kwargs["content"] = json.dumps(json_payload)
                    else:
                        request_kwargs["json"] = json_payload
                try:
                    response = await client.request(method, url, headers=headers, **request_kwargs)
                except httpx.HTTPError:
                    continue
                if 200 <= response.status_code < 300 or response.status_code in {401, 403}:
                    return response, candidate
        return None

    async def execute_contract_request(
        self,
        method: str,
        candidate: str,
        *,
        content_payload: str | bytes | None = None,
        files: Any | None = None,
        extra_headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> tuple[httpx.Response, str]:
        client_kwargs: dict[str, Any] = {
            "timeout": timeout,
            "verify": self.verify,
            "follow_redirects": True,
        }
        if self.context.tokens.session_cookies:
            client_kwargs["cookies"] = self.context.tokens.session_cookies

        async with httpx.AsyncClient(**client_kwargs) as client:
            headers = dict(self.headers)
            if extra_headers:
                headers.update(extra_headers)
            request_kwargs: dict[str, Any] = {}
            if files is not None:
                request_kwargs["files"] = files
            elif content_payload is not None:
                request_kwargs["content"] = content_payload
            try:
                response = await client.request(method, self._candidate_url(candidate), headers=headers, **request_kwargs)
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Teamwork Cloud request failed for {method} {candidate}: {exc}") from exc
        return response, candidate

    async def _request_candidates(
        self,
        method: str,
        candidates: list[str],
        *,
        json_payload: Any | None = None,
        timeout: float = 20.0,
    ) -> dict[str, Any] | list[Any] | None:
        raw_result = await self._request_raw_candidates(method, candidates, json_payload=json_payload, timeout=timeout)
        if not raw_result:
            return None
        response, _ = raw_result
        if response.status_code in {401, 403}:
            return {"restricted": True, "status_code": response.status_code}
        return self._decode_response(response)

    async def _request_candidates_with_trace(
        self,
        method: str,
        candidates: list[str],
        *,
        timeout: float = 20.0,
    ) -> tuple[dict[str, Any] | list[Any] | None, dict[str, Any]]:
        attempts: list[dict[str, Any]] = []
        client_kwargs: dict[str, Any] = {
            "timeout": timeout,
            "verify": self.verify,
            "follow_redirects": True,
        }
        if self.context.tokens.session_cookies:
            client_kwargs["cookies"] = self.context.tokens.session_cookies

        async with httpx.AsyncClient(**client_kwargs) as client:
            for candidate in candidates:
                url = self._candidate_url(candidate)
                headers = dict(self.headers)
                try:
                    response = await client.request(method, url, headers=headers)
                except httpx.HTTPError as exc:
                    attempts.append({"candidate": candidate, "error": str(exc)})
                    continue

                attempts.append({"candidate": candidate, "status_code": response.status_code})
                if 200 <= response.status_code < 300 or response.status_code in {401, 403}:
                    if response.status_code in {401, 403}:
                        return {"restricted": True, "status_code": response.status_code}, {
                            "selected_candidate": candidate,
                            "status_code": response.status_code,
                            "attempts": attempts,
                        }
                    return self._decode_response(response), {
                        "selected_candidate": candidate,
                        "status_code": response.status_code,
                        "attempts": attempts,
                    }

        return None, {"selected_candidate": None, "status_code": None, "attempts": attempts}

    def _trace_summary(self, trace: dict[str, Any]) -> str:
        parts: list[str] = []
        for attempt in trace.get("attempts", []):
            candidate = str(attempt.get("candidate") or "unknown")
            if attempt.get("status_code") is not None:
                parts.append(f"{candidate} -> HTTP {attempt['status_code']}")
            elif attempt.get("error"):
                parts.append(f"{candidate} -> {attempt['error']}")
        return "; ".join(parts) or "no usable candidate response"

    def _candidate_from_reference(self, reference: Any) -> str | None:
        raw_value: str | None = None
        if isinstance(reference, dict):
            for key in ("href", "@id", "id", "url", "next"):
                value = reference.get(key)
                if isinstance(value, str) and value.strip():
                    raw_value = value.strip()
                    break
        elif isinstance(reference, str):
            raw_value = reference.strip()

        if not raw_value:
            return None

        parsed = urlparse(raw_value)
        if parsed.scheme and parsed.netloc:
            candidate = parsed.path or "/"
            if parsed.query:
                candidate = f"{candidate}?{parsed.query}"
            return candidate
        if raw_value.startswith("/"):
            return raw_value
        return None

    def _pagination_candidate(self, payload: Any, response: httpx.Response) -> str | None:
        link_header = response.headers.get("link", "")
        if link_header:
            for part in link_header.split(","):
                if 'rel="next"' not in part:
                    continue
                start = part.find("<")
                end = part.find(">", start + 1)
                if start >= 0 and end > start:
                    candidate = self._candidate_from_reference(part[start + 1 : end])
                    if candidate:
                        return candidate

        if not isinstance(payload, dict):
            return None

        for key in ("hydra:next", "ldp:nextPage", "next", "nextPage"):
            candidate = self._candidate_from_reference(payload.get(key))
            if candidate:
                return candidate

        links = payload.get("links")
        if isinstance(links, dict):
            candidate = self._candidate_from_reference(links.get("next"))
            if candidate:
                return candidate

        return None

    def _merge_paged_payload(self, current: Any, extra: Any) -> Any:
        if isinstance(current, list) and isinstance(extra, list):
            merged = list(current)
            for item in extra:
                if item not in merged:
                    merged.append(item)
            return merged

        if isinstance(current, dict) and isinstance(extra, dict):
            merged = dict(current)
            for key in ("ldp:contains", "items", "data"):
                current_items = merged.get(key)
                extra_items = extra.get(key)
                if isinstance(current_items, list) and isinstance(extra_items, list):
                    combined = list(current_items)
                    for item in extra_items:
                        if item not in combined:
                            combined.append(item)
                    merged[key] = combined
            return merged

        return current

    async def _request_candidates_paged(
        self,
        method: str,
        candidates: list[str],
        *,
        timeout: float = 20.0,
    ) -> dict[str, Any] | list[Any] | None:
        raw_result = await self._request_raw_candidates(method, candidates, timeout=timeout)
        if not raw_result:
            return None

        response, _ = raw_result
        if response.status_code in {401, 403}:
            return {"restricted": True, "status_code": response.status_code}

        payload: dict[str, Any] | list[Any] = self._decode_response(response)
        next_candidate = self._pagination_candidate(payload, response)
        seen_candidates: set[str] = set()

        while next_candidate and next_candidate not in seen_candidates:
            seen_candidates.add(next_candidate)
            next_response, _ = await self.execute_contract_request("GET", next_candidate, timeout=timeout)
            if next_response.status_code in {401, 403}:
                break
            next_payload = self._decode_response(next_response)
            payload = self._merge_paged_payload(payload, next_payload)
            next_candidate = self._pagination_candidate(next_payload, next_response)

        return payload

    def _extract_current_username(self, payload: Any) -> str | None:
        candidates: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            candidates.append(payload)
            entity = _payload_entity(payload, "user")
            if entity and entity not in candidates:
                candidates.append(entity)
            for key in ("user", "data", "item"):
                value = payload.get(key)
                if isinstance(value, dict) and value not in candidates:
                    candidates.append(value)
        elif isinstance(payload, list):
            candidates.extend(item for item in payload if isinstance(item, dict))

        for candidate in candidates:
            username = _first_text(
                candidate.get("userName"),
                candidate.get("username"),
                candidate.get("preferred_username"),
                candidate.get("name"),
            )
            if username:
                return username
        return None

    def _extract_current_user_context(self, payload: Any) -> CurrentUserContext:
        candidates: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            candidates.append(payload)
            entity = _payload_entity(payload, "user")
            if entity and entity not in candidates:
                candidates.append(entity)
            for key in ("user", "data", "item"):
                value = payload.get(key)
                if isinstance(value, dict) and value not in candidates:
                    candidates.append(value)
        elif isinstance(payload, list):
            candidates.extend(item for item in payload if isinstance(item, dict))

        roles: list[str] = []
        groups: list[str] = []
        for candidate in candidates:
            roles.extend(_claim_text(candidate.get("roles")))
            roles.extend(_claim_text(candidate.get("authorities")))
            roles.extend(_claim_text(candidate.get("roleAssignments")))
            groups.extend(_claim_text(candidate.get("userGroups")))
            groups.extend(_claim_text(candidate.get("usergroups")))
            groups.extend(_claim_text(candidate.get("groups")))

        return CurrentUserContext(
            preferred_username=self._extract_current_username(payload),
            roles=list(dict.fromkeys(roles)),
            groups=list(dict.fromkeys(groups)),
        )

    async def current_user_context(self) -> CurrentUserContext | None:
        raw_result = await self._request_raw_candidates(
            "GET",
            ["/osmc/admin/currentUser?permission=true", *self.current_user_candidates()],
            timeout=10.0,
        )
        if raw_result is None:
            return None
        response, _ = raw_result
        if response.status_code in {401, 403}:
            return None
        return self._extract_current_user_context(self._decode_response(response))

    async def current_username(self) -> str | None:
        context = await self.current_user_context()
        if context is None:
            return None
        return context.preferred_username

    async def health(self) -> dict[str, Any]:
        checks = {"base_url": False}
        version_hint = self.context.server.version.value if self.context.server.version != TWCVersion.AUTO else None
        try:
            async with httpx.AsyncClient(timeout=10.0, verify=self.verify, follow_redirects=True) as client:
                base_response = await client.get(self.context.server.base_url)
                checks["base_url"] = base_response.status_code < 500
                combined_text = base_response.text
                combined_text = combined_text.lower()
                if "2024x" in combined_text:
                    version_hint = "2024x"
                elif "2022x" in combined_text:
                    version_hint = "2022x"
        except httpx.HTTPError:
            return {"status": "unreachable", "checks": checks, "version_hint": version_hint}
        status = "healthy" if all(checks.values()) else "degraded"
        return {"status": status, "checks": checks, "version_hint": version_hint}

    async def detect_version(self) -> str:
        if self._detected_version:
            return self._detected_version
        if self.context.server.version != TWCVersion.AUTO:
            self._detected_version = self.context.server.version.value
            return self._detected_version
        version_payload = await self._request_candidates("GET", self.version_candidates())
        if isinstance(version_payload, dict):
            for key in ("version", "productVersion", "raw"):
                value = str(version_payload.get(key, ""))
                if "2024x" in value:
                    self._detected_version = "2024x"
                    return self._detected_version
                if "2022x" in value:
                    self._detected_version = "2022x"
                    return self._detected_version
        self._detected_version = "2022x"
        return self._detected_version

    async def discover_capabilities(self) -> CapabilitySummary:
        version = await self.detect_version()
        health = await self.health()
        project_payload = await self._request_candidates("GET", self.project_candidates())
        project_accessible = bool(project_payload) and "restricted" not in str(project_payload)

        capabilities = {
            "repository": Capability(
                name="repository",
                state=CapabilityState.READY if project_accessible else CapabilityState.RESTRICTED,
                reason=(
                    "RealSwagger repository resources were accessible with the active TWC session."
                    if project_accessible
                    else "RealSwagger repository resources could not be loaded with the active TWC session."
                ),
                source="probe",
            ),
            "models": Capability(
                name="models",
                state=CapabilityState.READY if project_accessible else CapabilityState.RESTRICTED,
                reason="Model and branch browsing use the RealSwagger resources, branches, models, and elements endpoints.",
                source="verified-contract",
            ),
            "revisiondiff": Capability(
                name="revisiondiff",
                state=CapabilityState.READY if project_accessible else CapabilityState.RESTRICTED,
                reason="Compare supports the RealSwagger resource revisiondiff endpoint when numeric revisions are supplied for the same resource.",
                source="verified-contract",
            ),
            "edit": Capability(
                name="edit",
                state=CapabilityState.READY if project_accessible else CapabilityState.RESTRICTED,
                reason=(
                    "RealSwagger includes element update operations. Saves are still revalidated at runtime against the active TWC session."
                    if project_accessible
                    else "Element update operations exist in RealSwagger, but the active session did not expose enough repository access to confirm write access."
                ),
                source="verified-contract" if project_accessible else "probe",
            ),
            "user_access": Capability(
                name="user_access",
                state=CapabilityState.READY if project_accessible else CapabilityState.RESTRICTED,
                reason=(
                    "Project listing was accessible with the active session."
                    if project_accessible
                    else "Project listing could not be loaded. Access will be inferred from subsequent API responses."
                ),
                source="probe",
            ),
        }
        return CapabilitySummary(
            detected_version=version,
            reachable_endpoints={
                "projects": project_accessible,
                **health.get("checks", {}),
            },
            capabilities=capabilities,
        )

    def _workspace_id_from_payload(self, payload: Any, allow_plain_identifier: bool = False) -> str | None:
        entity = _payload_entity(payload)
        if not entity:
            return None

        for key in ("workspaceId", "workspaceID"):
            value = entity.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        for key in ("@id", "id", "kerml:resource", "resource", "@base"):
            value = entity.get(key)
            if isinstance(value, dict):
                value = value.get("@id") or value.get("id") or value.get("href")
            if not isinstance(value, str):
                continue
            segments = [segment for segment in urlparse(value).path.split("/") if segment]
            if "workspaces" in segments:
                index = segments.index("workspaces")
                if index + 1 < len(segments):
                    return segments[index + 1]
            if allow_plain_identifier and key in {"@id", "id"}:
                identifier = _reference_id(value)
                if identifier:
                    return identifier
        return None

    def branch_candidates(self, project_id: str, branch_id: str, workspace_id: str | None = None) -> list[str]:
        candidates = [f"/osmc/resources/{project_id}/branches/{branch_id}"]
        if workspace_id:
            candidates.insert(0, f"/osmc/workspaces/{workspace_id}/resources/{project_id}/branches/{branch_id}")
        return candidates

    def _extract_display_name(self, payload: dict[str, Any]) -> str:
        entity = _payload_entity(payload) or {}
        esi_data = entity.get("kerml:esiData")
        if isinstance(esi_data, dict):
            return _first_text(
                esi_data.get("name"),
                entity.get("kerml:name"),
                entity.get("dcterms:title"),
                entity.get("name"),
                entity.get("label"),
                entity.get("title"),
            )
        return _first_text(
            entity.get("kerml:name"),
            entity.get("dcterms:title"),
            entity.get("name"),
            entity.get("label"),
            entity.get("title"),
        )

    def _extract_description(self, payload: dict[str, Any]) -> str:
        entity = _payload_entity(payload) or {}
        return _first_text(entity.get("kerml:comment"), entity.get("dcterms:description"), entity.get("description"), entity.get("summary"))

    def _normalize_path_text(self, value: str) -> str:
        normalized = value.strip().replace("\\", "/").replace("::", "/")
        normalized = re.sub(r"/+", "/", normalized)
        return normalized.strip("/")

    def _extract_path_hint(self, payload: dict[str, Any]) -> str:
        entity = _payload_entity(payload) or {}
        esi_data = entity.get("kerml:esiData")
        if isinstance(esi_data, dict):
            path_hint = _first_text(
                esi_data.get("qualifiedName"),
                esi_data.get("qualified_name"),
                esi_data.get("path"),
                esi_data.get("humanName"),
            )
            if path_hint:
                return self._normalize_path_text(path_hint)
        path_hint = _first_text(
            entity.get("qualifiedName"),
            entity.get("qualified_name"),
            entity.get("kerml:qualifiedName"),
            entity.get("path"),
            entity.get("humanName"),
            entity.get("breadcrumbs_path"),
        )
        return self._normalize_path_text(path_hint) if path_hint else ""

    def _item_path(self, project_id: str, branch_id: str, item_name: str, payload: dict[str, Any] | None = None) -> str:
        if payload is not None:
            path_hint = self._extract_path_hint(payload)
            if path_hint:
                return path_hint
        normalized_name = item_name or "Unnamed Item"
        return f"{project_id}/{branch_id}/{normalized_name}"

    def _extract_item_metadata(self, payload: dict[str, Any]) -> dict[str, str]:
        entity = _payload_entity(payload) or {}
        metadata: dict[str, str] = {}
        ignored_keys = {
            "@context",
            "@base",
            "@id",
            "@type",
            "id",
            "ID",
            "name",
            "label",
            "title",
            "dcterms:title",
            "dcterms:description",
            "description",
            "summary",
            "kerml:name",
            "kerml:comment",
            "kerml:owner",
            "kerml:ownedElement",
            "kerml:packagedElement",
            "ldp:contains",
            "ldp:hasMemberRelation",
            "ldp:membershipResource",
            "kerml:esiData",
        }
        for key, value in entity.items():
            if key in ignored_keys or value in (None, "", [], {}):
                continue
            if isinstance(value, bool):
                metadata[key] = "true" if value else "false"
                continue
            if isinstance(value, (int, float)):
                metadata[key] = str(value)
                continue
            if not isinstance(value, str):
                continue
            if _reference_id(value) and _is_uuid_like(_reference_id(value) or ""):
                continue
            metadata[key] = value
        esi_data = entity.get("kerml:esiData")
        if isinstance(esi_data, dict):
            for key, value in esi_data.items():
                if isinstance(value, (str, int, float, bool)):
                    metadata[f"esi.{key}"] = str(value)
        return metadata

    def _reference_values_for_field(self, value: Any) -> list[Any]:
        if isinstance(value, list):
            references: list[Any] = []
            for item in value:
                references.extend(self._reference_values_for_field(item))
            return references
        if isinstance(value, dict):
            contains = value.get("ldp:contains")
            if isinstance(contains, list):
                references: list[Any] = []
                for item in contains:
                    references.extend(self._reference_values_for_field(item))
                if references:
                    return references
            identifier = _reference_id(value)
            if identifier and identifier != "it":
                return [value]
            return []
        if isinstance(value, (str, int)):
            raw_value = str(value).strip()
            identifier = _reference_id(raw_value)
            if identifier and identifier != "it" and (_is_uuid_like(identifier) or raw_value.startswith(("#", "_")) or "/" in raw_value):
                return [value]
        return []

    def _extract_stereotypes(self, payload: dict[str, Any]) -> list[str]:
        entity = _payload_entity(payload) or {}
        stereotypes: list[str] = []
        stereotype_values: list[Any] = []
        for key in ("uml:stereotypeName", "stereotypeName", "stereotypes"):
            stereotype_values.extend(_as_list(entity.get(key)))
        for value in stereotype_values:
            if isinstance(value, dict):
                stereotype_name = _first_text(value.get("uml:stereotypeName"), value.get("name"), value.get("label"))
            else:
                stereotype_name = str(value).strip() if str(value).strip() and not _is_uuid_like(str(value)) else ""
            if stereotype_name and stereotype_name not in stereotypes:
                stereotypes.append(stereotype_name)
        return stereotypes

    async def _batch_resolve_element_entities(
        self,
        project_id: str,
        branch_id: str,
        element_ids: list[str],
        workspace_id: str | None = None,
        *,
        batch_size: int = 200,
    ) -> dict[str, dict[str, Any]]:
        resolved: dict[str, dict[str, Any]] = {}
        pending_ids = list(dict.fromkeys(element_id for element_id in element_ids if element_id))
        if not pending_ids:
            return resolved

        for chunk_start in range(0, len(pending_ids), batch_size):
            chunk = pending_ids[chunk_start : chunk_start + batch_size]
            payload = await self._request_candidates(
                "POST",
                [
                    *((f"/osmc/workspaces/{workspace_id}/resources/{project_id}/branches/{branch_id}/elements",) if workspace_id else ()),
                    f"/osmc/resources/{project_id}/branches/{branch_id}/elements",
                ],
                json_payload=chunk,
                timeout=60.0,
            )
            if not isinstance(payload, dict) or payload.get("restricted"):
                continue
            for element_id, raw_payload in payload.items():
                entity = _payload_entity(raw_payload)
                if isinstance(entity, dict):
                    resolved[element_id] = entity
        return resolved

    def _reference_summary(
        self,
        reference: Any,
        *,
        relationship_type: str,
        project_id: str,
        branch_id: str,
        resolved_entities: dict[str, dict[str, Any]],
        parent_path: str = "",
    ) -> ItemReference | None:
        reference_id = _reference_id(reference)
        if not reference_id or reference_id == "it":
            return None

        local_entity = _payload_entity(reference) if isinstance(reference, (dict, list)) else None
        resolved_entity = resolved_entities.get(reference_id) or (local_entity if isinstance(local_entity, dict) else None)
        if resolved_entity is None and not _is_uuid_like(reference_id):
            return None
        reference_name = self._extract_display_name(resolved_entity) if isinstance(resolved_entity, dict) else ""
        raw_types = _normalize_types(resolved_entity.get("@type")) if isinstance(resolved_entity, dict) else []
        item_type = _humanize_type(raw_types[0]) if raw_types else "item"
        path = self._item_path(project_id, branch_id, reference_name or reference_id, resolved_entity) if isinstance(resolved_entity, dict) else ""
        if not path and parent_path and relationship_type in {"contains", "ownedElement", "packagedElement"}:
            path = f"{parent_path}/{reference_name or reference_id}"
        return ItemReference(
            id=reference_id,
            name=reference_name or reference_id,
            item_type=item_type,
            relationship_type=relationship_type,
            path=path,
        )

    def _dedupe_item_references(self, references: list[ItemReference]) -> list[ItemReference]:
        deduped: list[ItemReference] = []
        seen: set[tuple[str, str]] = set()
        for reference in references:
            key = (reference.id, reference.relationship_type)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(reference)
        return deduped

    async def _extract_item_references(
        self,
        payload: dict[str, Any],
        *,
        project_id: str,
        branch_id: str,
        item_path: str,
    ) -> tuple[ItemReference | None, list[ItemReference], list[ItemReference], list[ItemReference]]:
        entity = _payload_entity(payload) or {}
        containment_keys = {
            "ldp:contains": "contains",
            "kerml:ownedElement": "ownedElement",
            "kerml:packagedElement": "packagedElement",
        }
        type_keys = {
            "kerml:type": "type",
            "type": "type",
            "kerml:classifier": "classifier",
            "classifier": "classifier",
        }
        ignored_keys = {
            "@context",
            "@base",
            "@id",
            "@type",
            "id",
            "ID",
            "name",
            "label",
            "title",
            "dcterms:title",
            "dcterms:description",
            "description",
            "summary",
            "kerml:name",
            "kerml:comment",
            "kerml:esiData",
            "ldp:hasMemberRelation",
            "ldp:membershipResource",
            "createdDate",
            "modifiedDate",
            "creator",
            "author",
            "commitID",
            "branchID",
            "resourceId",
            "resourceID",
            "removed",
            "uml:stereotypeName",
            "uml:stereotypeId",
            "stereotypeName",
            "stereotypes",
        }

        resolution_ids: list[str] = []
        for key, value in entity.items():
            if key in ignored_keys:
                continue
            for reference in self._reference_values_for_field(value):
                reference_id = _reference_id(reference)
                if reference_id and reference_id not in resolution_ids:
                    resolution_ids.append(reference_id)

        resolved_entities = await self._batch_resolve_element_entities(project_id, branch_id, resolution_ids)

        owner: ItemReference | None = None
        for reference in self._reference_values_for_field(entity.get("kerml:owner")):
            owner = self._reference_summary(
                reference,
                relationship_type="owner",
                project_id=project_id,
                branch_id=branch_id,
                resolved_entities=resolved_entities,
            )
            if owner is not None:
                break

        type_references: list[ItemReference] = []
        contained_elements: list[ItemReference] = []
        related_items: list[ItemReference] = []
        for key, value in entity.items():
            if key in ignored_keys or key == "kerml:owner":
                continue
            relationship_type = containment_keys.get(key) or type_keys.get(key) or key.split(":")[-1]
            references = self._reference_values_for_field(value)
            if not references:
                continue
            summaries = [
                summary
                for reference in references
                if (summary := self._reference_summary(
                    reference,
                    relationship_type=relationship_type,
                    project_id=project_id,
                    branch_id=branch_id,
                    resolved_entities=resolved_entities,
                    parent_path=item_path,
                ))
                is not None
            ]
            if key in containment_keys:
                contained_elements.extend(summaries)
            elif key in type_keys:
                type_references.extend(summaries)
            else:
                related_items.extend(summaries)

        return (
            owner,
            self._dedupe_item_references(type_references),
            self._dedupe_item_references(contained_elements),
            self._dedupe_item_references(related_items),
        )

    def _extract_relationships(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        entity = _payload_entity(payload) or {}
        relationships: list[dict[str, Any]] = []
        for key in ("kerml:ownedElement", "kerml:owner"):
            for value in _as_list(entity.get(key)):
                identifier = _reference_id(value)
                if identifier:
                    relationships.append({"type": key.split(":")[-1], "target": identifier})
        return relationships

    def _build_item_markdown(self, name: str, description: str, raw_types: list[str], metadata: dict[str, str]) -> str:
        lines = [f"# {name}"]
        if description:
            lines.extend(["", description])
        if raw_types:
            lines.extend(["", f"Remote types: {', '.join(raw_types)}"])
        if metadata:
            lines.extend(["", "## Remote Metadata"])
            for key, value in sorted(metadata.items()):
                lines.append(f"- {key}: {value}")
        return "\n".join(lines)

    def _overlay_item(self, item: ItemDetails, project_id: str, branch_id: str) -> ItemDetails:
        overlay = self.fallback.items().get(item.id)
        if not overlay or overlay.project_id != project_id or overlay.branch_id != branch_id:
            return item
        return item.model_copy(
            update={
                "name": overlay.name or item.name,
                "description": overlay.description or item.description,
                "documentation_markdown": overlay.documentation_markdown or item.documentation_markdown,
                "metadata": overlay.metadata or item.metadata,
                "relationships": overlay.relationships or item.relationships,
                "raw_types": overlay.raw_types or item.raw_types,
                "stereotypes": overlay.stereotypes or item.stereotypes,
                "owner": overlay.owner or item.owner,
                "type_references": overlay.type_references or item.type_references,
                "contained_elements": overlay.contained_elements or item.contained_elements,
                "related_items": overlay.related_items or item.related_items,
                "version": overlay.version or item.version,
                "attachment_supported": overlay.attachment_supported or item.attachment_supported,
                "collaborators": overlay.collaborators or item.collaborators,
            }
        )

    async def _list_remote_branches(self, resource_id: str, workspace_id: str | None = None) -> list[BranchSummary]:
        candidates = [f"/osmc/resources/{resource_id}/branches"]
        if workspace_id:
            candidates.insert(0, f"/osmc/workspaces/{workspace_id}/resources/{resource_id}/branches")

        payload = await self._request_candidates("GET", candidates)
        if payload is None:
            return []
        branch_ids = _container_member_ids(payload)
        branches: list[BranchSummary] = []
        for branch_id in branch_ids:
            detail = await self._request_candidates("GET", self.branch_candidates(resource_id, branch_id, workspace_id))
            branch_payload = _payload_entity(detail, "branch")
            if branch_payload is not None:
                branches.append(
                    BranchSummary(
                        id=branch_id,
                        name=self._extract_display_name(branch_payload) or branch_id,
                        description=self._extract_description(branch_payload),
                    )
                )
            else:
                branches.append(BranchSummary(id=branch_id, name=branch_id, description=""))
        return branches

    async def _list_remote_projects(self, include_branches: bool = False) -> list[ProjectSummary]:
        self._last_project_list_issue = None
        parsed_projects: dict[str, ProjectSummary] = {}
        total_items_received = 0
        sample_project: dict[str, Any] | None = None
        sample_workspace: Any | None = None
        sample_resolved_resource: dict[str, Any] | None = None

        resolved_resources: list[dict[str, Any]] = []
        seen_resource_ids: set[str] = set()

        def payload_members(payload: Any) -> list[Any]:
            members = extract_resource_list(payload)
            if members is not None:
                return members
            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict):
                return [payload]
            return []

        def append_resource_payload(payload: Any, workspace_id: str | None, fallback_resource_id: str | None = None) -> bool:
            nonlocal sample_resolved_resource
            entity = _payload_entity(payload, "resource") if isinstance(payload, (dict, list)) else None
            if entity is None and isinstance(payload, dict):
                entity = payload
            if not isinstance(entity, dict):
                return False

            resource_id = fallback_resource_id or _resource_id_from_payload(entity) or _reference_id(payload)
            if not resource_id or resource_id in {"it", "resources"} or resource_id in seen_resource_ids:
                return False

            if sample_resolved_resource is None:
                sample_resolved_resource = entity

            resolved_resource = dict(entity)
            resolved_resource["__workspace_id"] = workspace_id
            resolved_resource["__resource_id"] = resource_id
            resolved_resources.append(resolved_resource)
            seen_resource_ids.add(resource_id)
            return True

        workspace_payload, workspace_trace = await self._request_candidates_with_trace(
            "GET",
            ["/osmc/workspaces?includeBody=true"],
        )
        if workspace_payload is None:
            self._last_project_list_issue = f"Workspace listing did not return a usable response ({self._trace_summary(workspace_trace)})"
            logger.warning("twc-project-list-workspaces-failed", server_id=self.context.server.id, trace=workspace_trace)
            workspace_objects: list[Any] = []
        elif isinstance(workspace_payload, dict) and workspace_payload.get("restricted"):
            self._last_project_list_issue = f"Workspace listing returned HTTP {workspace_payload.get('status_code')} for the active Teamwork Cloud session"
            logger.warning("twc-project-list-workspaces-restricted", server_id=self.context.server.id, trace=workspace_trace)
            workspace_objects = []
        else:
            workspace_objects = _workspace_objects(workspace_payload)

        if workspace_objects:
            sample_workspace = workspace_objects[0]

        logger.info(
            "twc-project-list-workspaces-loaded",
            server_id=self.context.server.id,
            workspace_count=len(workspace_objects),
            sample_workspace=sample_workspace,
        )

        if not workspace_objects:
            self._last_project_list_issue = "Workspace listing returned no workspace objects with kerml:resources"
            logger.warning(
                "twc-project-list-workspaces-empty",
                server_id=self.context.server.id,
                response_shape=_payload_shape(workspace_payload) if workspace_payload is not None else None,
                workspace_trace=workspace_trace,
            )

        for workspace in workspace_objects:
            workspace_id = self._workspace_id_from_payload(workspace, allow_plain_identifier=True)
            resource_ids = _workspace_resource_ids(workspace)
            logger.info(
                "twc-project-list-workspace-resources",
                server_id=self.context.server.id,
                selected_workspace_id=workspace_id,
                resource_ref_count=len(resource_ids),
            )

            for resource_id in resource_ids:
                if resource_id in seen_resource_ids:
                    continue

                resource_payload, resource_trace = await self._request_candidates_with_trace(
                    "GET",
                    [
                        *((
                            f"/osmc/workspaces/{workspace_id}/resources/{resource_id}",
                        ) if workspace_id else ()),
                        f"/osmc/resources/{resource_id}",
                    ],
                )
                if resource_payload is None:
                    logger.warning(
                        "twc-project-list-resource-resolve-failed",
                        server_id=self.context.server.id,
                        workspace_id=workspace_id,
                        resource_id=resource_id,
                        trace=resource_trace,
                    )
                    continue
                if isinstance(resource_payload, dict) and resource_payload.get("restricted"):
                    logger.warning(
                        "twc-project-list-resource-resolve-restricted",
                        server_id=self.context.server.id,
                        workspace_id=workspace_id,
                        resource_id=resource_id,
                        trace=resource_trace,
                    )
                    continue

                if not append_resource_payload(resource_payload, workspace_id, resource_id):
                    logger.warning(
                        "twc-project-list-resource-resolve-unusable",
                        server_id=self.context.server.id,
                        workspace_id=workspace_id,
                        resource_id=resource_id,
                        response_shape=_payload_shape(resource_payload),
                    )

            if workspace_id and not resource_ids:
                workspace_resources_payload, workspace_resources_trace = await self._request_candidates_with_trace(
                    "GET",
                    [
                        f"/osmc/workspaces/{workspace_id}/resources?includeBody=true&includeRemovedResource=false",
                        f"/osmc/workspaces/{workspace_id}/resources?includeBody=true",
                        f"/osmc/workspaces/{workspace_id}/resources",
                    ],
                )
                if workspace_resources_payload is None or (
                    isinstance(workspace_resources_payload, dict) and workspace_resources_payload.get("restricted")
                ):
                    logger.warning(
                        "twc-project-list-workspace-resource-list-failed",
                        server_id=self.context.server.id,
                        workspace_id=workspace_id,
                        trace=workspace_resources_trace,
                    )
                    continue
                for resource_item in payload_members(workspace_resources_payload):
                    append_resource_payload(resource_item, workspace_id)

        if not resolved_resources:
            direct_resource_payload, direct_resource_trace = await self._request_candidates_with_trace(
                "GET",
                [
                    "/osmc/resources?includeBody=true&includeRemovedResource=false",
                    "/osmc/resources?includeBody=true",
                    "/osmc/resources",
                ],
            )
            if direct_resource_payload is None:
                self._last_project_list_issue = f"Resource listing did not return a usable response ({self._trace_summary(direct_resource_trace)})"
                logger.warning("twc-project-list-direct-resources-failed", server_id=self.context.server.id, trace=direct_resource_trace)
            elif isinstance(direct_resource_payload, dict) and direct_resource_payload.get("restricted"):
                self._last_project_list_issue = f"Resource listing returned HTTP {direct_resource_payload.get('status_code')} for the active Teamwork Cloud session"
                logger.warning("twc-project-list-direct-resources-restricted", server_id=self.context.server.id, trace=direct_resource_trace)
            else:
                for resource_item in payload_members(direct_resource_payload):
                    append_resource_payload(resource_item, None)

        logger.info(
            "twc-project-list-resolved-resources",
            server_id=self.context.server.id,
            resolved_project_objects=len(resolved_resources),
            sample_resolved_resource=sample_resolved_resource,
        )

        total_items_received = len(resolved_resources)
        mapped_projects = map_projects(resolved_resources)
        if mapped_projects:
            sample_project = mapped_projects[0]

        for project in mapped_projects:
            resource_id = project.get("resource_id")
            if not isinstance(resource_id, str) or resource_id in parsed_projects:
                continue

            workspace_id = project.get("workspace_id") if isinstance(project.get("workspace_id"), str) else None
            branches: list[BranchSummary] = []
            if include_branches:
                branch_uuid = project.get("branch_uuid") if isinstance(project.get("branch_uuid"), str) else None
                if branch_uuid:
                    branches = [BranchSummary(id=branch_uuid, name=branch_uuid, description="")]
                else:
                    branches = await self._list_remote_branches(resource_id, workspace_id)
                    if not branches:
                        logger.warning(
                            "twc-project-list-branches-missing",
                            server_id=self.context.server.id,
                            workspace_id=workspace_id,
                            resource_id=resource_id,
                        )

            parsed_projects[resource_id] = ProjectSummary(
                id=resource_id,
                name=str(project["name"]),
                description=str(project.get("description") or ""),
                branches=branches,
                workspace_id=workspace_id,
                resource_id=resource_id,
                categories=project.get("categories"),
            )

        logger.info(
            "twc-project-list-resource-response",
            server_id=self.context.server.id,
            total_items_received=total_items_received,
            valid_projects_parsed=len(parsed_projects),
            sample_item_shape=_payload_shape(sample_resolved_resource) if sample_resolved_resource is not None else None,
        )

        if not parsed_projects:
            self._last_project_list_issue = "No valid projects resolved from TWC workspace resources"
            logger.error(
                "twc-project-list-parse-failed",
                server_id=self.context.server.id,
                issue=self._last_project_list_issue,
                total_items_received=total_items_received,
                sample_item_shape=_payload_shape(sample_resolved_resource) if sample_resolved_resource is not None else None,
                sample_item=sample_project,
                full_payload_sample=sample_resolved_resource,
                full_payload_sample_json=json.dumps(sample_resolved_resource, indent=2, default=str) if sample_resolved_resource is not None else None,
                workspace_trace=workspace_trace,
            )
            raise RuntimeError(self._last_project_list_issue)

        projects = list(parsed_projects.values())

        logger.info(
            "twc-project-list-remote",
            server_id=self.context.server.id,
            workspace_count=len(workspace_objects),
            total_items_received=total_items_received,
            valid_projects_parsed=len(projects),
            sample_item=sample_project,
        )
        return projects

    async def _resolve_tree_reference_node(
        self,
        *,
        item_id: str,
        fallback_label: str,
        fallback_node_type: str,
        project_id: str,
        branch_id: str,
        model_id: str,
        parent_path: str,
    ) -> TreeNode:
        label = fallback_label or item_id
        node_type = fallback_node_type
        should_resolve = not fallback_label or fallback_label == item_id or _looks_like_identifier(fallback_label)
        if should_resolve:
            remote_payload = await self._remote_item_payload(project_id, branch_id, item_id)
            entity = _payload_entity(remote_payload) if remote_payload is not None else None
            if isinstance(entity, dict):
                resolved_name = self._extract_display_name(entity)
                if resolved_name:
                    label = resolved_name
                raw_types = _normalize_types(entity.get("@type"))
                if raw_types:
                    node_type = _humanize_type(raw_types[0])

        return TreeNode(
            id=item_id,
            label=label or item_id,
            node_type=node_type,
            path=f"{parent_path}/{label or item_id}",
            children=[],
            metadata={
                "project_id": project_id,
                "branch_id": branch_id,
                "model_id": model_id,
            },
        )

    async def _model_tree_node(self, model_id: str, payload: dict[str, Any], project_id: str, branch_id: str) -> TreeNode:
        entity = _payload_entity(payload) or {}
        model_name = self._extract_display_name(entity) or model_id.upper()
        children: list[TreeNode] = []
        model_path = f"{project_id}/{branch_id}/{model_name}"
        roots = _as_list(entity.get("models:roots"))
        for root in roots:
            if not isinstance(root, dict):
                continue
            root_id = _reference_id(root.get("models:root") or root.get("@id"))
            if not root_id:
                continue
            root_name = _first_text(root.get("models:name"), root_id)
            root_type = _humanize_type(str(root.get("@type") or "model_root"))
            children.append(
                await self._resolve_tree_reference_node(
                    item_id=root_id,
                    fallback_label=root_name,
                    fallback_node_type=root_type,
                    project_id=project_id,
                    branch_id=branch_id,
                    model_id=model_id,
                    parent_path=model_path,
                )
            )

        if not children:
            usages = _as_list(entity.get("models:usages"))
            for usage in usages:
                if not isinstance(usage, dict):
                    continue
                project = usage.get("models:project") if isinstance(usage.get("models:project"), dict) else usage
                usage_id = _reference_id(project.get("@id") if isinstance(project, dict) else project)
                usage_name = self._extract_display_name(project) if isinstance(project, dict) else ""
                if not usage_id:
                    continue
                children.append(
                    await self._resolve_tree_reference_node(
                        item_id=usage_id,
                        fallback_label=usage_name or usage_id,
                        fallback_node_type="usage",
                        project_id=project_id,
                        branch_id=branch_id,
                        model_id=model_id,
                        parent_path=model_path,
                    )
                )

        return TreeNode(
            id=model_id,
            label=model_name,
            node_type="model",
            path=model_path,
            children=children,
            metadata={
                "project_id": project_id,
                "branch_id": branch_id,
                "model_id": model_id,
            },
        )

    async def _load_remote_tree(self, project_id: str, branch_id: str) -> list[TreeNode]:
        payload = await self._request_candidates(
            "GET",
            [
                f"/osmc/resources/{project_id}/branches/{branch_id}/models",
                f"/osmc/resources/{project_id}/models",
            ],
        )
        model_ids = _container_member_ids(payload) if payload is not None else []
        nodes: list[TreeNode] = []
        for model_id in model_ids:
            model_payload = await self._request_candidates(
                "GET",
                [
                    f"/osmc/resources/{project_id}/branches/{branch_id}/models/{model_id}",
                    f"/osmc/resources/{project_id}/models/{model_id}",
                ],
            )
            if _payload_entity(model_payload) is not None:
                nodes.append(await self._model_tree_node(model_id, model_payload, project_id, branch_id))
        return nodes

    async def _element_seed_ids(
        self,
        project_id: str,
        branch_id: str,
        workspace_id: str | None = None,
    ) -> tuple[list[str], str, list[str]]:
        warnings: list[str] = [
            "RealSwagger.json does not declare GET /osmc/workspaces/{workspaceId}/resources/{resourceId}/branches/{branchId}/elements, so discovery starts from Swagger-declared model roots and then traverses GET /elements/{elementId} recursively."
        ]
        model_payload = await self._request_candidates_paged(
            "GET",
            [
                *((f"/osmc/workspaces/{workspace_id}/resources/{project_id}/branches/{branch_id}/models",) if workspace_id else ()),
                f"/osmc/resources/{project_id}/branches/{branch_id}/models",
                f"/osmc/resources/{project_id}/models",
            ],
            timeout=30.0,
        )
        if model_payload is None:
            warnings.append("Model discovery returned no response.")
            return [], "model-roots", warnings
        if isinstance(model_payload, dict) and model_payload.get("restricted"):
            warnings.append("Model discovery is restricted for the current Teamwork Cloud session.")
            return [], "model-roots", warnings

        model_ids = _container_member_ids(model_payload)
        if not model_ids:
            warnings.append("No model IDs were returned for the selected project and branch.")
            return [], "model-roots", warnings

        seed_ids: list[str] = []
        for model_id in model_ids:
            model_detail = await self._request_candidates_paged(
                "GET",
                [
                    *((f"/osmc/workspaces/{workspace_id}/resources/{project_id}/branches/{branch_id}/models/{model_id}",) if workspace_id else ()),
                    f"/osmc/resources/{project_id}/branches/{branch_id}/models/{model_id}",
                    f"/osmc/resources/{project_id}/models/{model_id}",
                ],
                timeout=30.0,
            )
            entity = _payload_entity(model_detail) if model_detail is not None else None
            if not isinstance(entity, dict):
                continue
            for root in _as_list(entity.get("models:roots")):
                if not isinstance(root, dict):
                    continue
                root_id = _reference_id(root.get("models:root") or root.get("@id"))
                if root_id and root_id not in seed_ids:
                    seed_ids.append(root_id)

        if not seed_ids:
            warnings.append("No model roots were available to seed element traversal.")
        seed_source = "workspace-model-roots" if workspace_id else "resource-model-roots"
        return seed_ids, seed_source, warnings

    async def discover_elements(
        self,
        project_id: str,
        branch_id: str,
        workspace_id: str | None = None,
        *,
        batch_size: int = 200,
    ) -> ElementDiscoveryResult:
        seed_ids, seed_source, warnings = await self._element_seed_ids(project_id, branch_id, workspace_id)
        seed_ids = list(dict.fromkeys(seed_ids))
        if ELEMENT_DISCOVERY_THROTTLE_EVERY > 0 and ELEMENT_DISCOVERY_THROTTLE_SECONDS > 0:
            warnings.append(
                f"Element discovery pauses for {ELEMENT_DISCOVERY_THROTTLE_SECONDS:g} seconds after every {ELEMENT_DISCOVERY_THROTTLE_EVERY} traversed elements to reduce upstream load."
            )
        if not seed_ids:
            return ElementDiscoveryResult(
                project_id=project_id,
                branch_id=branch_id,
                workspace_id=workspace_id,
                seed_source=seed_source,
                seed_ids=[],
                ids=[],
                entries=[],
                total_ids=0,
                traversed_elements=0,
                hydrated_elements=0,
                batch_count=0,
                batch_size=batch_size,
                warnings=warnings,
            )

        queue: asyncio.Queue[str | None] = asyncio.Queue()
        for seed_id in seed_ids:
            queue.put_nowait(seed_id)

        discovered_ids = list(seed_ids)
        enqueued_ids = set(seed_ids)
        visited_ids: set[str] = set()
        payloads_by_id: dict[str, Any] = {}
        warnings_lock = asyncio.Lock()
        throttle_lock = asyncio.Lock()
        traversed_count = 0
        pause_until = 0.0

        async def append_warning(message: str) -> None:
            async with warnings_lock:
                if len(warnings) < 50:
                    warnings.append(message)

        async def wait_for_throttle_window() -> None:
            if ELEMENT_DISCOVERY_THROTTLE_EVERY <= 0 or ELEMENT_DISCOVERY_THROTTLE_SECONDS <= 0:
                return
            while True:
                async with throttle_lock:
                    remaining = pause_until - asyncio.get_running_loop().time()
                if remaining <= 0:
                    return
                await asyncio.sleep(remaining)

        async def mark_traversal_progress() -> None:
            nonlocal traversed_count, pause_until
            if ELEMENT_DISCOVERY_THROTTLE_EVERY <= 0 or ELEMENT_DISCOVERY_THROTTLE_SECONDS <= 0:
                return
            async with throttle_lock:
                traversed_count += 1
                if traversed_count % ELEMENT_DISCOVERY_THROTTLE_EVERY == 0:
                    pause_until = max(pause_until, asyncio.get_running_loop().time()) + ELEMENT_DISCOVERY_THROTTLE_SECONDS

        async def fetch_element_payload(element_id: str) -> Any:
            payload = await self._request_candidates_paged(
                "GET",
                [
                    *((f"/osmc/workspaces/{workspace_id}/resources/{project_id}/branches/{branch_id}/elements/{element_id}",) if workspace_id else ()),
                    f"/osmc/resources/{project_id}/branches/{branch_id}/elements/{element_id}",
                ],
                timeout=30.0,
            )
            if isinstance(payload, dict) and payload.get("restricted"):
                raise PermissionError(f"Access to element {element_id} is restricted for the current Teamwork Cloud session.")
            if payload is None:
                raise RuntimeError(f"No response was returned for element {element_id}.")
            return payload

        async def worker() -> None:
            while True:
                element_id = await queue.get()
                if element_id is None:
                    queue.task_done()
                    return
                try:
                    if element_id in visited_ids:
                        continue
                    await wait_for_throttle_window()
                    payload = await fetch_element_payload(element_id)
                    await mark_traversal_progress()
                    payloads_by_id[element_id] = payload
                    visited_ids.add(element_id)
                    for child_id in _element_containment_ids(payload):
                        if child_id in enqueued_ids:
                            continue
                        enqueued_ids.add(child_id)
                        discovered_ids.append(child_id)
                        queue.put_nowait(child_id)
                except PermissionError as exc:
                    await append_warning(str(exc))
                except RuntimeError as exc:
                    await append_warning(str(exc))
                finally:
                    queue.task_done()

        worker_count = min(ELEMENT_DISCOVERY_MAX_WORKERS, max(1, len(seed_ids)))
        workers = [asyncio.create_task(worker()) for _ in range(worker_count)]
        await queue.join()
        for _ in workers:
            queue.put_nowait(None)
        await asyncio.gather(*workers)

        batch_count = 0
        hydrated_ids: set[str] = set()
        for chunk_start in range(0, len(discovered_ids), batch_size):
            chunk = discovered_ids[chunk_start : chunk_start + batch_size]
            batch_payload = await self._request_candidates(
                "POST",
                [
                    *((f"/osmc/workspaces/{workspace_id}/resources/{project_id}/branches/{branch_id}/elements",) if workspace_id else ()),
                    f"/osmc/resources/{project_id}/branches/{branch_id}/elements",
                ],
                json_payload=chunk,
                timeout=60.0,
            )
            if batch_payload is None:
                await append_warning(f"Element batch request returned no response for chunk starting at {chunk_start + 1}.")
                continue
            if isinstance(batch_payload, dict) and batch_payload.get("restricted"):
                await append_warning("Element batch retrieval is restricted for the current Teamwork Cloud session.")
                continue
            if not isinstance(batch_payload, dict):
                await append_warning(f"Unexpected element batch payload type: {type(batch_payload).__name__}.")
                continue

            batch_count += 1
            for element_id, raw_payload in batch_payload.items():
                entity = _payload_entity(raw_payload)
                if entity is None:
                    continue
                payloads_by_id[element_id] = raw_payload
                hydrated_ids.add(element_id)

        entries: list[ElementDiscoveryEntry] = []
        for element_id in discovered_ids:
            payload = payloads_by_id.get(element_id)
            entity = _payload_entity(payload) if payload is not None else None
            raw_types = _normalize_types(entity.get("@type")) if isinstance(entity, dict) else []
            entries.append(
                ElementDiscoveryEntry(
                    id=element_id,
                    name=self._extract_display_name(payload) if payload is not None else element_id,
                    item_type=_humanize_type(raw_types[0]) if raw_types else "element",
                    child_count=len(_element_containment_ids(payload)) if payload is not None else 0,
                )
            )

        return ElementDiscoveryResult(
            project_id=project_id,
            branch_id=branch_id,
            workspace_id=workspace_id,
            seed_source=seed_source,
            seed_ids=seed_ids,
            ids=discovered_ids,
            entries=entries,
            total_ids=len(discovered_ids),
            traversed_elements=len(visited_ids),
            hydrated_elements=len(hydrated_ids),
            batch_count=batch_count,
            batch_size=batch_size,
            warnings=warnings,
        )

    async def _remote_item_payload(self, project_id: str, branch_id: str, item_id: str) -> Any | None:
        payload = await self._request_candidates(
            "GET",
            [
                f"/osmc/resources/{project_id}/branches/{branch_id}/elements/{item_id}",
                f"/osmc/resources/{project_id}/branches/{branch_id}/models/{item_id}",
                f"/osmc/resources/{project_id}/elements/{item_id}",
            ],
        )
        return payload

    async def _remote_item_details(self, payload: dict[str, Any], item_id: str, project_id: str, branch_id: str) -> ItemDetails:
        entity = _payload_entity(payload) or {}
        raw_types = _normalize_types(entity.get("@type"))
        metadata = self._extract_item_metadata(entity)
        name = self._extract_display_name(entity) or item_id
        description = self._extract_description(entity)
        item_type = _humanize_type(raw_types[0]) if raw_types else "item"
        item_path = self._item_path(project_id, branch_id, name, entity)
        owner, type_references, contained_elements, related_items = await self._extract_item_references(
            entity,
            project_id=project_id,
            branch_id=branch_id,
            item_path=item_path,
        )
        relationships = [
            {
                "type": reference.relationship_type,
                "target": reference.id,
                "target_name": reference.name,
                "item_type": reference.item_type,
                "path": reference.path,
            }
            for reference in [*contained_elements, *type_references, *related_items, *([owner] if owner else [])]
        ]
        item = ItemDetails(
            id=item_id,
            name=name,
            item_type=item_type,
            path=item_path,
            project_id=project_id,
            branch_id=branch_id,
            description=description,
            documentation_markdown=self._build_item_markdown(name, description, raw_types, metadata),
            raw_types=raw_types,
            stereotypes=self._extract_stereotypes(entity),
            owner=owner,
            type_references=type_references,
            contained_elements=contained_elements,
            related_items=related_items,
            metadata=metadata,
            relationships=relationships or self._extract_relationships(entity),
            version=metadata.get("modifiedDate") or metadata.get("commitID") or "remote",
            editable=True,
            attachment_supported=False,
            collaborators=[],
            source_payload=entity,
        )
        return item

    def _document_versions(self, payload: dict[str, Any], fallback_versions: list[DocumentVersion] | None = None) -> list[DocumentVersion]:
        versions: list[DocumentVersion] = []
        for index, version in enumerate(_as_list(payload.get("versions") or payload.get("history") or payload.get("revisions")), start=1):
            if not isinstance(version, dict):
                versions.append(DocumentVersion(id=uuid4().hex, label=str(version), created_at=utcnow(), summary=""))
                continue
            versions.append(
                DocumentVersion(
                    id=str(version.get("id") or version.get("versionId") or uuid4().hex),
                    label=str(version.get("label") or version.get("name") or version.get("version") or index),
                    created_at=version.get("created_at") or version.get("createdAt") or version.get("timestamp") or utcnow(),
                    summary=str(version.get("summary") or version.get("description") or ""),
                )
            )
        return versions or list(fallback_versions or [])

    def _document_from_payload(self, payload: Any, fallback_document: CollaboratorDocument | None = None) -> CollaboratorDocument | None:
        entity = _payload_entity(payload, "document")
        if entity is None:
            return None
        fallback_title = fallback_document.title if fallback_document else ""
        fallback_body = fallback_document.body_markdown if fallback_document else ""
        fallback_item_id = fallback_document.item_id if fallback_document else ""
        fallback_project_id = fallback_document.project_id if fallback_document else "unknown"
        fallback_branch_id = fallback_document.branch_id if fallback_document else "main"
        body_markdown = _first_text(
            entity.get("body_markdown"),
            entity.get("bodyMarkdown"),
            entity.get("markdown"),
            entity.get("content"),
            entity.get("body"),
            fallback_body,
        )
        breadcrumbs = [str(item) for item in _as_list(entity.get("breadcrumbs")) if str(item).strip()]
        path_text = _first_text(entity.get("path"), entity.get("breadcrumbs_path"))
        if not breadcrumbs and path_text:
            breadcrumbs = [segment for segment in path_text.split("/") if segment]
        toc = [str(item) for item in _as_list(entity.get("toc")) if str(item).strip()]
        if not toc and body_markdown:
            toc = [line[3:].strip() for line in body_markdown.splitlines() if line.startswith("## ")]
        return CollaboratorDocument(
            id=str(entity.get("id") or entity.get("document_id") or entity.get("documentId") or (fallback_document.id if fallback_document else uuid4().hex)),
            title=_first_text(entity.get("title"), entity.get("name"), entity.get("label"), fallback_title) or "Collaborator Document",
            item_id=str(entity.get("item_id") or entity.get("itemId") or entity.get("relatedItemId") or fallback_item_id),
            project_id=str(entity.get("project_id") or entity.get("projectId") or fallback_project_id),
            branch_id=str(entity.get("branch_id") or entity.get("branchId") or fallback_branch_id),
            body_markdown=body_markdown,
            breadcrumbs=breadcrumbs or list(fallback_document.breadcrumbs if fallback_document else []),
            toc=toc or list(fallback_document.toc if fallback_document else []),
            editable=bool(entity.get("editable", True if fallback_document is None else fallback_document.editable)),
            attachments_supported=bool(
                entity.get(
                    "attachments_supported",
                    entity.get("attachment_supported", True if fallback_document is None else fallback_document.attachments_supported),
                )
            ),
            versions=self._document_versions(entity, fallback_document.versions if fallback_document else None),
        )

    def _documents_from_payload(self, payload: Any) -> list[CollaboratorDocument]:
        items = _payload_list(payload, "documents", "items", "data")
        if items is None:
            entity = _payload_entity(payload, "document")
            items = [entity] if entity is not None else []
        documents: list[CollaboratorDocument] = []
        for item in items:
            document = self._document_from_payload(item)
            if document is not None:
                documents.append(document)
        return documents

    def _attachment_from_payload(
        self,
        payload: Any,
        document_id: str,
        *,
        fallback_name: str | None = None,
        fallback_size: int | None = None,
        source: str = "remote",
    ) -> AttachmentInfo | None:
        entity = _payload_entity(payload)
        if entity is None:
            return None
        raw_size = entity.get("size_bytes") or entity.get("sizeBytes") or entity.get("size") or fallback_size or 0
        try:
            size_bytes = int(raw_size)
        except (TypeError, ValueError):
            size_bytes = fallback_size or 0
        file_name = _first_text(entity.get("file_name"), entity.get("fileName"), entity.get("name"), fallback_name) or str(entity.get("id") or uuid4().hex)
        content_type = _first_text(entity.get("content_type"), entity.get("contentType"), entity.get("mime_type"), entity.get("mimeType"))
        if not content_type:
            content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        return AttachmentInfo(
            id=str(entity.get("id") or entity.get("attachmentId") or uuid4().hex),
            document_id=document_id,
            file_name=file_name,
            content_type=content_type,
            size_bytes=size_bytes,
            uploaded_at=entity.get("uploaded_at") or entity.get("uploadedAt") or entity.get("created_at") or utcnow(),
            source=str(entity.get("source") or source),
        )

    def _attachments_from_payload(self, payload: Any, document_id: str) -> list[AttachmentInfo]:
        items = _payload_list(payload, "attachments", "items", "data")
        if items is None:
            entity = _payload_entity(payload)
            items = [entity] if entity and any(key in entity for key in ("file_name", "fileName", "content_type", "contentType", "size", "size_bytes")) else []
        attachments: list[AttachmentInfo] = []
        for item in items:
            attachment = self._attachment_from_payload(item, document_id)
            if attachment is not None:
                attachments.append(attachment)
        return attachments

    def _comment_from_payload(self, payload: Any, document_id: str) -> CommentEntry | None:
        entity = _payload_entity(payload)
        if entity is None:
            return None
        return CommentEntry(
            id=str(entity.get("id") or entity.get("commentId") or uuid4().hex),
            document_id=document_id,
            author=_first_text(entity.get("author"), entity.get("createdBy"), entity.get("user"), entity.get("username")) or "unknown",
            content=_first_text(entity.get("content"), entity.get("body"), entity.get("markdown"), entity.get("text")),
            created_at=entity.get("created_at") or entity.get("createdAt") or entity.get("timestamp") or utcnow(),
        )

    def _comments_from_payload(self, payload: Any, document_id: str) -> list[CommentEntry]:
        items = _payload_list(payload, "comments", "items", "data")
        if items is None:
            entity = _payload_entity(payload)
            items = [entity] if entity and any(key in entity for key in ("author", "content", "body", "text")) else []
        comments: list[CommentEntry] = []
        for item in items:
            comment = self._comment_from_payload(item, document_id)
            if comment is not None:
                comments.append(comment)
        return comments

    def _attachment_cache_dir(self, document_id: str) -> Path:
        path = self.context.storage_dir / "attachment-cache" / self.context.server.id / document_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _attachment_cache_path(self, document_id: str, attachment_id: str, file_name: str) -> Path:
        safe_name = Path(file_name).name or attachment_id
        return self._attachment_cache_dir(document_id) / f"{attachment_id}-{safe_name}"

    def _clear_attachment_cache(self, document_id: str, attachment_id: str) -> None:
        cache_dir = self._attachment_cache_dir(document_id)
        for path in cache_dir.glob(f"{attachment_id}-*"):
            if path.exists():
                path.unlink()

    async def update_branch(self, project_id: str, branch_id: str, payload: dict[str, Any]) -> BranchSummary:
        version = await self.detect_version()
        if version != "2024x":
            raise PermissionError("Branch rename and metadata updates are not supported in the 2022x deployment profile.")

        current_payload = await self._request_candidates("GET", self.branch_candidates(project_id, branch_id))
        entity = _payload_entity(current_payload, "branch")
        if entity is None:
            branch = self.fallback.update_branch(project_id, branch_id, payload.get("name"), payload.get("description"))
            if branch is not None:
                return branch
            raise KeyError(branch_id)

        workspace_id = self._workspace_id_from_payload(entity)
        candidates = self.branch_candidates(project_id, branch_id, workspace_id)
        next_name = _first_text(payload.get("name"), self._extract_display_name(entity), branch_id)
        next_description = payload.get("description") if "description" in payload else self._extract_description(entity)

        update_payload = {
            key: value
            for key, value in entity.items()
            if key in {"ID", "@id", "@type", "author", "resourceID", "startRevision", "latestRevision"} and value not in (None, "")
        }
        update_payload.update(
            {
                "dcterms:title": next_name,
                "name": next_name,
                "title": next_name,
            }
        )
        if next_description is not None:
            update_payload["dcterms:description"] = next_description
            update_payload["description"] = next_description

        last_status: int | None = None
        for content_type in ("application/json", "application/ld+json"):
            raw_result = await self._request_raw_candidates(
                "PATCH",
                candidates,
                content_payload=json.dumps(update_payload),
                extra_headers={"Content-Type": content_type},
            )
            if raw_result is None:
                continue
            response, _ = raw_result
            last_status = response.status_code
            if response.status_code in {401, 403}:
                raise PermissionError("The active session is not allowed to update branch metadata.")
            if 200 <= response.status_code < 300:
                refreshed_payload = await self._request_candidates("GET", candidates)
                refreshed = _payload_entity(refreshed_payload, "branch") or entity
                branch = BranchSummary(
                    id=branch_id,
                    name=self._extract_display_name(refreshed) or next_name,
                    description=self._extract_description(refreshed) or str(next_description or ""),
                )
                self.fallback.update_branch(project_id, branch_id, branch.name, branch.description)
                return branch

        if last_status == 404:
            raise KeyError(branch_id)
        if last_status == 422:
            raise PermissionError("The remote server rejected the branch update payload.")
        raise PermissionError("Remote Teamwork Cloud branch update could not be confirmed for this branch.")

    async def _update_remote_item(
        self,
        item_id: str,
        payload: dict[str, Any],
        project_id: str,
        branch_id: str,
    ) -> ItemDetails | None:
        remote_payload = await self._remote_item_payload(project_id, branch_id, item_id)
        if not remote_payload:
            return None

        remote_entity = _payload_entity(remote_payload)
        if not isinstance(remote_entity, dict):
            return None

        updated_payload = json.loads(json.dumps(remote_entity))
        esi_data = updated_payload.setdefault("kerml:esiData", {})
        if not isinstance(esi_data, dict):
            esi_data = {}
            updated_payload["kerml:esiData"] = esi_data

        remote_fields_changed = False
        if "name" in payload and payload.get("name"):
            remote_fields_changed = True
            esi_data["name"] = payload["name"]
            updated_payload["kerml:name"] = payload["name"]
            updated_payload["dcterms:title"] = payload["name"]
        if "description" in payload:
            remote_fields_changed = True
            updated_payload["kerml:comment"] = payload.get("description") or ""
            updated_payload["dcterms:description"] = payload.get("description") or ""

        response_payload: dict[str, Any] | None = remote_payload
        if remote_fields_changed:
            response_payload = None
            for method in ("PATCH", "PUT"):
                candidate_payload = await self._request_candidates(
                    method,
                    [f"/osmc/resources/{project_id}/branches/{branch_id}/elements/{item_id}"],
                    json_payload=updated_payload,
                )
                if isinstance(candidate_payload, dict) and "restricted" not in candidate_payload:
                    response_payload = candidate_payload if candidate_payload.get("@type") else await self._remote_item_payload(project_id, branch_id, item_id)
                    if response_payload:
                        break
            if not response_payload:
                raise PermissionError("Remote Teamwork Cloud item update could not be confirmed for this element.")

        return await self._remote_item_details(response_payload or remote_payload, item_id, project_id, branch_id)

    async def list_projects(self, include_branches: bool = False) -> list[ProjectSummary]:
        try:
            remote_projects = await self._list_remote_projects(include_branches=include_branches)
            logger.info("Fetched projects from TWC", server_id=self.context.server.id, fetched_count=len(remote_projects))
            return remote_projects
        except RuntimeError:
            raise
        except Exception as exc:
            logger.exception("TWC project fetch failed", server_id=self.context.server.id)
            raise RuntimeError("Failed to load projects from TWC") from exc

    async def list_project_branches(self, project_id: str, workspace_id: str | None = None) -> list[BranchSummary]:
        try:
            branches = await self._list_remote_branches(project_id, workspace_id)
            logger.info(
                "Fetched project branches from TWC",
                server_id=self.context.server.id,
                project_id=project_id,
                workspace_id=workspace_id,
                fetched_count=len(branches),
            )
            return branches
        except RuntimeError:
            raise
        except Exception as exc:
            logger.exception(
                "TWC branch fetch failed",
                server_id=self.context.server.id,
                project_id=project_id,
                workspace_id=workspace_id,
            )
            raise RuntimeError("Failed to load project branches from TWC") from exc

    async def get_model_tree(self, project_id: str | None = None, branch_id: str | None = None) -> list[TreeNode]:
        if project_id and branch_id:
            remote_nodes = await self._load_remote_tree(project_id, branch_id)
            if remote_nodes:
                return remote_nodes

        payload = await self._request_candidates("GET", self.tree_candidates(project_id, branch_id))
        if isinstance(payload, dict):
            items = _first_list(payload, "tree", "items", "data")
            if items:
                return [TreeNode.model_validate(item) for item in items]
        return []

    async def get_item(self, item_id: str, project_id: str | None = None, branch_id: str | None = None) -> ItemDetails:
        if project_id and branch_id:
            remote_payload = await self._remote_item_payload(project_id, branch_id, item_id)
            if _payload_entity(remote_payload) is not None:
                return await self._remote_item_details(remote_payload, item_id, project_id, branch_id)

        payload = await self._request_candidates("GET", self.item_candidates(item_id))
        if isinstance(payload, dict) and payload.get("id"):
            try:
                return ItemDetails.model_validate(payload)
            except Exception:
                pass
        raise KeyError(item_id)

    async def update_item(
        self,
        item_id: str,
        payload: dict[str, Any],
        project_id: str | None = None,
        branch_id: str | None = None,
    ) -> ItemDetails:
        if project_id and branch_id:
            remote_item = await self._update_remote_item(item_id, payload, project_id, branch_id)
            if remote_item is not None:
                return remote_item

        raise KeyError(item_id)

    async def search(self, query: str) -> SearchResponse:
        payload = await self._request_candidates("GET", self.search_candidates(query))
        items = _payload_list(payload, "results", "items", "data") if payload is not None else None
        if items is not None:
            results: list[SearchResult] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                raw_type = str(item.get("type") or item.get("item_type") or item.get("kind") or "model")
                lowered_type = raw_type.lower()
                target_tab = "collaborator" if any(marker in lowered_type for marker in ("document", "collaborator")) else "details"
                result_id = str(item.get("id") or item.get("document_id") or item.get("documentId") or uuid4().hex)
                results.append(
                    SearchResult(
                        id=result_id,
                        title=str(item.get("title") or item.get("name") or "Untitled"),
                        item_type=raw_type,
                        path=str(item.get("path") or item.get("breadcrumbs_path") or ""),
                        excerpt=str(item.get("excerpt") or item.get("description") or item.get("summary") or ""),
                        score=float(item.get("score") or 0.5),
                        project_id=_first_text(item.get("project_id"), item.get("projectId"), item.get("projectID")) or None,
                        branch_id=_first_text(item.get("branch_id"), item.get("branchId"), item.get("branchID")) or None,
                        document_id=(str(item.get("document_id") or item.get("documentId") or result_id) if target_tab == "collaborator" else None),
                        target_tab=target_tab,
                    )
                )
            return SearchResponse(query=query, total=len(results), results=results)

        # RealSwagger does not define a repository/model search endpoint for this app,
        # so we do not synthesize search results from tree scans or local fallbacks.
        return SearchResponse(query=query, total=0, results=[])

    async def list_simulation_configs(self, project_id: str | None = None) -> list[SimulationConfig]:
        payload = await self._request_candidates("GET", self.simulation_candidates(project_id))
        if isinstance(payload, dict) and payload.get("restricted"):
            payload = None
        if payload is not None:
            items = _payload_list(payload, "configurations", "items", "data")
            if items is None:
                entity = _payload_entity(payload)
                items = [entity] if entity is not None else []
            if items is not None:
                configs = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    parameters = [
                        SimulationParameter(
                            name=str(param.get("name")),
                            label=str(param.get("label") or param.get("name")),
                            kind=str(param.get("kind") or param.get("type") or "string"),
                            required=bool(param.get("required", False)),
                            default_value=param.get("defaultValue"),
                            options=[str(choice) for choice in param.get("options", [])],
                        )
                        for param in item.get("editable_parameters", item.get("parameters", []))
                    ]
                    configs.append(
                        SimulationConfig(
                            id=str(item.get("id") or uuid4().hex),
                            name=str(item.get("name") or "Simulation"),
                            description=str(item.get("description") or ""),
                            project_id=str(item.get("project_id") or project_id or "unknown"),
                            editable_parameters=parameters,
                            supports_cancel=True,
                        )
                    )
                if configs:
                    return configs

        return [
            SimulationConfig(
                id="dispatch-balance",
                name="Dispatch Balance Study",
                description="Evaluate redundant channel dispatch margin across gain and damping sweeps.",
                project_id=project_id or "aircraft-systems",
                editable_parameters=[
                    SimulationParameter(name="duration_hours", label="Duration (hours)", kind="integer", required=True, default_value=24),
                    SimulationParameter(name="disturbance_level", label="Disturbance Level", kind="choice", required=True, default_value="medium", options=["low", "medium", "high"]),
                    SimulationParameter(name="gain_scalar", label="Gain Scalar", kind="number", required=True, default_value=1.0),
                    SimulationParameter(name="export_trace", label="Export Detailed Trace", kind="boolean", default_value=True),
                ],
            ),
            SimulationConfig(
                id="control-law-stress",
                name="Control Law Stress Envelope",
                description="Stress branch-level control law assumptions against envelope and workload constraints.",
                project_id=project_id or "aircraft-systems",
                editable_parameters=[
                    SimulationParameter(name="scenario", label="Scenario", kind="choice", required=True, default_value="crosswind", options=["crosswind", "engine_out", "turbulence"]),
                    SimulationParameter(name="iterations", label="Iterations", kind="integer", required=True, default_value=12),
                ],
            ),
        ]

    async def run_simulation(
        self,
        request: SimulationRunRequest,
        report: ProgressReporter,
        cancel_requested: CancelChecker,
    ) -> dict[str, Any]:
        remote_payload = await self._request_candidates("POST", self.simulation_run_candidates(), json_payload=request.model_dump())
        if isinstance(remote_payload, dict) and "restricted" not in remote_payload:
            return {"mode": "remote", "remote_response": remote_payload}

        steps = [
            (10, "Validating simulation parameters"),
            (25, "Preparing model execution context"),
            (45, "Executing scenario sweeps"),
            (70, "Collecting metrics and live traces"),
            (90, "Rendering publishable result package"),
            (100, "Simulation complete"),
        ]
        for progress, message in steps:
            if cancel_requested():
                return {"mode": "fallback", "cancelled": True}
            await report(progress, message)
            await asyncio.sleep(0.8)

        parameters = request.parameters
        gain = float(parameters.get("gain_scalar", 1.0))
        disturbance = str(parameters.get("disturbance_level", "medium"))
        disturbance_factor = {"low": 0.94, "medium": 0.88, "high": 0.79}.get(disturbance, 0.88)
        stability_margin = round(1.37 * gain * disturbance_factor, 3)
        workload_index = round(0.64 / max(gain, 0.2) + (0.22 if disturbance == "high" else 0.08), 3)
        return {
            "mode": "fallback",
            "config_id": request.config_id,
            "parameters": request.parameters,
            "metrics": {
                "stability_margin": stability_margin,
                "workload_index": workload_index,
                "trace_samples": 480,
            },
            "summary": "Local fallback execution completed because a remote Teamwork Cloud simulation endpoint was not detected.",
        }

    async def list_documents(self) -> list[CollaboratorDocument]:
        payload = await self._request_candidates("GET", self.document_candidates())
        if isinstance(payload, dict) and payload.get("restricted"):
            return self.fallback.documents()
        if payload is not None:
            documents = self._documents_from_payload(payload)
            if documents or isinstance(payload, (dict, list)):
                return documents
        return self.fallback.documents()

    async def get_document(self, document_id: str) -> CollaboratorDocument:
        payload = await self._request_candidates("GET", self.document_item_candidates(document_id))
        if not (isinstance(payload, dict) and payload.get("restricted")):
            document = self._document_from_payload(payload)
            if document is not None:
                return document
        for document in self.fallback.documents():
            if document.id == document_id:
                return document
        raise KeyError(document_id)

    async def update_document(self, document_id: str, body_markdown: str) -> CollaboratorDocument:
        payload_variants = [
            {"body_markdown": body_markdown},
            {"bodyMarkdown": body_markdown},
            {"markdown": body_markdown},
            {"content": body_markdown},
            {"body": body_markdown},
        ]
        for method in ("PUT", "PATCH"):
            for candidate_payload in payload_variants:
                raw_result = await self._request_raw_candidates(method, self.document_item_candidates(document_id), json_payload=candidate_payload)
                if raw_result is None:
                    continue
                response, _ = raw_result
                if response.status_code in {401, 403}:
                    break
                if 200 <= response.status_code < 300:
                    refreshed_payload = await self._request_candidates("GET", self.document_item_candidates(document_id))
                    document = self._document_from_payload(refreshed_payload)
                    if document is not None:
                        return document
        document = await self.get_document(document_id)
        document.body_markdown = body_markdown
        document.versions = [
            DocumentVersion(id=uuid4().hex, label=f"{len(document.versions) + 1}.0", created_at=utcnow(), summary="Saved from workbench"),
            *document.versions,
        ]
        return self.fallback.save_document(document)

    async def list_attachments(self, document_id: str) -> list[AttachmentInfo]:
        payload = await self._request_candidates("GET", self.attachment_candidates(document_id))
        if isinstance(payload, dict) and payload.get("restricted"):
            return self.fallback.attachments(document_id)
        if payload is not None:
            attachments = self._attachments_from_payload(payload, document_id)
            if attachments or isinstance(payload, (dict, list)):
                return attachments
        return self.fallback.attachments(document_id)

    async def upload_attachment(self, document_id: str, file_name: str, content_type: str, content: bytes) -> AttachmentInfo:
        raw_result = await self._request_raw_candidates(
            "POST",
            self.attachment_candidates(document_id),
            files={"file": (file_name, content, content_type)},
        )
        if raw_result is not None:
            response, _ = raw_result
            if response.status_code not in {401, 403}:
                payload = self._decode_response(response)
                attachment = self._attachment_from_payload(payload, document_id, fallback_name=file_name, fallback_size=len(content))
                if attachment is not None:
                    return attachment
                refreshed = await self.list_attachments(document_id)
                for attachment in reversed(refreshed):
                    if attachment.file_name == file_name:
                        return attachment
        return self.fallback.add_attachment(document_id, file_name, content_type, content)

    async def delete_attachment(self, document_id: str, attachment_id: str) -> bool:
        raw_result = await self._request_raw_candidates("DELETE", self.attachment_item_candidates(document_id, attachment_id))
        if raw_result is not None:
            response, _ = raw_result
            if response.status_code not in {401, 403}:
                self._clear_attachment_cache(document_id, attachment_id)
                return 200 <= response.status_code < 300
        return self.fallback.delete_attachment(document_id, attachment_id)

    async def get_attachment_file(self, document_id: str, attachment_id: str) -> Path | None:
        attachments = await self.list_attachments(document_id)
        attachment = next((item for item in attachments if item.id == attachment_id), None)
        raw_result = await self._request_raw_candidates("GET", self.attachment_download_candidates(document_id, attachment_id))
        if raw_result is not None:
            response, _ = raw_result
            content_type = response.headers.get("content-type", "")
            if response.status_code not in {401, 403} and response.content and "application/json" not in content_type and "application/ld+json" not in content_type:
                file_name = attachment.file_name if attachment is not None else attachment_id
                path = self._attachment_cache_path(document_id, attachment_id, file_name)
                path.write_bytes(response.content)
                return path
        return self.fallback.attachment_path(document_id, attachment_id)

    async def list_comments(self, document_id: str) -> list[CommentEntry]:
        payload = await self._request_candidates("GET", self.comment_candidates(document_id))
        if isinstance(payload, dict) and payload.get("restricted"):
            return self.fallback.comments(document_id)
        if payload is not None:
            comments = self._comments_from_payload(payload, document_id)
            if comments or isinstance(payload, (dict, list)):
                return comments
        return self.fallback.comments(document_id)

    async def add_comment(self, document_id: str, author: str, content: str) -> CommentEntry:
        payload_variants = [
            {"author": author, "content": content},
            {"author": author, "body": content},
            {"username": author, "text": content},
        ]
        for candidate_payload in payload_variants:
            raw_result = await self._request_raw_candidates("POST", self.comment_candidates(document_id), json_payload=candidate_payload)
            if raw_result is None:
                continue
            response, _ = raw_result
            if response.status_code in {401, 403}:
                break
            if 200 <= response.status_code < 300:
                payload = self._decode_response(response)
                comment = self._comment_from_payload(payload, document_id)
                if comment is not None:
                    return comment
                refreshed_comments = await self.list_comments(document_id)
                for comment in reversed(refreshed_comments):
                    if comment.author == author and comment.content == content:
                        return comment
        return self.fallback.add_comment(document_id, author, content)

    async def compare_items(
        self,
        left_id: str,
        right_id: str,
        left_project_id: str | None = None,
        left_branch_id: str | None = None,
        right_project_id: str | None = None,
        right_branch_id: str | None = None,
    ) -> CompareResult:
        if left_project_id and left_project_id == right_project_id and left_id.isdigit() and right_id.isdigit():
            revision_diff = await self._compare_revisions(left_project_id, left_id, right_id)
            if revision_diff is not None:
                return revision_diff

        left = (await self.get_item(left_id, left_project_id, left_branch_id)).model_dump(mode="json")
        right = (await self.get_item(right_id, right_project_id, right_branch_id)).model_dump(mode="json")
        differences = _dict_diff(left, right)
        return CompareResult(
            compare_type="item",
            left_id=left_id,
            right_id=right_id,
            summary=f"{len(differences)} field differences detected.",
            differences=differences,
        )

    async def _compare_revisions(self, resource_id: str, source_revision: str, target_revision: str) -> CompareResult | None:
        payload = await self._request_candidates(
            "GET",
            [f"/osmc/resources/{resource_id}/revisiondiff?source={source_revision}&target={target_revision}"],
        )
        if not isinstance(payload, dict) or payload.get("restricted"):
            return None

        differences: list[CompareDifference] = []
        for section, section_value in sorted(payload.items()):
            if section.startswith("@"):
                continue
            values = section_value if isinstance(section_value, list) else [section_value]
            for index, value in enumerate(values):
                differences.append(
                    CompareDifference(
                        field_path=f"{section}[{index}]",
                        left_value=None if section.lower().startswith("added") else value,
                        right_value=None if section.lower().startswith("removed") else value,
                        summary=f"{section} revision difference",
                    )
                )

        return CompareResult(
            compare_type="revisiondiff",
            left_id=source_revision,
            right_id=target_revision,
            summary=f"{len(differences)} revision differences detected.",
            differences=differences,
        )

    def project_candidates(self) -> list[str]:
        return [
            "/osmc/resources?includeBody=true&includeRemovedResource=false",
            "/osmc/resources?includeBody=true",
            "/osmc/resources",
            "/osmc/workspaces?includeBody=true",
        ]

    def current_user_candidates(self) -> list[str]:
        return ["/osmc/admin/currentUser"]

    def version_candidates(self) -> list[str]:
        return ["/osmc/version"]

    def tree_candidates(self, project_id: str | None, branch_id: str | None) -> list[str]:
        if not project_id:
            return []
        if not branch_id:
            return [f"/osmc/resources/{project_id}/models"]
        return [
            f"/osmc/resources/{project_id}/branches/{branch_id}/models",
            f"/osmc/resources/{project_id}/models",
        ]

    def item_candidates(self, item_id: str) -> list[str]:
        return []

    def search_candidates(self, query: str) -> list[str]:
        return []

    def simulation_candidates(self, project_id: str | None = None) -> list[str]:
        return []

    def simulation_run_candidates(self) -> list[str]:
        return []

    def document_candidates(self) -> list[str]:
        return []

    def document_item_candidates(self, document_id: str) -> list[str]:
        return []

    def attachment_candidates(self, document_id: str) -> list[str]:
        return []

    def attachment_item_candidates(self, document_id: str, attachment_id: str) -> list[str]:
        return []

    def attachment_download_candidates(self, document_id: str, attachment_id: str) -> list[str]:
        return []

    def comment_candidates(self, document_id: str) -> list[str]:
        return []


class Teamwork2022xAdapter(TeamworkAdapter):
    def version_candidates(self) -> list[str]:
        return ["/osmc/version"]


class Teamwork2024xAdapter(TeamworkAdapter):
    def version_candidates(self) -> list[str]:
        return ["/osmc/version"]


def create_adapter(server: ServerProfile, tokens: TokenBundle, storage_dir: Path) -> TeamworkAdapter:
    version = server.version
    context = AdapterContext(server=server, tokens=tokens, storage_dir=storage_dir)
    if version == TWCVersion.V2022X:
        return Teamwork2022xAdapter(context)
    if version == TWCVersion.V2024X:
        return Teamwork2024xAdapter(context)
    return TeamworkAdapter(context)


def _dict_diff(left: dict[str, Any], right: dict[str, Any], prefix: str = "") -> list[CompareDifference]:
    differences: list[CompareDifference] = []
    for key in sorted(set(left) | set(right)):
        current_path = f"{prefix}.{key}" if prefix else key
        left_value = left.get(key)
        right_value = right.get(key)
        if isinstance(left_value, dict) and isinstance(right_value, dict):
            differences.extend(_dict_diff(left_value, right_value, current_path))
            continue
        if left_value != right_value:
            differences.append(
                CompareDifference(
                    field_path=current_path,
                    left_value=left_value,
                    right_value=right_value,
                    summary=f"{current_path} changed",
                )
            )
    return differences
