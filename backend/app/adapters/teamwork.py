from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable
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
        self.verify = (
            context.server.ca_bundle_path if context.server.verify_tls and context.server.ca_bundle_path else context.server.verify_tls
        )

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.context.tokens.access_token}",
            "Accept": "application/json",
        }

    async def _request_candidates(
        self,
        method: str,
        candidates: list[str],
        *,
        json_payload: Any | None = None,
        timeout: float = 20.0,
    ) -> dict[str, Any] | list[Any] | None:
        async with httpx.AsyncClient(timeout=timeout, verify=self.verify, follow_redirects=True) as client:
            for candidate in candidates:
                url = f"{self.context.server.base_url.rstrip('/')}{candidate}"
                try:
                    response = await client.request(method, url, headers=self.headers, json=json_payload)
                except httpx.HTTPError:
                    continue
                if response.status_code in {200, 201, 202}:
                    content_type = response.headers.get("content-type", "")
                    if "application/json" in content_type:
                        return response.json()
                    return {"raw": response.text}
                if response.status_code in {401, 403}:
                    return {"restricted": True}
        return None

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
        if self.context.server.version != TWCVersion.AUTO:
            return self.context.server.version.value
        version_payload = await self._request_candidates("GET", self.version_candidates())
        if isinstance(version_payload, dict):
            for key in ("version", "productVersion", "raw"):
                value = str(version_payload.get(key, ""))
                if "2024x" in value:
                    return "2024x"
                if "2022x" in value:
                    return "2022x"
        return "2024x"

    async def discover_capabilities(self) -> CapabilitySummary:
        version = await self.detect_version()
        health = await self.health()
        simulation_payload = await self._request_candidates("GET", self.simulation_candidates())
        collaborator_payload = await self._request_candidates("GET", self.document_candidates())
        project_payload = await self._request_candidates("GET", self.project_candidates())

        capabilities = {
            "simulation": Capability(
                name="simulation",
                state=CapabilityState.READY if simulation_payload and "restricted" not in str(simulation_payload) else CapabilityState.RESTRICTED,
                reason=(
                    "Remote simulation endpoint detected."
                    if simulation_payload and "restricted" not in str(simulation_payload)
                    else "Remote simulation endpoint could not be safely confirmed. Local fallback executor will remain available."
                ),
                source="remote" if simulation_payload and "restricted" not in str(simulation_payload) else "fallback",
            ),
            "attachment": Capability(
                name="attachment",
                state=CapabilityState.READY if collaborator_payload else CapabilityState.RESTRICTED,
                reason=(
                    "Collaborator document endpoints detected."
                    if collaborator_payload
                    else "Collaborator attachment endpoints are not confirmed. Attachments can be staged locally until a remote endpoint is configured."
                ),
                source="remote" if collaborator_payload else "fallback",
            ),
            "edit": Capability(
                name="edit",
                state=CapabilityState.READY if version == "2024x" else CapabilityState.RESTRICTED,
                reason=(
                    "Write workflows are enabled for this branch and will be revalidated on save."
                    if version == "2024x"
                    else "Write capability could not be non-destructively validated. The UI will stay conservative and re-check on save."
                ),
                source="probe",
            ),
            "user_access": Capability(
                name="user_access",
                state=CapabilityState.READY if project_payload else CapabilityState.RESTRICTED,
                reason=(
                    "Project listing was accessible with the active session."
                    if project_payload
                    else "Project listing could not be loaded. Access will be inferred from subsequent API responses."
                ),
                source="probe",
            ),
            "publish": Capability(
                name="publish",
                state=CapabilityState.UNKNOWN,
                reason="Publish capability is finalized by the pluggable publisher adapter.",
                source="integration",
            ),
        }
        return CapabilitySummary(
            detected_version=version,
            reachable_endpoints={
                "projects": bool(project_payload),
                "simulation": bool(simulation_payload),
                "collaborator": bool(collaborator_payload),
                **health.get("checks", {}),
            },
            capabilities=capabilities,
        )

    async def list_projects(self) -> list[ProjectSummary]:
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
        payload = await self._request_candidates("GET", self.tree_candidates(project_id, branch_id))
        if isinstance(payload, dict):
            items = _first_list(payload, "tree", "items", "data")
            if items:
                return [TreeNode.model_validate(item) for item in items]
        return self.fallback.tree(project_id, branch_id)

    async def get_item(self, item_id: str) -> ItemDetails:
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

    async def update_item(self, item_id: str, payload: dict[str, Any]) -> ItemDetails:
        remote_payload = await self._request_candidates("PUT", self.item_candidates(item_id), json_payload=payload)
        if isinstance(remote_payload, dict) and remote_payload.get("id"):
            try:
                return ItemDetails.model_validate(remote_payload)
            except Exception:
                pass

        item = await self.get_item(item_id)
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
        payload = await self._request_candidates("GET", self.simulation_candidates())
        if isinstance(payload, dict):
            items = _first_list(payload, "configurations", "items", "data")
            if items is not None:
                configs = []
                for item in items:
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
        if isinstance(payload, dict):
            items = _first_list(payload, "documents", "items", "data")
            if items:
                return [CollaboratorDocument.model_validate(item) for item in items]
        return self.fallback.documents()

    async def get_document(self, document_id: str) -> CollaboratorDocument:
        payload = await self._request_candidates("GET", self.document_item_candidates(document_id))
        if isinstance(payload, dict) and payload.get("id"):
            return CollaboratorDocument.model_validate(payload)
        for document in self.fallback.documents():
            if document.id == document_id:
                return document
        raise KeyError(document_id)

    async def update_document(self, document_id: str, body_markdown: str) -> CollaboratorDocument:
        payload = await self._request_candidates(
            "PUT",
            self.document_item_candidates(document_id),
            json_payload={"body_markdown": body_markdown},
        )
        if isinstance(payload, dict) and payload.get("id"):
            return CollaboratorDocument.model_validate(payload)
        document = await self.get_document(document_id)
        document.body_markdown = body_markdown
        document.versions = [
            DocumentVersion(id=uuid4().hex, label=f"{len(document.versions) + 1}.0", created_at=utcnow(), summary="Saved from workbench"),
            *document.versions,
        ]
        return self.fallback.save_document(document)

    async def list_attachments(self, document_id: str) -> list[AttachmentInfo]:
        payload = await self._request_candidates("GET", self.attachment_candidates(document_id))
        if isinstance(payload, dict):
            items = _first_list(payload, "attachments", "items", "data")
            if items:
                return [AttachmentInfo.model_validate(item) for item in items]
        return self.fallback.attachments(document_id)

    async def upload_attachment(self, document_id: str, file_name: str, content_type: str, content: bytes) -> AttachmentInfo:
        return self.fallback.add_attachment(document_id, file_name, content_type, content)

    async def delete_attachment(self, document_id: str, attachment_id: str) -> bool:
        return self.fallback.delete_attachment(document_id, attachment_id)

    async def get_attachment_file(self, document_id: str, attachment_id: str) -> Path | None:
        return self.fallback.attachment_path(document_id, attachment_id)

    async def list_comments(self, document_id: str) -> list[CommentEntry]:
        return self.fallback.comments(document_id)

    async def add_comment(self, document_id: str, author: str, content: str) -> CommentEntry:
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
        return ["/api/projects", "/osmc/resources/projects", "/projects"]

    def version_candidates(self) -> list[str]:
        return ["/api/version", "/version", "/about"]

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

    def simulation_candidates(self) -> list[str]:
        return ["/api/simulations/configurations", "/simulation/api/configurations", "/simulations/configurations"]

    def simulation_run_candidates(self) -> list[str]:
        return ["/api/simulations/runs", "/simulation/api/runs", "/simulations/runs"]

    def document_candidates(self) -> list[str]:
        return ["/api/collaborator/documents", "/collaborator/api/documents", "/documents"]

    def document_item_candidates(self, document_id: str) -> list[str]:
        return [f"/api/collaborator/documents/{document_id}", f"/collaborator/api/documents/{document_id}"]

    def attachment_candidates(self, document_id: str) -> list[str]:
        return [
            f"/api/collaborator/documents/{document_id}/attachments",
            f"/collaborator/api/documents/{document_id}/attachments",
        ]


class Teamwork2022xAdapter(TeamworkAdapter):
    def version_candidates(self) -> list[str]:
        return ["/osmc/resources/version", "/version", "/about"]


class Teamwork2024xAdapter(TeamworkAdapter):
    def version_candidates(self) -> list[str]:
        return ["/api/version", "/version", "/about"]


def create_adapter(server: ServerProfile, tokens: TokenBundle, storage_dir: Path) -> TeamworkAdapter:
    version = server.version
    context = AdapterContext(server=server, tokens=tokens, storage_dir=storage_dir)
    if version == TWCVersion.V2022X:
        return Teamwork2022xAdapter(context)
    if version == TWCVersion.V2024X:
        return Teamwork2024xAdapter(context)
    return Teamwork2024xAdapter(context)


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
