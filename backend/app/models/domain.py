from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class TWCVersion(str, Enum):
    AUTO = "auto"
    V2022X = "2022x"
    V2024X = "2024x"


class CapabilityState(str, Enum):
    READY = "ready"
    RESTRICTED = "restricted"
    NOT_AVAILABLE = "not_available"
    UNKNOWN = "unknown"


class JobType(str, Enum):
    SIMULATION = "simulation"
    PUBLISH = "publish"
    EXPORT = "export"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ThemeMode(str, Enum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


class ServerProfileBase(BaseModel):
    name: str
    base_url: str
    auth_url: str
    version: TWCVersion = TWCVersion.AUTO
    client_id: str
    callback_url: str
    verify_tls: bool = True
    ca_bundle_path: str | None = None
    favorite: bool = False


class ServerProfileCreate(ServerProfileBase):
    pass


class ServerProfileUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    auth_url: str | None = None
    version: TWCVersion | None = None
    client_id: str | None = None
    callback_url: str | None = None
    verify_tls: bool | None = None
    ca_bundle_path: str | None = None
    favorite: bool | None = None


class ServerProfile(ServerProfileBase):
    id: str = Field(default_factory=lambda: uuid4().hex)
    last_used_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ServerHealth(BaseModel):
    server_id: str
    status: Literal["healthy", "degraded", "unreachable"]
    version_hint: str | None = None
    response_time_ms: int | None = None
    checks: dict[str, bool] = Field(default_factory=dict)
    message: str = ""


class UserContext(BaseModel):
    preferred_username: str
    server_id: str
    server_name: str


class Capability(BaseModel):
    name: str
    state: CapabilityState
    reason: str = ""
    source: str = "probe"
    detected_at: datetime = Field(default_factory=utcnow)


class CapabilitySummary(BaseModel):
    detected_version: str
    reachable_endpoints: dict[str, bool] = Field(default_factory=dict)
    capabilities: dict[str, Capability] = Field(default_factory=dict)
    detected_at: datetime = Field(default_factory=utcnow)


class SessionPreferences(BaseModel):
    theme_mode: ThemeMode = ThemeMode.SYSTEM
    font_scale: float = 1.0
    request_timeout_seconds: int = 30
    live_log_poll_interval_ms: int = 2500
    presentation_font_scale: float = 1.2


class Bookmark(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    title: str
    item_id: str
    item_type: str
    path: str = ""


class SavedSearch(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    name: str
    query: str
    filters: dict[str, Any] = Field(default_factory=dict)


class TokenBundle(BaseModel):
    access_token: str
    refresh_token: str | None = None
    id_token: str | None = None
    token_type: str = "Bearer"
    scope: str | None = None
    expires_at: datetime | None = None


class PATLoginRequest(BaseModel):
    server_id: str
    preferred_username: str
    personal_access_token: str
    admin_secret: str | None = None


class SessionData(BaseModel):
    session_id: str = Field(default_factory=lambda: uuid4().hex)
    server: ServerProfile
    user: UserContext
    encrypted_tokens: str
    csrf_token: str = Field(default_factory=lambda: uuid4().hex)
    capabilities: CapabilitySummary
    preferences: SessionPreferences = Field(default_factory=SessionPreferences)
    bookmarks: list[Bookmark] = Field(default_factory=list)
    saved_searches: list[SavedSearch] = Field(default_factory=list)
    recent_items: list[Bookmark] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime = Field(default_factory=utcnow)


class SessionSnapshot(BaseModel):
    authenticated: bool
    session_id: str | None = None
    csrf_token: str | None = None
    user: UserContext | None = None
    server: ServerProfile | None = None
    capabilities: CapabilitySummary | None = None
    preferences: SessionPreferences = Field(default_factory=SessionPreferences)
    bookmarks: list[Bookmark] = Field(default_factory=list)
    saved_searches: list[SavedSearch] = Field(default_factory=list)
    recent_items: list[Bookmark] = Field(default_factory=list)


class BranchSummary(BaseModel):
    id: str
    name: str
    description: str = ""


class BranchUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class ProjectSummary(BaseModel):
    id: str
    name: str
    description: str = ""
    favorite: bool = False
    branches: list[BranchSummary] = Field(default_factory=list)


class TreeNode(BaseModel):
    id: str
    label: str
    node_type: str
    path: str
    children: list["TreeNode"] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ItemDetails(BaseModel):
    id: str
    name: str
    item_type: str
    path: str
    project_id: str
    branch_id: str
    description: str = ""
    documentation_markdown: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    version: str = "1.0"
    editable: bool = False
    attachment_supported: bool = False
    collaborators: list[str] = Field(default_factory=list)


class SearchResult(BaseModel):
    id: str
    title: str
    item_type: str
    path: str
    excerpt: str
    score: float


class SearchResponse(BaseModel):
    query: str
    total: int
    results: list[SearchResult] = Field(default_factory=list)


class SimulationParameter(BaseModel):
    name: str
    label: str
    kind: Literal["string", "integer", "number", "boolean", "choice"]
    description: str = ""
    required: bool = False
    default_value: Any = None
    options: list[str] = Field(default_factory=list)


class SimulationConfig(BaseModel):
    id: str
    name: str
    description: str
    project_id: str
    editable_parameters: list[SimulationParameter] = Field(default_factory=list)
    supports_cancel: bool = True


class SimulationRunRequest(BaseModel):
    config_id: str
    project_id: str
    branch_id: str = "main"
    parameters: dict[str, Any] = Field(default_factory=dict)


class PublishRequest(BaseModel):
    project_id: str
    branch_id: str
    scope: str
    template: str
    category: str
    republish: bool = False
    open_result: bool = True
    presets: dict[str, Any] = Field(default_factory=dict)


class PublishPreset(BaseModel):
    id: str
    name: str
    template: str
    category: str
    description: str


class DocumentVersion(BaseModel):
    id: str
    label: str
    created_at: datetime
    summary: str = ""


class AttachmentInfo(BaseModel):
    id: str
    document_id: str
    file_name: str
    content_type: str
    size_bytes: int
    uploaded_at: datetime = Field(default_factory=utcnow)
    source: str = "remote"


class CommentEntry(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    document_id: str
    author: str
    content: str
    created_at: datetime = Field(default_factory=utcnow)


class CollaboratorDocument(BaseModel):
    id: str
    title: str
    item_id: str
    project_id: str
    branch_id: str
    body_markdown: str
    breadcrumbs: list[str] = Field(default_factory=list)
    toc: list[str] = Field(default_factory=list)
    editable: bool = False
    attachments_supported: bool = False
    versions: list[DocumentVersion] = Field(default_factory=list)


class CompareDifference(BaseModel):
    field_path: str
    left_value: Any = None
    right_value: Any = None
    summary: str


class CompareResult(BaseModel):
    compare_type: str
    left_id: str
    right_id: str
    summary: str
    differences: list[CompareDifference] = Field(default_factory=list)


class ExportRequest(BaseModel):
    export_type: Literal["item", "compare", "search", "simulation"]
    export_format: Literal["json", "csv", "markdown", "html", "pdf"]
    reference_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class JobRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    job_type: JobType
    status: JobStatus = JobStatus.PENDING
    title: str
    owner: str
    server_id: str
    progress: int = 0
    message: str = "Queued"
    logs: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    artifact_path: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cancel_requested: bool = False


class DashboardPayload(BaseModel):
    projects: list[ProjectSummary] = Field(default_factory=list)
    recent_items: list[Bookmark] = Field(default_factory=list)
    bookmarks: list[Bookmark] = Field(default_factory=list)
    capability_badges: list[Capability] = Field(default_factory=list)
    active_jobs: list[JobRecord] = Field(default_factory=list)
    publish_presets: list[PublishPreset] = Field(default_factory=list)
