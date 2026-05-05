from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


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
    version: TWCVersion = TWCVersion.V2022X
    verify_tls: bool = True
    ca_bundle_path: str | None = None
    enabled: bool = True
    display_order: int = Field(default=0, ge=0)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_auth_fields(cls, raw: object) -> object:
        if not isinstance(raw, dict):
            return raw
        payload = dict(raw)
        payload.pop("auth_mode", None)
        payload.pop("auth_url", None)
        payload.pop("client_id", None)
        payload.pop("callback_url", None)
        return payload

    @field_validator("name", "base_url", "ca_bundle_path", mode="before")
    @classmethod
    def empty_string_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class ServerProfileCreate(ServerProfileBase):
    pass


class ServerProfileUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    version: TWCVersion | None = None
    verify_tls: bool | None = None
    ca_bundle_path: str | None = None
    enabled: bool | None = None
    display_order: int | None = Field(default=None, ge=0)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_auth_fields(cls, raw: object) -> object:
        if not isinstance(raw, dict):
            return raw
        payload = dict(raw)
        payload.pop("auth_mode", None)
        payload.pop("auth_url", None)
        payload.pop("client_id", None)
        payload.pop("callback_url", None)
        return payload

    @field_validator("name", "base_url", "ca_bundle_path", mode="before")
    @classmethod
    def empty_string_to_none_update(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class ServerProfile(ServerProfileBase):
    id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class PresetServerDefinition(ServerProfileBase):
    id: str


class ServerProfileReorderRequest(BaseModel):
    server_ids: list[str] = Field(default_factory=list)


class UserServerState(BaseModel):
    user_id: str
    selected_server_id: str | None = None
    last_used_server_id: str | None = None
    favorite_server_ids: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utcnow)


class AuthorizationContext(BaseModel):
    roles: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    source: str = "authenticated-user-default"
    can_manage_server_presets: bool = False


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
    project_id: str | None = None
    branch_id: str | None = None


