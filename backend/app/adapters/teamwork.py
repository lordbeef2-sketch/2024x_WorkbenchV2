from __future__ import annotations

import asyncio
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from app.models.domain import (
    AttachmentInfo,
    Capability,
    CapabilityState,
    CapabilitySummary,
    CollaboratorDocument,
    CommentEntry,
    CompareDifference,
    CompareResult,
    DocumentVersion,
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


def _first_list(payload: dict[str, Any], *keys: str) -> list[Any] | None:
    for key in keys:
        if isinstance(payload.get(key), list):
            return payload[key]
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
        return _first_list(payload, *keys)
    return None


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
        for key in ("@id", "id", "value", "href", "models:root", "resource"):
            identifier = _reference_id(value.get(key))
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


def _ldp_member_ids(payload: dict[str, Any]) -> list[str]:
    identifiers: list[str] = []
    for item in _payload_dicts(payload):
        for member in _as_list(item.get("ldp:contains")):
            identifier = _reference_id(member)
            if identifier and identifier != "it" and identifier not in identifiers:
                identifiers.append(identifier)
    return identifiers


def _normalize_types(value: Any) -> list[str]:
    return [str(item) for item in _as_list(value) if str(item).strip()]


def _humanize_type(raw_type: str) -> str:
    tail = raw_type.split(":")[-1].rsplit("/", 1)[-1]
    normalized = tail.replace("_", " ").replace("-", " ").strip().lower()
    return normalized or "item"


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
        self.fallback = FallbackWorkspaceStore(context.storage_dir, context.server.id)
        self._detected_version: str | None = None
        self.verify = (
            context.server.ca_bundle_path if context.server.verify_tls and context.server.ca_bundle_path else context.server.verify_tls
        )

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.context.tokens.access_token}",
            "Accept": "application/json, application/ld+json;q=0.9, text/plain;q=0.5",
        }

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
        async with httpx.AsyncClient(timeout=timeout, verify=self.verify, follow_redirects=True) as client:
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

    async def health(self) -> dict[str, Any]:
        checks = {"base_url": False, "auth_url": False}
        version_hint = self.context.server.version.value if self.context.server.version != TWCVersion.AUTO else None
        try:
            async with httpx.AsyncClient(timeout=10.0, verify=self.verify, follow_redirects=True) as client:
                base_response = await client.get(self.context.server.base_url)
                checks["base_url"] = base_response.status_code < 500
                auth_response = await client.get(self.context.server.auth_url)
                checks["auth_url"] = auth_response.status_code < 500
                combined_text = f"{base_response.text}\n{auth_response.text}".lower()
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
        self._detected_version = "2024x"
        return self._detected_version

    async def discover_capabilities(self) -> CapabilitySummary:
        version = await self.detect_version()
        health = await self.health()
        simulation_payload = await self._request_candidates("GET", self.simulation_candidates())
        collaborator_payload = await self._request_candidates("GET", self.document_candidates())
        project_payload = await self._request_candidates("GET", self.project_candidates())
        project_accessible = bool(project_payload) and "restricted" not in str(project_payload)
        simulation_ready = bool(simulation_payload) and "restricted" not in str(simulation_payload)
        collaborator_ready = bool(collaborator_payload) and "restricted" not in str(collaborator_payload)

        capabilities = {
            "simulation": Capability(
                name="simulation",
                state=CapabilityState.READY,
                reason=(
                    "Remote simulation endpoint detected."
                    if simulation_ready
                    else "Remote simulation endpoint was not detected. The integrated local simulation runner remains available for workspace studies and exports."
                ),
                source="remote" if simulation_ready else "local",
            ),
            "attachment": Capability(
                name="attachment",
                state=CapabilityState.READY,
                reason=(
                    "Collaborator document endpoints detected."
                    if collaborator_ready
                    else "Remote collaborator endpoints were not detected. The local collaborator workspace remains available for documents, attachments, and comments."
                ),
                source="remote" if collaborator_ready else "local",
            ),
            "edit": Capability(
                name="edit",
                state=CapabilityState.READY if project_accessible else CapabilityState.RESTRICTED,
                reason=(
                    "Shared 2022xR2 and 2024xR3 contracts include model and resource write operations. Saves use version-aware request serialization and will still be revalidated at runtime."
                    if project_accessible
                    else "Shared write operations exist in the verified contract, but the active session did not expose enough repository endpoints to safely confirm write access."
                ),
                source="verified-contract" if project_accessible else "probe",
            ),
            "branch_edit": Capability(
                name="branch_edit",
                state=CapabilityState.READY if version == "2024x" else CapabilityState.RESTRICTED,
                reason=(
                    "Branch rename and metadata update endpoints are verified in the 2024xR3 export."
                    if version == "2024x"
                    else "Branch rename and metadata update were not present in the verified 2022xR2 export, so branch editing stays disabled."
                ),
                source="verified-contract",
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
            "publish": Capability(
                name="publish",
                state=CapabilityState.UNKNOWN,
                reason="Publish remains integration-defined and is not part of the verified main Teamwork Cloud contract surface.",
                source="integration",
            ),
        }
        return CapabilitySummary(
            detected_version=version,
            reachable_endpoints={
                "projects": project_accessible,
                "simulation": simulation_ready,
                "collaborator": collaborator_ready,
                **health.get("checks", {}),
            },
            capabilities=capabilities,
        )

    def _workspace_id_from_payload(self, payload: Any) -> str | None:
        entity = _payload_entity(payload)
        if not entity:
            return None
        for key in ("kerml:resource", "resource", "@base"):
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
            return _first_text(esi_data.get("name"), entity.get("kerml:name"), entity.get("dcterms:title"), entity.get("name"), entity.get("title"))
        return _first_text(entity.get("kerml:name"), entity.get("dcterms:title"), entity.get("name"), entity.get("title"))

    def _extract_description(self, payload: dict[str, Any]) -> str:
        entity = _payload_entity(payload) or {}
        return _first_text(entity.get("kerml:comment"), entity.get("dcterms:description"), entity.get("description"), entity.get("summary"))

    def _item_path(self, project_id: str, branch_id: str, item_name: str) -> str:
        normalized_name = item_name or "Unnamed Item"
        return f"{project_id}/{branch_id}/{normalized_name}"

    def _extract_item_metadata(self, payload: dict[str, Any]) -> dict[str, str]:
        entity = _payload_entity(payload) or {}
        metadata: dict[str, str] = {}
        for key in ("createdDate", "modifiedDate", "creator", "author", "commitID", "branchID", "resourceId", "resourceID", "removed"):
            value = entity.get(key)
            if value not in (None, ""):
                metadata[key] = str(value)
        esi_data = entity.get("kerml:esiData")
        if isinstance(esi_data, dict):
            for key, value in esi_data.items():
                if isinstance(value, (str, int, float, bool)):
                    metadata[f"esi.{key}"] = str(value)
        return metadata

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
                "version": overlay.version or item.version,
                "attachment_supported": overlay.attachment_supported or item.attachment_supported,
                "collaborators": overlay.collaborators or item.collaborators,
            }
        )

    async def _list_remote_branches(self, resource_id: str) -> list[BranchSummary]:
        payload = await self._request_candidates("GET", [f"/osmc/resources/{resource_id}/branches"])
        if payload is None:
            return []
        branch_ids = _ldp_member_ids(payload)
        branches: list[BranchSummary] = []
        for branch_id in branch_ids:
            detail = await self._request_candidates("GET", self.branch_candidates(resource_id, branch_id))
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

    async def _list_remote_projects(self) -> list[ProjectSummary]:
        payload = await self._request_candidates("GET", ["/osmc/resources"])
        if payload is None:
            return []
        resource_ids = _ldp_member_ids(payload)
        projects: list[ProjectSummary] = []
        for resource_id in resource_ids:
            detail = await self._request_candidates("GET", [f"/osmc/resources/{resource_id}"])
            detail_payload = _payload_entity(detail, "resource") or {}
            branches = await self._list_remote_branches(resource_id)
            if not branches:
                branches = [BranchSummary(id="main", name="main", description="Default branch placeholder")]
            projects.append(
                ProjectSummary(
                    id=resource_id,
                    name=self._extract_display_name(detail_payload) or resource_id,
                    description=self._extract_description(detail_payload),
                    favorite=False,
                    branches=branches,
                )
            )
        return projects

    def _model_tree_node(self, model_id: str, payload: dict[str, Any], project_id: str, branch_id: str) -> TreeNode:
        entity = _payload_entity(payload) or {}
        model_name = self._extract_display_name(entity) or model_id.upper()
        children: list[TreeNode] = []
        roots = _as_list(entity.get("models:roots"))
        for root in roots:
            if not isinstance(root, dict):
                continue
            root_id = _reference_id(root.get("models:root") or root.get("@id"))
            if not root_id:
                continue
            root_name = _first_text(root.get("models:name"), root_id)
            children.append(
                TreeNode(
                    id=root_id,
                    label=root_name,
                    node_type=_humanize_type(str(root.get("@type") or "model_root")),
                    path=f"{project_id}/{branch_id}/{model_name}/{root_name}",
                    children=[],
                    metadata={
                        "project_id": project_id,
                        "branch_id": branch_id,
                        "model_id": model_id,
                    },
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
                    TreeNode(
                        id=usage_id,
                        label=usage_name or usage_id,
                        node_type="usage",
                        path=f"{project_id}/{branch_id}/{model_name}/{usage_name or usage_id}",
                        children=[],
                        metadata={
                            "project_id": project_id,
                            "branch_id": branch_id,
                            "model_id": model_id,
                        },
                    )
                )

        return TreeNode(
            id=model_id,
            label=model_name,
            node_type="model",
            path=f"{project_id}/{branch_id}/{model_name}",
            children=children,
            metadata={
                "project_id": project_id,
                "branch_id": branch_id,
                "model_id": model_id,
            },
        )

    async def _load_remote_tree(self, project_id: str, branch_id: str) -> list[TreeNode]:
        payload = await self._request_candidates("GET", [f"/osmc/resources/{project_id}/branches/{branch_id}/models"])
        if not isinstance(payload, dict):
            return []
        model_ids = _ldp_member_ids(payload)
        nodes: list[TreeNode] = []
        for model_id in model_ids:
            model_payload = await self._request_candidates("GET", [f"/osmc/resources/{project_id}/branches/{branch_id}/models/{model_id}"])
            if isinstance(model_payload, dict):
                nodes.append(self._model_tree_node(model_id, model_payload, project_id, branch_id))
        return nodes

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

    def _remote_item_details(self, payload: dict[str, Any], item_id: str, project_id: str, branch_id: str) -> ItemDetails:
        entity = _payload_entity(payload) or {}
        raw_types = _normalize_types(entity.get("@type"))
        metadata = self._extract_item_metadata(entity)
        name = self._extract_display_name(entity) or item_id
        description = self._extract_description(entity)
        item_type = _humanize_type(raw_types[0]) if raw_types else "item"
        item = ItemDetails(
            id=item_id,
            name=name,
            item_type=item_type,
            path=self._item_path(project_id, branch_id, name),
            project_id=project_id,
            branch_id=branch_id,
            description=description,
            documentation_markdown=self._build_item_markdown(name, description, raw_types, metadata),
            metadata=metadata,
            relationships=self._extract_relationships(entity),
            version=metadata.get("modifiedDate") or metadata.get("commitID") or "remote",
            editable=True,
            attachment_supported=False,
            collaborators=[],
        )
        return self._overlay_item(item, project_id, branch_id)

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
            raise PermissionError("Branch rename and metadata updates are only available for 2024x servers.")

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

        updated_payload = json.loads(json.dumps(remote_payload))
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

        item = self._remote_item_details(response_payload or remote_payload, item_id, project_id, branch_id)
        overlay_fields = {
            key: value
            for key, value in payload.items()
            if key in {"name", "description", "documentation_markdown", "metadata", "version"}
        }
        return self.fallback.save_item(item.model_copy(update=overlay_fields))

    async def list_projects(self) -> list[ProjectSummary]:
        remote_projects = await self._list_remote_projects()
        if remote_projects:
            return remote_projects

        payload = await self._request_candidates("GET", self.project_candidates())
        if isinstance(payload, dict):
            items = _first_list(payload, "projects", "items", "data")
            if items is not None:
                projects = []
                for item in items:
                    projects.append(
                        ProjectSummary(
                            id=str(item.get("id") or item.get("projectId") or uuid4().hex),
                            name=str(item.get("name") or item.get("title") or "Unnamed Project"),
                            description=str(item.get("description") or item.get("summary") or ""),
                            favorite=False,
                            branches=[BranchSummary(id="main", name="main", description="Default branch")],
                        )
                    )
                if projects:
                    return projects
        return self.fallback.projects()

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
        return self.fallback.tree(project_id, branch_id)

    async def get_item(self, item_id: str, project_id: str | None = None, branch_id: str | None = None) -> ItemDetails:
        if project_id and branch_id:
            remote_payload = await self._remote_item_payload(project_id, branch_id, item_id)
            if _payload_entity(remote_payload) is not None:
                return self._remote_item_details(remote_payload, item_id, project_id, branch_id)

        payload = await self._request_candidates("GET", self.item_candidates(item_id))
        if isinstance(payload, dict) and payload.get("id"):
            try:
                return ItemDetails.model_validate(payload)
            except Exception:
                pass
        items = self.fallback.items()
        if item_id not in items:
            raise KeyError(item_id)
        return items[item_id]

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

        item = await self.get_item(item_id, project_id, branch_id)
        if not item.editable:
            raise PermissionError("This model item is read-only for the active session")

        updated = item.model_copy(
            update={
                key: value
                for key, value in payload.items()
                if key in {"name", "description", "documentation_markdown", "metadata", "version"}
            }
        )
        return self.fallback.save_item(updated)

    async def search(self, query: str) -> SearchResponse:
        payload = await self._request_candidates("GET", self.search_candidates(query))
        if isinstance(payload, dict):
            items = _first_list(payload, "results", "items", "data")
            if items is not None:
                results = [
                    SearchResult(
                        id=str(item.get("id") or uuid4().hex),
                        title=str(item.get("title") or item.get("name") or "Untitled"),
                        item_type=str(item.get("type") or "model"),
                        path=str(item.get("path") or ""),
                        excerpt=str(item.get("excerpt") or item.get("description") or ""),
                        score=float(item.get("score") or 0.5),
                    )
                    for item in items
                ]
                return SearchResponse(query=query, total=len(results), results=results)

        query_lower = query.lower().strip()
        results = []
        for item in self.fallback.items().values():
            searchable = f"{item.name} {item.description} {item.documentation_markdown} {item.path}".lower()
            if query_lower and query_lower in searchable:
                results.append(
                    SearchResult(
                        id=item.id,
                        title=item.name,
                        item_type=item.item_type,
                        path=item.path,
                        excerpt=item.description,
                        score=0.92,
                    )
                )
        return SearchResponse(query=query, total=len(results), results=results)

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

    async def compare_items(self, left_id: str, right_id: str) -> CompareResult:
        left = (await self.get_item(left_id)).model_dump(mode="json")
        right = (await self.get_item(right_id)).model_dump(mode="json")
        differences = _dict_diff(left, right)
        return CompareResult(
            compare_type="item",
            left_id=left_id,
            right_id=right_id,
            summary=f"{len(differences)} field differences detected.",
            differences=differences,
        )

    def project_candidates(self) -> list[str]:
        return ["/osmc/resources", "/api/projects", "/projects"]

    def version_candidates(self) -> list[str]:
        return ["/osmc/resources/version", "/api/version", "/version", "/about"]

    def tree_candidates(self, project_id: str | None, branch_id: str | None) -> list[str]:
        project_id = project_id or "aircraft-systems"
        branch_id = branch_id or "main"
        return [
            f"/api/projects/{project_id}/branches/{branch_id}/tree",
            f"/osmc/resources/projects/{project_id}/branches/{branch_id}/tree",
            f"/api/model-tree?projectId={project_id}&branchId={branch_id}",
        ]

    def item_candidates(self, item_id: str) -> list[str]:
        return [f"/api/items/{item_id}", f"/osmc/resources/items/{item_id}", f"/api/elements/{item_id}"]

    def search_candidates(self, query: str) -> list[str]:
        return [f"/api/search?query={query}", f"/osmc/resources/search?query={query}"]

    def simulation_candidates(self, project_id: str | None = None) -> list[str]:
        base_candidates = ["/api/simulations/configurations", "/simulation/api/configurations", "/simulations/configurations"]
        if not project_id:
            return base_candidates
        candidates: list[str] = []
        for candidate in base_candidates:
            candidates.append(f"{candidate}?projectId={project_id}")
            candidates.append(candidate)
        return candidates

    def simulation_run_candidates(self) -> list[str]:
        return ["/api/simulations/runs", "/simulation/api/runs", "/simulations/runs"]

    def document_candidates(self) -> list[str]:
        return ["/api/collaborator/documents", "/collaborator/api/documents", "/documents"]

    def document_item_candidates(self, document_id: str) -> list[str]:
        return [f"/api/collaborator/documents/{document_id}", f"/collaborator/api/documents/{document_id}", f"/documents/{document_id}"]

    def attachment_candidates(self, document_id: str) -> list[str]:
        return [
            f"/api/collaborator/documents/{document_id}/attachments",
            f"/collaborator/api/documents/{document_id}/attachments",
            f"/documents/{document_id}/attachments",
        ]

    def attachment_item_candidates(self, document_id: str, attachment_id: str) -> list[str]:
        return [
            f"/api/collaborator/documents/{document_id}/attachments/{attachment_id}",
            f"/collaborator/api/documents/{document_id}/attachments/{attachment_id}",
            f"/documents/{document_id}/attachments/{attachment_id}",
        ]

    def attachment_download_candidates(self, document_id: str, attachment_id: str) -> list[str]:
        return [
            f"/api/collaborator/documents/{document_id}/attachments/{attachment_id}/download",
            f"/collaborator/api/documents/{document_id}/attachments/{attachment_id}/download",
            f"/documents/{document_id}/attachments/{attachment_id}/download",
            *self.attachment_item_candidates(document_id, attachment_id),
        ]

    def comment_candidates(self, document_id: str) -> list[str]:
        return [
            f"/api/collaborator/documents/{document_id}/comments",
            f"/collaborator/api/documents/{document_id}/comments",
            f"/documents/{document_id}/comments",
        ]


class Teamwork2022xAdapter(TeamworkAdapter):
    def version_candidates(self) -> list[str]:
        return ["/osmc/resources/version", "/api/version", "/version", "/about"]


class Teamwork2024xAdapter(TeamworkAdapter):
    def version_candidates(self) -> list[str]:
        return ["/api/version", "/osmc/resources/version", "/version", "/about"]


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