class SavedSearch(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    name: str
    query: str
    filters: dict[str, Any] = Field(default_factory=dict)


class TokenBundle(BaseModel):
    access_token: str | None = None
    refresh_token: str | None = None
    id_token: str | None = None
    token_type: str = "Token"
    scope: str | None = None
    expires_at: datetime | None = None
    session_cookies: dict[str, str] = Field(default_factory=dict)
    upstream_user: str | None = None


class OSLCTokenBundle(BaseModel):
    access_token: str
    access_token_secret: str
    consumer_key: str
    consumer_secret: str | None = None
    rootservices_url: str
    request_token_url: str
    authorize_url: str
    access_token_url: str
    service_provider_catalog_url: str | None = None
    request_consumer_key_url: str | None = None
    configuration_management_service_providers_url: str | None = None
    acquired_at: datetime = Field(default_factory=utcnow)


class OSLCConsumerCredentials(BaseModel):
    consumer_key: str
    consumer_secret: str
    source: Literal["config", "session"] = "session"
    acquired_at: datetime = Field(default_factory=utcnow)


class TokenLoginRequest(BaseModel):
    server_id: str
    token: str


class SessionData(BaseModel):
    session_id: str = Field(default_factory=lambda: uuid4().hex)
    server: ServerProfile
    user: UserContext
    authorization_context: AuthorizationContext = Field(default_factory=AuthorizationContext)
    encrypted_credentials: str
    encrypted_oslc_credentials: str | None = None
    encrypted_oslc_consumer_credentials: str | None = None
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
    pending_server: ServerProfile | None = None
    server_state: UserServerState | None = None
    can_manage_server_presets: bool = False
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
    workspace_id: str | None = None
    resource_id: str | None = None
    categories: Any | None = None


class TreeNode(BaseModel):
    id: str
    label: str
    node_type: str
    path: str
    children: list["TreeNode"] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ItemReference(BaseModel):
    id: str
    name: str = ""
    item_type: str = "item"
    relationship_type: str = ""
    path: str = ""


class ItemDetails(BaseModel):
    id: str
    name: str
    item_type: str
    path: str
    project_id: str
    branch_id: str
    description: str = ""
    documentation_markdown: str = ""
    raw_types: list[str] = Field(default_factory=list)
    stereotypes: list[str] = Field(default_factory=list)
    owner: ItemReference | None = None
    type_references: list[ItemReference] = Field(default_factory=list)
    contained_elements: list[ItemReference] = Field(default_factory=list)
    related_items: list[ItemReference] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    version: str = "1.0"
    editable: bool = False
    attachment_supported: bool = False
    collaborators: list[str] = Field(default_factory=list)
    source_payload: dict[str, Any] = Field(default_factory=dict)


class ElementDiscoveryEntry(BaseModel):
    id: str
    name: str = ""
    item_type: str = "element"
    child_count: int = 0


class ElementDiscoveryResult(BaseModel):
    project_id: str
    branch_id: str
    workspace_id: str | None = None
    latest_revision: str | None = None
    seed_source: str = ""
    seed_ids: list[str] = Field(default_factory=list)
    ids: list[str] = Field(default_factory=list)
    entries: list[ElementDiscoveryEntry] = Field(default_factory=list)
    total_ids: int = 0
    traversed_elements: int = 0
    hydrated_elements: int = 0
    batch_count: int = 0
    batch_size: int = 200
    cache_status: Literal["full-refresh", "incremental-refresh", "cache-hit"] = "full-refresh"
    warnings: list[str] = Field(default_factory=list)
    discovered_at: datetime = Field(default_factory=utcnow)


class SearchResult(BaseModel):
    id: str
    title: str
    item_type: str
    path: str
    excerpt: str
    score: float
    project_id: str | None = None
    branch_id: str | None = None
    document_id: str | None = None
    target_tab: Literal["details", "collaborator"] = "details"


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
    project_id: str | None = None
    branch_id: str | None = None
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


class SwaggerParameterSpec(BaseModel):
    name: str
    location: str
    required: bool = False
    schema_type: str = "string"
    schema_format: str | None = None
    schema_ref: str | None = None
    description: str = ""
    enum: list[Any] = Field(default_factory=list)
    default: Any = None
    is_file: bool = False


class SwaggerRequestBodySpec(BaseModel):
    required: bool = False
    description: str = ""
    content_types: list[str] = Field(default_factory=list)
    schema_refs: dict[str, str | None] = Field(default_factory=dict)


class SwaggerResponseSpec(BaseModel):
    status_code: str
    description: str = ""
    content_types: list[str] = Field(default_factory=list)
    schema_ref: str | None = None


class SwaggerSchemaProperty(BaseModel):
    name: str
    schema_type: str = "object"
    schema_format: str | None = None
    schema_ref: str | None = None
    description: str = ""
    required: bool = False
    enum: list[Any] = Field(default_factory=list)


class SwaggerSchemaSummary(BaseModel):
    name: str
    schema_type: str = "object"
    description: str = ""
    required: list[str] = Field(default_factory=list)
    properties: list[SwaggerSchemaProperty] = Field(default_factory=list)


class SwaggerOperationSpec(BaseModel):
    key: str
    method: str
    path: str
    tag: str
    tags: list[str] = Field(default_factory=list)
    operation_id: str | None = None
    summary: str = ""
    description: str = ""
    path_parameters: list[SwaggerParameterSpec] = Field(default_factory=list)
    query_parameters: list[SwaggerParameterSpec] = Field(default_factory=list)
    header_parameters: list[SwaggerParameterSpec] = Field(default_factory=list)
    form_parameters: list[SwaggerParameterSpec] = Field(default_factory=list)
    request_body: SwaggerRequestBodySpec | None = None
    responses: list[SwaggerResponseSpec] = Field(default_factory=list)
    supports_file_upload: bool = False
    supports_download: bool = False
    destructive: bool = False


class SwaggerContractManifest(BaseModel):
    openapi: str
    title: str
    version: str
    server_urls: list[str] = Field(default_factory=list)
    security: list[str] = Field(default_factory=list)
    operation_counts: dict[str, int] = Field(default_factory=dict)
    tag_counts: dict[str, int] = Field(default_factory=dict)
    operations: list[SwaggerOperationSpec] = Field(default_factory=list)
    schemas: list[SwaggerSchemaSummary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SwaggerExecuteRequest(BaseModel):
    operation_key: str
    path_params: dict[str, Any] = Field(default_factory=dict)
    query_params: dict[str, Any] = Field(default_factory=dict)
    body: Any = None
    content_type: str | None = None
    timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)


class SwaggerExecuteResponse(BaseModel):
    operation_key: str
    method: str
    path: str
    requested_path: str
    status_code: int
    ok: bool
    content_type: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None
    text: str | None = None
    body_base64: str | None = None
    is_binary: bool = False
    size_bytes: int = 0
    filename: str | None = None


class OSLCRootServicesSummary(BaseModel):
    rootservices_url: str
    service_provider_catalog_url: str | None = None
    configuration_management_service_providers_url: str | None = None
    request_token_url: str | None = None
    authorize_url: str | None = None
    access_token_url: str | None = None
    request_consumer_key_url: str | None = None
    raw_content_type: str = ""


class OSLCAuthorizationStatus(BaseModel):
    server_id: str
    configured: bool
    authorized: bool
    rootservices: OSLCRootServicesSummary | None = None
    consumer_key_configured: bool = False
    consumer_key_source: Literal["none", "config", "shared", "session"] = "none"
    can_generate_consumer_key: bool = False
    message: str = ""


class OSLCStoreConsumerRequest(BaseModel):
    consumer_key: str
    consumer_secret: str


class OSLCGenerateConsumerRequest(BaseModel):
    name: str
    secret: str
    remember_for_session: bool = True


class OSLCGenerateConsumerResponse(BaseModel):
    consumer_key: str
    request_consumer_key_url: str
    stored_for_session: bool = False
    approval_required: bool = True
    message: str = ""


class OSLCSharedConsumerRequest(BaseModel):
    consumer_key: str
    consumer_secret: str


class OSLCSharedConsumerStatus(BaseModel):
    server_id: str
    configured: bool
    consumer_key: str | None = None
    updated_at: datetime | None = None
    source: Literal["none", "shared", "config"] = "none"


class OSLCExecuteRequest(BaseModel):
    path_or_url: str
    accept: str | None = None
    timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)


class OSLCExecuteResponse(BaseModel):
    requested_url: str
    status_code: int
    ok: bool
    content_type: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None
    text: str | None = None
    body_base64: str | None = None
    is_binary: bool = False
    size_bytes: int = 0
    filename: str | None = None
