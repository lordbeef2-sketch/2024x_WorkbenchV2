from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import json
import secrets
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
import re
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx
import structlog

from app.auth.twc import infer_token_expiry, refresh_twc_auth_token
from app.adapters.teamwork import MODEL_CACHE_SYNC_MIN_REQUEST_INTERVAL_SECONDS, TeamworkAdapter, _dict_diff, create_adapter
from app.core.pdf import render_pdf_document
from app.core.storage import SqliteRepository
from app.integrations.publisher import PublisherAdapter, build_publisher
from app.jobs.coordinator import JobCoordinator
from app.models.domain import (
    AuthorizationContext,
    BranchIngestState,
    BranchAccessManifestStatus,
    BranchAccessRecord,
    BranchPermissionAttachment,
    BranchTombstoneRecord,
    BranchTombstoneRequest,
    Bookmark,
    BranchDeltaIngestRequest,
    BranchWebhookRegistration,
    BranchCacheSnapshot,
    BranchCacheSummary,
    BranchCacheSyncRequest,
    BranchSnapshotIngestRequest,
    BranchSummary,
    BranchUpdateRequest,
    CacheApiKeyCreateResponse,
    CacheApiKeyRecord,
    CacheApiKeyScope,
    CacheApiKeySummary,
    CacheChildrenResponse,
    CacheElementEditRequest,
    CacheElementGraphResponse,
    CacheElementSearchResponse,
    CacheApiManifest,
    CacheApiTokenIdentity,
    CacheIngestTokenRotateResponse,
    CacheIngestTokenStatus,
    CacheServerEntry,
    CacheProjectBranchEntry,
    CacheProjectEntry,
    Capability,
    CapabilityState,
    CachedElementQueryResponse,
    CachedElementRecord,
    CachedModelRecord,
    CachedModelView,
    CommentEntry,
    CompareContext,
    CompareDifference,
    CompareResult,
    CurrentPermissionStatus,
    DashboardPayload,
    ElementDiscoveryEntry,
    ElementDiscoveryResult,
    ExportRequest,
    FallbackCacheRefreshRequest,
    FallbackCacheRefreshStatus,
    ItemDetails,
    ItemReference,
    JobRecord,
    JobStatus,
    JobType,
    MaterializedCacheStatus,
    ModelPermissionSnapshot,
    PermissionManifest,
    PermissionManifestEntry,
    PermissionRefreshAuditRecord,
    PermissionRefreshRequest,
    OSLCAuthorizationStatus,
    OSLCConsumerCredentials,
    OSLCExecuteRequest,
    OSLCExecuteResponse,
    OSLCGenerateConsumerResponse,
    OSLCSharedConsumerStatus,
    OpenWebUIModelEntry,
    ProjectSummary,
    ProjectTombstoneRecord,
    ProjectTombstoneRequest,
    ProjectUsageResponse,
    ProjectUsageSummary,
    PublishRequest,
    SavedSearch,
    SearchResponse,
    ServerHealth,
    ServerPermissionInventory,
    ServerPermissionInventoryAuditRecord,
    ServerPermissionInventoryStatus,
    ServerProfile,
    ServerProfileCreate,
    ServerProfileReorderRequest,
    ServerProfileUpdate,
    SessionData,
    SessionPreferences,
    SessionSnapshot,
    SimulationConfig,
    SimulationRunRequest,
    SwaggerContractManifest,
    SwaggerExecuteRequest,
    SwaggerExecuteResponse,
    TokenBundle,
    TokenLoginRequest,
    TreeNode,
    TWCVersion,
    UserServerState,
    UserContext,
    WorkbenchAgentChatRequest,
    WorkbenchAgentChatResponse,
    WorkbenchAgentConfigRequest,
    WorkbenchAgentKnowledgeStatus,
    WorkbenchAgentSecret,
    WorkbenchAgentStatus,
    WebhookRegistrationStatus,
    CacheTreeResponse,
    StereotypeElementSearchResponse,
    utcnow,
)
from app.security.session import SessionManager
from app.services.swagger_contract import SwaggerContract
from app.settings.config import Settings

logger = structlog.get_logger(__name__)


SERVER_ADMIN_ROLE_NAMES = {"server administrator", "configure server"}
TWC_SERVER_ADMIN_ROLE_NAME = "server administrator"
PROJECT_LIST_CACHE_KEY = "projects"
BRANCH_REVISION_PROBE_TTL_SECONDS = 20
FAILED_BRANCH_CACHE_RETRY_SECONDS = 300
PLUGIN_CACHE_SOURCE_KIND = "cameo-plugin"


def normalize_lookup_key(value: str) -> str:
    return value.strip().lower()


OPAQUE_IDENTIFIER_RE = re.compile(r"^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{24,32})$", re.IGNORECASE)


class PermissionSnapshotIndeterminateError(RuntimeError):
    """The refresh could not authoritatively confirm grants or revocations."""


class PlatformService:
    def __init__(
        self,
        *,
        settings: Settings,
        oauth,
        repo: SqliteRepository,
        sessions: SessionManager,
        jobs: JobCoordinator,
        publisher: PublisherAdapter,
    ) -> None:
        self.settings = settings
        self.oauth = oauth
        self.repo = repo
        self.sessions = sessions
        self.jobs = jobs
        self.publisher = publisher
        self._model_cache_server_locks: dict[str, asyncio.Lock] = {}
        self._permission_snapshot_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._permission_inventory_locks: dict[str, asyncio.Lock] = {}
        self._permission_inventory_dirty_notifier: Callable[[], None] | None = None
        self._permission_refresh_instance_id = secrets.token_hex(16)
        self._branch_revision_probe_cache: dict[tuple[str, str, str], tuple[datetime, str | None]] = {}
        contract_path = Path(__file__).resolve().parents[3] / "contracts" / "RealSwagger.json"
        if not contract_path.exists():
            contract_path = Path.cwd() / "contracts" / "RealSwagger.json"
        self.contract = SwaggerContract(contract_path)

    def list_servers(self) -> list[ServerProfile]:
        return self.repo.list_servers()

    def list_servers_for_management(self) -> list[ServerProfile]:
        return self.repo.list_servers(include_disabled=True)

    def create_server(self, payload: ServerProfileCreate) -> ServerProfile:
        server = ServerProfile(**payload.model_dump())
        if "display_order" not in payload.model_fields_set:
            server.display_order = self.repo.next_server_display_order()
        return self.repo.upsert_server(server)

    def update_server(self, server_id: str, payload: ServerProfileUpdate) -> ServerProfile:
        current = self._require_server(server_id)
        updated = current.model_copy(update={key: value for key, value in payload.model_dump(exclude_none=True).items()})
        updated.updated_at = utcnow()
        return self.repo.upsert_server(updated)

    def reorder_servers(self, payload: ServerProfileReorderRequest) -> list[ServerProfile]:
        current_servers = self.repo.list_servers(include_disabled=True)
        servers_by_id = {server.id: server for server in current_servers}
        requested_ids = [server_id for server_id in payload.server_ids if server_id in servers_by_id]
        missing_ids = [server_id for server_id in payload.server_ids if server_id not in servers_by_id]
        if missing_ids:
            raise KeyError(missing_ids[0])

        ordered_ids = requested_ids + [server.id for server in current_servers if server.id not in requested_ids]
        ordered_servers: list[ServerProfile] = []
        for index, server_id in enumerate(ordered_ids):
            server = servers_by_id[server_id]
            if server.display_order != index:
                server = server.model_copy(update={"display_order": index, "updated_at": utcnow()})
            ordered_servers.append(server)

        return self.repo.bulk_upsert_servers(ordered_servers)

    def delete_server(self, server_id: str) -> bool:
        return self.repo.delete_server(server_id)

    def get_server(self, server_id: str, *, include_disabled: bool = True) -> ServerProfile | None:
        server = self.repo.get_server(server_id)
        if not server:
            return None
        if not include_disabled and not server.enabled:
            return None
        return server

    def can_manage_server_presets(self, session: SessionData) -> bool:
        return session.authorization_context.can_manage_server_presets

    async def health_check(self, server_id: str, *, include_disabled: bool = False) -> ServerHealth:
        server = self._require_server(server_id, include_disabled=include_disabled)
        verify = server.ca_bundle_path if server.verify_tls and server.ca_bundle_path else server.verify_tls
        checks = {"base_url": False}
        version_hint = server.version.value if server.version != TWCVersion.AUTO else None
        message = ""
        response_time_ms = None
        try:
            async with httpx.AsyncClient(timeout=8.0, verify=verify, follow_redirects=True) as client:
                response = await client.get(server.base_url)
                checks["base_url"] = response.status_code < 500
                response_time_ms = int(response.elapsed.total_seconds() * 1000)
                text = response.text
                text = text.lower()
                if "2024x" in text:
                    version_hint = "2024x"
                elif "2022x" in text:
                    version_hint = "2022x"
                if not all(checks.values()):
                    message = "At least one endpoint responded outside the healthy threshold."
        except httpx.HTTPError as exc:
            message = str(exc)

        if all(checks.values()):
            status = "healthy"
        elif any(checks.values()):
            status = "degraded"
        else:
            status = "unreachable"

        return ServerHealth(
            server_id=server.id,
            status=status,
            version_hint=version_hint,
            response_time_ms=response_time_ms,
            checks=checks,
            message=message,
        )

    async def login_with_upstream_session(
        self,
        server_id: str,
        *,
        access_token: str | None,
        session_cookies: dict[str, str],
        preferred_username: str | None,
        upstream_roles: list[str] | None = None,
        upstream_groups: list[str] | None = None,
    ) -> SessionData:
        server = self._require_server(server_id, include_disabled=False)
        credentials = TokenBundle(
            access_token=access_token,
            session_cookies=session_cookies,
            upstream_user=preferred_username,
        )
        if not credentials.access_token and not credentials.session_cookies:
            raise PermissionError(
                "No upstream Teamwork Cloud credentials were present on the request. Deploy this app behind the same TWC session cookie domain or a proxy that forwards a user-scoped TWC token."
            )

        return await self._create_authenticated_session(
            server,
            credentials,
            fallback_username=preferred_username,
            upstream_roles=upstream_roles,
            upstream_groups=upstream_groups,
            log_event="upstream-session-login-complete",
        )

    async def login_with_token(
        self,
        payload: TokenLoginRequest,
        *,
        upstream_roles: list[str] | None = None,
        upstream_groups: list[str] | None = None,
    ) -> SessionData:
        server = self._require_server(payload.server_id, include_disabled=False)
        credentials = self._token_bundle_from_login_token(payload.token)
        return await self._create_authenticated_session(
            server,
            credentials,
            upstream_roles=upstream_roles,
            upstream_groups=upstream_groups,
            log_event="token-login-complete",
        )

    async def login_with_token_bundle(
        self,
        server_id: str,
        token_bundle: TokenBundle,
        *,
        preferred_username: str | None = None,
        upstream_roles: list[str] | None = None,
        upstream_groups: list[str] | None = None,
    ) -> SessionData:
        server = self._require_server(server_id, include_disabled=False)
        return await self._create_authenticated_session(
            server,
            token_bundle,
            fallback_username=preferred_username,
            upstream_roles=upstream_roles,
            upstream_groups=upstream_groups,
            log_event="redirect-login-complete",
        )

    async def get_live_session(self, session_id: str | None) -> SessionData | None:
        session = self.sessions.get_session(session_id)
        if not session:
            return None
        return await self._refresh_session_credentials_if_needed(session)

    def get_session_snapshot(self, session_id: str | None) -> SessionSnapshot:
        session = self.sessions.get_session(session_id)
        snapshot = self.sessions.snapshot(session)
        if not session:
            return snapshot

        return snapshot.model_copy(
            update={
                "server_state": self.repo.get_user_server_state(self._user_key(session.user.preferred_username)),
            }
        )

    def get_session_snapshot_for_session(self, session: SessionData | None) -> SessionSnapshot:
        snapshot = self.sessions.snapshot(session)
        if not session:
            return snapshot
        return snapshot.model_copy(
            update={
                "server_state": self.repo.get_user_server_state(self._user_key(session.user.preferred_username)),
            }
        )

    def get_preferences(self, session: SessionData) -> SessionPreferences:
        return session.preferences

    async def refresh_capabilities(
        self,
        session: SessionData,
        payload: PermissionRefreshRequest | None = None,
    ):
        capabilities = self._snapshot_capabilities(session.server)
        request = payload or PermissionRefreshRequest()
        existing_job = next(
            (
                candidate
                for candidate in self.jobs.list_jobs(session.user.preferred_username)
                if candidate.server_id == session.server.id
                and candidate.job_type == JobType.PERMISSION_REFRESH
                and candidate.status in {JobStatus.PENDING, JobStatus.RUNNING}
                and candidate.updated_at >= utcnow() - timedelta(minutes=2)
            ),
            None,
        )
        if existing_job is not None:
            capabilities = capabilities.model_copy(update={"permission_refresh_job_id": existing_job.id})
            return self.sessions.update_capabilities(session, capabilities).capabilities
        job = self.jobs.create_job(
            job_type=JobType.PERMISSION_REFRESH,
            title="Refresh Teamwork Cloud permissions",
            owner=session.user.preferred_username,
            server_id=session.server.id,
            payload=request.model_dump(),
        )

        async def handler(context) -> dict[str, Any]:
            await context.report(10, "Refreshing the current user's effective TWC permissions")
            live_session = self.sessions.get_session(session.session_id) or session
            try:
                live_session = await self._refresh_session_credentials_if_needed(live_session)
                refreshed_at, delta = await self._refresh_permission_snapshot_guarded(
                    live_session,
                    reason="manual-capability-project-refresh",
                    refresh_shared_inventory=False,
                    priority_project_id=request.selected_project_id,
                    priority_branch_id=request.selected_branch_id,
                )
            except Exception as exc:
                self._mark_permission_refresh_failure(
                    live_session,
                    exc,
                    reason="manual-capability-project-refresh",
                )
                raise
            await context.report(95, "Permission snapshot replaced; reconciling visible projects")
            projects = await self.list_projects(live_session, refresh=False)
            return {
                **delta,
                "refreshed_at": refreshed_at.isoformat(),
                "project_ids": [project.id for project in projects],
                "selected_project_id": request.selected_project_id,
                "selected_branch_id": request.selected_branch_id,
                "selected_model_id": request.selected_model_id,
            }

        self.jobs.submit(job, handler)
        capabilities = capabilities.model_copy(update={"permission_refresh_job_id": job.id})
        updated_session = self.sessions.update_capabilities(session, capabilities)
        logger.info(
            "twc-capability-refresh-queued",
            user=updated_session.user.preferred_username,
            server_id=updated_session.server.id,
            permission_refresh_job_id=job.id,
        )
        return updated_session.capabilities

    def _snapshot_capabilities(self, server: ServerProfile) -> CapabilitySummary:
        version = server.version.value if server.version != TWCVersion.AUTO else "2024x"
        capabilities = {
            "repository": Capability(
                name="repository",
                state=CapabilityState.READY,
                reason="Project and branch browsing uses stored Cameo Workbench snapshots.",
                source="workbench-snapshot",
            ),
            "models": Capability(
                name="models",
                state=CapabilityState.READY,
                reason="Models and elements are supplied by Cameo Workbench snapshots, not REST traversal.",
                source="workbench-snapshot",
            ),
            "revisiondiff": Capability(
                name="revisiondiff",
                state=CapabilityState.READY,
                reason="Branch and project comparison uses stored snapshot contents.",
                source="workbench-snapshot",
            ),
            "edit": Capability(
                name="edit",
                state=CapabilityState.READY,
                reason="Explicit saves remain guarded by the stored TWC permission snapshot.",
                source="permission-snapshot",
            ),
            "user_access": Capability(
                name="user_access",
                state=CapabilityState.READY,
                reason="TWC remains the authority for current-user, group, role, and scoped resource permissions.",
                source="twc-permissions",
            ),
        }
        return CapabilitySummary(
            detected_version=version,
            reachable_endpoints={"permissions": True},
            capabilities=capabilities,
        )

    def update_preferences(self, session: SessionData, preferences: SessionPreferences) -> SessionPreferences:
        return self.sessions.update_preferences(session, preferences).preferences

    def get_workbench_agent_status(self, session: SessionData) -> WorkbenchAgentStatus:
        secret = self._workbench_agent_secret(session)
        kb_status = self._three_ds_kb_status()
        if secret is None:
            return WorkbenchAgentStatus(
                configured=False,
                **kb_status,
                message="Map an Open WebUI model here to use your stored project data as agent knowledge inside Workbench.",
            )
        return WorkbenchAgentStatus(
            configured=True,
            base_url=secret.base_url,
            model_id=secret.model_id or None,
            model_name=secret.model_name or None,
            has_api_key=bool(secret.api_key),
            knowledge_file_id=secret.knowledge_file_id,
            knowledge_file_name=secret.knowledge_file_name,
            knowledge_project_id=secret.knowledge_project_id,
            knowledge_branch_id=secret.knowledge_branch_id,
            reference_file_id=secret.reference_file_id,
            reference_file_name=secret.reference_file_name,
            reference_synced_at=secret.reference_synced_at,
            updated_at=secret.updated_at,
            knowledge_synced_at=secret.knowledge_synced_at,
            **kb_status,
            message="Open WebUI agent mapping is ready. Sync a branch knowledge bundle or start chatting.",
        )

    def set_workbench_agent_config(self, session: SessionData, payload: WorkbenchAgentConfigRequest) -> WorkbenchAgentStatus:
        base_url = self._normalize_openwebui_base_url(payload.base_url)
        api_key = payload.api_key.strip()
        if not base_url:
            raise ValueError("Open WebUI base URL is required.")
        existing = self._workbench_agent_secret(session)
        if not api_key:
            if existing and existing.base_url == base_url and existing.api_key:
                api_key = existing.api_key
            else:
                raise ValueError("Open WebUI API key is required the first time you save a connection or when changing the base URL.")
        secret = WorkbenchAgentSecret(
            base_url=base_url,
            api_key=api_key,
            model_id=payload.model_id.strip(),
            model_name=payload.model_name.strip(),
            knowledge_file_id=existing.knowledge_file_id if existing and existing.base_url == base_url and existing.model_id == payload.model_id.strip() else None,
            knowledge_file_name=existing.knowledge_file_name if existing and existing.base_url == base_url and existing.model_id == payload.model_id.strip() else None,
            knowledge_project_id=existing.knowledge_project_id if existing and existing.base_url == base_url and existing.model_id == payload.model_id.strip() else None,
            knowledge_branch_id=existing.knowledge_branch_id if existing and existing.base_url == base_url and existing.model_id == payload.model_id.strip() else None,
            reference_file_id=existing.reference_file_id if existing and existing.base_url == base_url else None,
            reference_file_name=existing.reference_file_name if existing and existing.base_url == base_url else None,
            reference_fingerprint=existing.reference_fingerprint if existing and existing.base_url == base_url else None,
            reference_synced_at=existing.reference_synced_at if existing and existing.base_url == base_url else None,
            knowledge_synced_at=existing.knowledge_synced_at if existing and existing.base_url == base_url and existing.model_id == payload.model_id.strip() else None,
            updated_at=utcnow(),
        )
        self._store_workbench_agent_secret(session, secret)
        return self.get_workbench_agent_status(session).model_copy(
            update={"message": "Open WebUI agent mapping saved in encrypted Workbench storage."}
        )

    def clear_workbench_agent_config(self, session: SessionData) -> WorkbenchAgentStatus:
        self.repo.delete_app_secret(self._workbench_agent_scope(session.server.id, self._user_key(session.user.preferred_username)))
        return WorkbenchAgentStatus(
            configured=False,
            **self._three_ds_kb_status(),
            message="Open WebUI agent mapping cleared for this Workbench user.",
        )

    async def list_openwebui_models(self, session: SessionData) -> list[OpenWebUIModelEntry]:
        secret = self._workbench_agent_secret(session)
        if secret is None:
            raise ValueError("Save an Open WebUI base URL and API key before loading models.")
        url = f"{secret.base_url}/api/models"
        try:
            async with httpx.AsyncClient(timeout=30.0, verify=False, follow_redirects=True) as client:
                response = await client.get(url, headers=self._openwebui_headers(secret.api_key))
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Open WebUI model listing failed: {self._openwebui_http_error_message(exc)}") from exc
        if response.status_code >= 400:
            raise RuntimeError(f"Open WebUI model listing failed: {response.text or response.reason_phrase}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Open WebUI did not return JSON for /api/models.") from exc
        return self._parse_openwebui_models(payload)

    async def sync_workbench_agent_knowledge(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
    ) -> WorkbenchAgentKnowledgeStatus:
        secret = self._workbench_agent_secret(session)
        if secret is None:
            raise ValueError("Save an Open WebUI mapping before syncing knowledge.")
        if not secret.model_id:
            raise ValueError("Choose an Open WebUI agent or model before syncing knowledge.")

        summary = self.get_branch_cache_summary_for_user(session.server.id, session.user.preferred_username, project_id, branch_id)
        if summary is None:
            raise ValueError("The selected stored project branch is not available to this Workbench user.")

        reference_file_id, reference_file_name, reference_stats, reference_fingerprint = await self._ensure_workbench_reference_knowledge(secret)
        file_name, file_content, bundle_stats = self._build_workbench_agent_knowledge_document(session, project_id, branch_id)
        file_id = await self._upload_openwebui_markdown_file(secret, file_name, file_content)

        updated_secret = secret.model_copy(
            update={
                "knowledge_file_id": file_id,
                "knowledge_file_name": file_name,
                "knowledge_project_id": project_id,
                "knowledge_branch_id": branch_id,
                "knowledge_synced_at": utcnow(),
                "reference_file_id": reference_file_id,
                "reference_file_name": reference_file_name,
                "reference_fingerprint": reference_fingerprint,
                "reference_synced_at": secret.reference_synced_at if secret.reference_fingerprint == reference_fingerprint else utcnow(),
                "updated_at": utcnow(),
            }
        )
        self._store_workbench_agent_secret(session, updated_secret)
        return WorkbenchAgentKnowledgeStatus(
            project_id=project_id,
            branch_id=branch_id,
            knowledge_file_id=file_id,
            knowledge_file_name=file_name,
            reference_file_id=reference_file_id,
            reference_file_name=reference_file_name,
            synced_at=updated_secret.knowledge_synced_at or utcnow(),
            **bundle_stats,
            **reference_stats,
            message="Open WebUI processed the branch model file and the persistent Workbench + 3DS 2024x reference file. Every Workbench Agent chat attaches both sources.",
        )

    def submit_workbench_agent_knowledge_sync(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
    ) -> JobRecord:
        secret = self._workbench_agent_secret(session)
        if secret is None:
            raise ValueError("Save an Open WebUI mapping before syncing knowledge.")
        if not secret.model_id:
            raise ValueError("Choose an Open WebUI agent or model before syncing knowledge.")
        summary = self.get_branch_cache_summary_for_user(
            session.server.id,
            session.user.preferred_username,
            project_id,
            branch_id,
        )
        if summary is None:
            raise ValueError("The selected stored project branch is not available to this Workbench user.")

        for existing in self.jobs.list_jobs(session.user.preferred_username):
            if (
                existing.server_id == session.server.id
                and existing.job_type == JobType.AGENT_KNOWLEDGE
                and existing.status in {JobStatus.PENDING, JobStatus.RUNNING}
                and existing.payload.get("project_id") == project_id
                and existing.payload.get("branch_id") == branch_id
            ):
                return existing

        job = self.jobs.create_job(
            job_type=JobType.AGENT_KNOWLEDGE,
            title=f"Agent knowledge: {project_id}/{branch_id}",
            owner=session.user.preferred_username,
            server_id=session.server.id,
            payload={"project_id": project_id, "branch_id": branch_id},
        )

        async def handler(context):
            await context.report(5, "Preparing the Workbench + 3DS reference and branch model knowledge files.")
            result = await self.sync_workbench_agent_knowledge(session, project_id, branch_id)
            await context.report(100, "Open WebUI finished processing both Workbench Agent knowledge files.")
            return result.model_dump(mode="json")

        return self.jobs.submit(job, handler)

    async def run_workbench_agent_chat(
        self,
        session: SessionData,
        payload: WorkbenchAgentChatRequest,
    ) -> WorkbenchAgentChatResponse:
        secret = self._workbench_agent_secret(session)
        if secret is None:
            raise ValueError("Save an Open WebUI mapping before using Workbench Agent.")
        if not secret.model_id:
            raise ValueError("Choose an Open WebUI agent or model before chatting.")
        if not payload.messages:
            raise ValueError("At least one message is required.")

        working_secret = secret
        if payload.sync_knowledge and (
            not secret.knowledge_file_id
            or secret.knowledge_project_id != payload.project_id
            or secret.knowledge_branch_id != payload.branch_id
        ):
            await self.sync_workbench_agent_knowledge(session, payload.project_id, payload.branch_id)
            working_secret = self._workbench_agent_secret(session) or secret

        if not working_secret.knowledge_file_id:
            raise ValueError("Sync the current project branch knowledge before chatting with Workbench Agent.")

        reference_file_id, reference_file_name, _, reference_fingerprint = await self._ensure_workbench_reference_knowledge(working_secret)
        if working_secret.reference_file_id != reference_file_id or working_secret.reference_fingerprint != reference_fingerprint:
            working_secret = working_secret.model_copy(
                update={
                    "reference_file_id": reference_file_id,
                    "reference_file_name": reference_file_name,
                    "reference_fingerprint": reference_fingerprint,
                    "reference_synced_at": utcnow(),
                    "updated_at": utcnow(),
                }
            )
            self._store_workbench_agent_secret(session, working_secret)

        request_messages = [
            {"role": "system", "content": self._workbench_agent_system_prompt(session, payload.project_id, payload.branch_id)},
            *[message.model_dump() for message in payload.messages],
        ]
        request_body = {
            "model": working_secret.model_id,
            "messages": request_messages,
            "files": [
                {"type": "file", "id": reference_file_id, "status": "processed"},
                {"type": "file", "id": working_secret.knowledge_file_id, "status": "processed"},
            ],
        }
        chat_timeout = httpx.Timeout(connect=30.0, read=300.0, write=120.0, pool=60.0)
        try:
            async with httpx.AsyncClient(timeout=chat_timeout, verify=False, follow_redirects=True) as client:
                response = await client.post(
                    f"{working_secret.base_url}/api/chat/completions",
                    headers={
                        "Authorization": f"Bearer {working_secret.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=request_body,
                )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Open WebUI chat request failed: {self._openwebui_http_error_message(exc)}") from exc
        if response.status_code >= 400:
            raise RuntimeError(f"Open WebUI chat request failed: {response.text or response.reason_phrase}")
        try:
            raw_payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Open WebUI did not return JSON for the chat completion request.") from exc

        return WorkbenchAgentChatResponse(
            model_id=working_secret.model_id,
            model_name=working_secret.model_name or working_secret.model_id,
            assistant_message=self._openwebui_assistant_message(raw_payload),
            knowledge_file_id=working_secret.knowledge_file_id,
            knowledge_file_name=working_secret.knowledge_file_name,
            raw_response=raw_payload if isinstance(raw_payload, dict) else {"payload": raw_payload},
            message="Workbench Agent used the mapped Open WebUI model with both the persistent Workbench + 3DS reference and the accessible branch model attached.",
        )

    def add_bookmark(self, session: SessionData, bookmark: Bookmark) -> list[Bookmark]:
        return self.sessions.upsert_bookmark(session, bookmark).bookmarks

    def delete_bookmark(self, session: SessionData, bookmark_id: str) -> list[Bookmark]:
        return self.sessions.delete_bookmark(session, bookmark_id).bookmarks

    def save_search(self, session: SessionData, saved_search: SavedSearch) -> list[SavedSearch]:
        return self.sessions.upsert_saved_search(session, saved_search).saved_searches

    def delete_search(self, session: SessionData, search_id: str) -> list[SavedSearch]:
        return self.sessions.delete_saved_search(session, search_id).saved_searches

    def add_recent(self, session: SessionData, bookmark: Bookmark) -> list[Bookmark]:
        return self.sessions.add_recent_item(session, bookmark).recent_items

    async def dashboard(self, session: SessionData) -> DashboardPayload:
        projects = await self.list_projects(session, refresh=False)
        logger.info("twc-project-list-dashboard", user=session.user.preferred_username, server_id=session.server.id, delivered_count=len(projects))
        return DashboardPayload(
            projects=projects,
            recent_items=session.recent_items,
            bookmarks=session.bookmarks,
            capability_badges=list(session.capabilities.capabilities.values()),
            active_jobs=[],
            publish_presets=[],
        )

    async def list_projects(self, session: SessionData, refresh: bool = False):
        # A user cannot select a plugin-backed project until it appears in this
        # list, so project discovery must establish that user's TWC branch
        # access before applying the cached visibility filter. Without this
        # bootstrap, only the snapshot publisher or users already present in a
        # stored access manifest can ever discover newly shared projects.
        await self._ensure_plugin_listing_permissions(session, force=refresh)
        projects = self._project_summaries_from_cache_for_user(session)
        self.repo.delete_user_cache(
            self._user_key(session.user.preferred_username),
            session.server.id,
            PROJECT_LIST_CACHE_KEY,
        )
        logger.info("twc-project-list-ui", user=session.user.preferred_username, server_id=session.server.id, delivered_count=len(projects))
        return projects

    async def list_project_branches(self, session: SessionData, project_id: str, workspace_id: str | None = None, refresh: bool = False):
        # Always filter branch names from the current stored permission
        # snapshot; a pre-refresh UI cache must not survive a revocation.
        branches = self._branch_summaries_from_cache_for_user(session, project_id)
        logger.info(
            "twc-branch-list-ui",
            user=session.user.preferred_username,
            server_id=session.server.id,
            project_id=project_id,
            workspace_id=workspace_id,
            delivered_count=len(branches),
        )
        return branches

    def _project_summaries_from_cache_for_user(self, session: SessionData) -> list[ProjectSummary]:
        cached_projects = self.list_cached_projects_for_user(session.server.id, session.user.preferred_username)
        projects: list[ProjectSummary] = []
        for project in cached_projects:
            plugin_branches = [branch for branch in project.branches if self._is_plugin_managed_summary(branch)]
            if not plugin_branches:
                continue
            projects.append(ProjectSummary(
                id=project.project_id,
                name=project.project_name,
                description="Stored Cameo Workbench snapshot with TWC-scoped user access",
                favorite=False,
                branches=[
                    BranchSummary(
                        id=branch.branch_id,
                        name=branch.branch_name,
                        description=f"Stored branch model cache ({branch.status.value})",
                    )
                    for branch in sorted(plugin_branches, key=lambda item: ((item.branch_name or item.branch_id).lower(), item.branch_id))
                ],
                workspace_id=project.workspace_id,
                resource_id=project.project_id,
            ))
        return projects

    def _branch_summaries_from_cache_for_user(self, session: SessionData, project_id: str) -> list[BranchSummary]:
        cached_projects = self.list_cached_projects_for_user(session.server.id, session.user.preferred_username)
        for project in cached_projects:
            if project.project_id != project_id:
                continue
            return [
                BranchSummary(
                    id=branch.branch_id,
                    name=branch.branch_name,
                    description=f"Stored branch model cache ({branch.status.value})",
                )
                for branch in sorted(
                    (item for item in project.branches if self._is_plugin_managed_summary(item)),
                    key=lambda item: ((item.branch_name or item.branch_id).lower(), item.branch_id),
                )
            ]
        return []

    async def get_model_tree(
        self,
        session: SessionData,
        project_id: str | None,
        branch_id: str | None,
        workspace_id: str | None = None,
        refresh: bool = False,
        depth: int | None = None,
    ):
        if not project_id or not branch_id:
            return []
        cache_key = self._tree_cache_key(project_id, branch_id)
        use_branch_materialized_cache = bool(project_id and branch_id)
        if cache_key and not refresh and not use_branch_materialized_cache:
            cached_tree = self._cached_model_list(session, cache_key, TreeNode)
            if cached_tree is not None:
                return cached_tree

        summary = self.repo.get_branch_cache_summary(session.server.id, project_id, branch_id)
        if summary is not None:
            await self._ensure_plugin_branch_permissions(
                session,
                project_id,
                branch_id,
                workspace_id=workspace_id,
                summary=summary,
                force=refresh,
            )
            materialized_tree = self._materialized_model_tree(session, project_id, branch_id, depth=depth)
            return materialized_tree or []

        raise RuntimeError(self._fallback_cache_missing_message(project_id, branch_id))

    async def get_project_usages(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
        workspace_id: str | None = None,
        refresh: bool = False,
    ) -> ProjectUsageResponse:
        summary = self.repo.get_branch_cache_summary(session.server.id, project_id, branch_id)
        if summary is None:
            raise RuntimeError(self._fallback_cache_missing_message(project_id, branch_id))
        await self._ensure_plugin_branch_permissions(
            session,
            project_id,
            branch_id,
            workspace_id=workspace_id,
            summary=summary,
            force=refresh,
        )
        models = self._visible_cached_models_for_user(
            self._user_key(session.user.preferred_username),
            session.server.id,
            project_id,
            branch_id,
        )
        if not models:
            return ProjectUsageResponse(project_id=project_id, branch_id=branch_id)

        explicitly_primary = [model for model in models if bool(model.payload.get("primary"))]
        primary = explicitly_primary[0] if explicitly_primary else models[0]
        source = "snapshot" if explicitly_primary else "legacy-snapshot-inferred"
        items = [
            ProjectUsageSummary(
                id=model.model_id,
                model_id=model.model_id,
                name=model.name or str(model.payload.get("human_name") or model.payload.get("name") or model.model_id),
                qualified_name=str(model.payload.get("qualified_name") or ""),
                usage_type=str(model.payload.get("usage_type") or "attached"),
                version=(str(model.payload.get("version")) if model.payload.get("version") else None),
                uri=(str(model.payload.get("resource_uri")) if model.payload.get("resource_uri") else None),
                automatic=(bool(model.payload.get("automatic")) if model.payload.get("automatic") is not None else None),
            )
            for model in models
            if model.model_id != primary.model_id
        ]
        return ProjectUsageResponse(
            project_id=project_id,
            branch_id=branch_id,
            primary_model_id=primary.model_id,
            primary_model_name=primary.name,
            total=len(items),
            source=source,
            items=items,
        )

    async def get_model_tree_children(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
        parent_id: str,
        workspace_id: str | None = None,
        model_id: str | None = None,
        refresh: bool = False,
    ) -> list[TreeNode]:
        summary = self.repo.get_branch_cache_summary(session.server.id, project_id, branch_id)
        if summary is not None:
            if refresh or not self._plugin_branch_permissions_known_for_user(
                session,
                project_id,
                branch_id,
                summary=summary,
            ):
                await self._ensure_plugin_branch_permissions(
                    session,
                    project_id,
                    branch_id,
                    workspace_id=workspace_id,
                    summary=summary,
                    force=refresh,
                )
            response = self.get_cached_branch_children_for_user(
                session.server.id,
                session.user.preferred_username,
                project_id,
                branch_id,
                parent_id,
                model_id=model_id,
            )
            return response.items

        raise RuntimeError(self._fallback_cache_missing_message(project_id, branch_id))

    async def discover_elements(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
        workspace_id: str | None = None,
        refresh: bool = False,
    ) -> ElementDiscoveryResult:
        cache_key = self._element_discovery_cache_key(project_id, branch_id)
        summary = self.repo.get_branch_cache_summary(session.server.id, project_id, branch_id)
        resolved_workspace_id = workspace_id or (summary.workspace_id if summary is not None else None)
        if summary is not None:
            if refresh or not self._plugin_branch_permissions_known_for_user(
                session,
                project_id,
                branch_id,
                summary=summary,
            ):
                await self._ensure_plugin_branch_permissions(
                    session,
                    project_id,
                    branch_id,
                    workspace_id=resolved_workspace_id,
                    summary=summary,
                    force=refresh,
                )
            materialized = self._materialized_element_discovery(session, project_id, branch_id, summary)
            if materialized is not None:
                self.repo.upsert_user_cache(
                    self._user_key(session.user.preferred_username),
                    session.server.id,
                    cache_key,
                    json.loads(materialized.model_dump_json()),
                )
                return materialized

            result = ElementDiscoveryResult(
                project_id=project_id,
                branch_id=branch_id,
                workspace_id=resolved_workspace_id,
                latest_revision=summary.latest_revision if summary is not None else None,
                seed_source="plugin-model-cache",
                seed_ids=[],
                ids=[],
                entries=[],
                total_ids=0,
                traversed_elements=0,
                hydrated_elements=0,
                batch_count=0,
                batch_size=0,
                cache_status="cache-hit",
                warnings=[
                    "This branch is served from the stored Workbench model cache.",
                    "No accessible cached elements are available for the active TWC session on this branch.",
                    *([summary.message] if summary and summary.message else []),
                ],
            )
            self.repo.upsert_user_cache(
                self._user_key(session.user.preferred_username),
                session.server.id,
                cache_key,
                json.loads(result.model_dump_json()),
            )
            return result

        raise RuntimeError(self._fallback_cache_missing_message(project_id, branch_id))

    async def submit_branch_cache_sync(self, session: SessionData, request: BranchCacheSyncRequest) -> JobRecord:
        raise RuntimeError(
            "TWC REST model and element synchronization is disabled. "
            "Publish this branch from the Cameo Workbench plugin to populate its model snapshot."
        )

    async def handle_model_cache_webhook(
        self,
        registration_id: str,
        authorization_header: str | None,
        payload: Any,
    ) -> dict[str, Any]:
        registration = self.repo.get_branch_webhook_registration_by_id(registration_id)
        if registration is None:
            raise KeyError(registration_id)
        if not self._validate_branch_webhook_auth(registration, authorization_header):
            raise PermissionError("Invalid webhook credentials.")

        event_summary = self._summarize_webhook_payload(payload)
        registration = registration.model_copy(
            update={
                "last_event_at": utcnow(),
                "last_event_summary": event_summary,
                "updated_at": utcnow(),
                "status_message": "Webhook event received, but automatic background refresh is disabled. The branch refreshes only when a user views it.",
            }
        )
        self.repo.upsert_branch_webhook_registration(registration)
        return {"accepted": True, "queued": False, "message": registration.status_message}

    def get_branch_cache_summary(self, session: SessionData, project_id: str, branch_id: str) -> BranchCacheSummary:
        summary = self.repo.get_branch_cache_summary(session.server.id, project_id, branch_id)
        if summary is not None:
            if self._is_plugin_managed_summary(summary):
                visible_summary = self.get_branch_cache_summary_for_user(
                    session.server.id,
                    session.user.preferred_username,
                    project_id,
                    branch_id,
                )
                if visible_summary is not None:
                    return visible_summary
                raise PermissionError("The active Workbench user does not have access to this cached branch.")
            return summary
        return self._branch_cache_summary(
            session,
            project_id,
            branch_id,
            status=MaterializedCacheStatus.EMPTY,
            message="No materialized branch cache has been created yet.",
        )

    def get_branch_cache_snapshot(self, session: SessionData, project_id: str, branch_id: str) -> BranchCacheSnapshot:
        summary = self.get_branch_cache_summary(session, project_id, branch_id)
        snapshot = self.get_branch_cache_snapshot_for_user(
            session.server.id,
            session.user.preferred_username,
            project_id,
            branch_id,
        )
        if snapshot is not None:
            return snapshot
        return BranchCacheSnapshot(summary=summary, models=[])

    def get_cached_branch_model(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
        model_id: str,
    ) -> CachedModelView | None:
        return self.get_cached_branch_model_for_user(
            session.server.id,
            session.user.preferred_username,
            project_id,
            branch_id,
            model_id,
        )

    def list_cached_branch_elements(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
        *,
        model_id: str | None = None,
        search: str | None = None,
        limit: int = 200,
        offset: int = 0,
        all_results: bool = False,
    ) -> CachedElementQueryResponse:
        return self.list_cached_branch_elements_for_user(
            session.server.id,
            session.user.preferred_username,
            project_id,
            branch_id,
            model_id=model_id,
            search=search,
            limit=limit,
            offset=offset,
            all_results=all_results,
        )

    def search_cached_branch_elements(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
        *,
        query: str | None = None,
        item_type: str | None = None,
        metaclass: str | None = None,
        stereotype: str | None = None,
        owner_id: str | None = None,
        include_details: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> CacheElementSearchResponse:
        return self.search_cached_branch_elements_for_user(
            session.server.id,
            session.user.preferred_username,
            project_id,
            branch_id,
            query=query,
            item_type=item_type,
            metaclass=metaclass,
            stereotype=stereotype,
            owner_id=owner_id,
            include_details=include_details,
            limit=limit,
            offset=offset,
        )

    def search_cached_branch_elements_by_stereotype(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
        stereotype: str,
        *,
        include_details: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> StereotypeElementSearchResponse:
        return self.search_cached_branch_elements_by_stereotype_for_user(
            session.server.id,
            session.user.preferred_username,
            project_id,
            branch_id,
            stereotype,
            include_details=include_details,
            limit=limit,
            offset=offset,
        )

    def get_cached_branch_element(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
        element_id: str,
        *,
        model_id: str | None = None,
    ) -> CachedElementRecord | None:
        return self.get_cached_branch_element_for_user(
            session.server.id,
            session.user.preferred_username,
            project_id,
            branch_id,
            element_id,
            model_id=model_id,
        )

    def get_branch_ingest_state(self, server_id: str, project_id: str, branch_id: str) -> BranchIngestState:
        server = self._require_server(server_id, include_disabled=True)
        summary = self.repo.get_branch_cache_summary(server.id, project_id, branch_id)
        permission_attachment = self.repo.get_branch_permission_attachment(server.id, project_id, branch_id)
        if summary is None:
            return BranchIngestState(
                server_id=server.id,
                project_id=project_id,
                branch_id=branch_id,
                exists=False,
            )
        return BranchIngestState(
            server_id=summary.server_id,
            project_id=summary.project_id,
            branch_id=summary.branch_id,
            workspace_id=summary.workspace_id,
            exists=True,
            project_name=summary.project_name,
            branch_name=summary.branch_name,
            latest_revision=summary.latest_revision,
            snapshot_hash=summary.snapshot_hash,
            model_count=summary.model_count,
            element_count=summary.element_count,
            source_kind=summary.source_kind,
            source_user=summary.source_user,
            permission_manifest_source=permission_attachment.manifest.source if permission_attachment else None,
            permission_manifest_complete=bool(permission_attachment and permission_attachment.manifest.complete),
            permission_manifest_entry_count=len(permission_attachment.manifest.entries) if permission_attachment else 0,
            permission_manifest_attached_at=permission_attachment.attached_at if permission_attachment else None,
            updated_at=summary.updated_at,
        )

    def _normalize_snapshot_hash(self, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    def _permission_attachment_from_upload(
        self,
        server_id: str,
        project_id: str,
        branch_id: str,
        workspace_id: str | None,
        latest_revision: str | None,
        snapshot_hash: str | None,
        source_user: str,
        supplied_manifest: PermissionManifest | None,
        attached_at: datetime,
    ) -> BranchPermissionAttachment:
        normalized_user = self._user_key(source_user)
        if supplied_manifest is None:
            manifest = PermissionManifest(
                captured_at=attached_at,
                captured_by=source_user,
                source="cameo-plugin-publisher-evidence",
                complete=False,
                entries=[
                    PermissionManifestEntry(
                        scope_id=branch_id,
                        scope_type="project-branch",
                        principal_name=normalized_user,
                        principal_type="user",
                        role_name="Snapshot Publisher",
                        accessible=True,
                        editable=True,
                    )
                ],
                warnings=[
                    "The plugin did not provide a package permission manifest. Current TWC REST permissions must be captured at login."
                ],
            )
        else:
            entries = list(supplied_manifest.entries)
            if not any(
                self._user_key(entry.principal_name or entry.principal_id) == normalized_user
                and entry.scope_type in {"project", "project-branch"}
                for entry in entries
            ):
                entries.append(
                    PermissionManifestEntry(
                        scope_id=branch_id,
                        scope_type="project-branch",
                        principal_name=normalized_user,
                        principal_type="user",
                        role_name="Snapshot Publisher",
                        accessible=True,
                        editable=True,
                    )
                )
            manifest = supplied_manifest.model_copy(
                update={
                    "captured_by": supplied_manifest.captured_by or source_user,
                    "entries": entries,
                }
            )
        return BranchPermissionAttachment(
            server_id=server_id,
            project_id=project_id,
            branch_id=branch_id,
            workspace_id=workspace_id,
            latest_revision=latest_revision,
            snapshot_hash=snapshot_hash,
            manifest=manifest,
            attached_at=attached_at,
        )

    @staticmethod
    def _permission_attachment_acl_hash(attachment: BranchPermissionAttachment | None) -> str:
        if attachment is None:
            return ""
        entries = [entry.model_dump(mode="json") for entry in attachment.manifest.entries]
        entries.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), default=str))
        encoded = json.dumps(
            {"complete": attachment.manifest.complete, "entries": entries},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _snapshot_hash_document(
        self,
        models: list[dict[str, Any]],
        elements: list[dict[str, Any]],
    ) -> str:
        document = {
            "models": sorted(models, key=lambda item: str(item.get("model_id") or "")),
            "elements": sorted(elements, key=lambda item: str(item.get("element_id") or "")),
        }
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _snapshot_hash_from_ingest_payload(self, payload: BranchSnapshotIngestRequest) -> str:
        models = [
            {
                "model_id": model.model_id,
                "name": model.name,
                "human_name": model.human_name,
                "qualified_name": model.qualified_name,
                "owner_id": model.owner_id or "",
                "primary": model.primary,
                "usage_type": model.usage_type,
                "resource_uri": model.resource_uri or "",
                "root_element_ids": list(model.root_element_ids),
            }
            for model in payload.models
        ]
        elements = [
            {
                "element_id": element.element_id,
                "model_id": element.model_id or "",
                "local_id": element.local_id or "",
                "owner_id": element.owner_id or "",
                "name": element.name,
                "human_name": element.human_name,
                "qualified_name": element.qualified_name,
                "human_type": element.human_type,
                "metaclass": element.metaclass,
                "documentation": element.documentation,
                "diagram_type": element.diagram_type,
                "diagram_preview_format": element.diagram_preview_format,
                "diagram_preview_base64": element.diagram_preview_base64,
                "owned_element_ids": list(element.owned_element_ids),
                "applied_stereotype_ids": list(element.applied_stereotype_ids),
                "diagram_element_ids": list(element.diagram_element_ids),
                "attributes": element.attributes,
                "references": element.references,
                "spec_sections": element.spec_sections,
            }
            for element in payload.elements
        ]
        return self._snapshot_hash_document(models, elements)

    def ingest_branch_snapshot(self, payload: BranchSnapshotIngestRequest) -> BranchCacheSummary:
        server = self._require_server(payload.server_id, include_disabled=True)
        source_user = self._user_key(payload.source_user)
        ingested_at = utcnow()
        snapshot_hash = self._normalize_snapshot_hash(payload.snapshot_hash) or self._snapshot_hash_from_ingest_payload(payload)

        resolved_models = self._resolve_snapshot_model_records(server.id, payload, source_user, ingested_at)
        resolved_elements = self._resolve_snapshot_element_records(server.id, payload, resolved_models, source_user, ingested_at)
        repaired_models = self._repair_cached_model_roots(resolved_models, resolved_elements)
        element_counts_by_model: dict[str, int] = {}
        for record in resolved_elements:
            element_counts_by_model[record.model_id] = element_counts_by_model.get(record.model_id, 0) + 1

        finalized_models = [
            model.model_copy(update={"element_count": element_counts_by_model.get(model.model_id, 0)})
            for model in repaired_models
        ]
        permissions = [
            ModelPermissionSnapshot(
                user_id=source_user,
                server_id=server.id,
                project_id=payload.project_id,
                branch_id=payload.branch_id,
                workspace_id=payload.workspace_id,
                latest_revision=payload.revision_id,
                model_id=model.model_id,
                accessible=True,
                restricted=False,
                editable=True,
                source="cameo-plugin-ingest",
                payload={"source_user": payload.source_user, "source": payload.source},
                updated_at=ingested_at,
            )
            for model in finalized_models
        ]
        access_records = [
            BranchAccessRecord(
                user_id=source_user,
                server_id=server.id,
                project_id=payload.project_id,
                branch_id=payload.branch_id,
                workspace_id=payload.workspace_id,
                branch_name=payload.branch_name or payload.branch_id,
                latest_revision=payload.revision_id,
                accessible=True,
                editable=True,
                admin_access=False,
                roles=["Snapshot Publisher"],
                source="cameo-plugin-ingest",
                payload={"source_user": payload.source_user, "source": payload.source},
                updated_at=ingested_at,
            )
        ]
        permission_attachment = self._permission_attachment_from_upload(
            server.id,
            payload.project_id,
            payload.branch_id,
            payload.workspace_id,
            payload.revision_id,
            snapshot_hash,
            payload.source_user,
            payload.permission_manifest,
            ingested_at,
        )

        summary = BranchCacheSummary(
            server_id=server.id,
            project_id=payload.project_id,
            branch_id=payload.branch_id,
            workspace_id=payload.workspace_id,
            project_name=payload.project_name or payload.project_id,
            branch_name=payload.branch_name or payload.branch_id,
            latest_revision=payload.revision_id,
            status=MaterializedCacheStatus.READY,
            message="Stored from Cameo live model snapshot.",
            model_count=len(finalized_models),
            element_count=len(resolved_elements),
            snapshot_hash=snapshot_hash,
            source_kind=payload.source,
            source_user=payload.source_user,
            updated_at=ingested_at,
        )
        self.repo.run_in_transaction(
            lambda connection: self._store_ingested_branch_snapshot(
                connection,
                server.id,
                payload.project_id,
                payload.branch_id,
                source_user,
                finalized_models,
                resolved_elements,
                permissions,
                access_records,
                permission_attachment,
                summary,
            )
        )
        # A new uploaded branch changes the project set against which the
        # shared role/group inventory must be evaluated. Preserve the last
        # complete role-ID map, mark it dirty, and let the next Server
        # Administrator login replace it.
        self.repo.mark_server_permission_inventory_dirty(server.id)
        self.sessions.mark_server_permission_snapshots_due(server.id)
        if self._permission_inventory_dirty_notifier is not None:
            self._permission_inventory_dirty_notifier()
        self._write_branch_access_manifest(
            summary,
            self.repo.list_branch_access_records(server.id, payload.project_id, payload.branch_id),
        )
        self._invalidate_ingested_branch_caches(source_user, server.id, payload.project_id, payload.branch_id)
        return summary

    def ingest_branch_delta(self, payload: BranchDeltaIngestRequest) -> BranchCacheSummary:
        server = self._require_server(payload.server_id, include_disabled=True)
        existing_summary = self.repo.get_branch_cache_summary(server.id, payload.project_id, payload.branch_id)
        if existing_summary is None:
            raise ValueError("A branch snapshot must be ingested before deltas can be applied.")
        previous_permission_attachment = self.repo.get_branch_permission_attachment(
            server.id,
            payload.project_id,
            payload.branch_id,
        )
        existing_snapshot_hash = self._normalize_snapshot_hash(existing_summary.snapshot_hash)
        base_snapshot_hash = self._normalize_snapshot_hash(payload.base_snapshot_hash)
        target_snapshot_hash = self._normalize_snapshot_hash(payload.target_snapshot_hash)
        if not base_snapshot_hash:
            raise RuntimeError("A delta requires the full snapshot baseline fingerprint. Publish a full snapshot to rebaseline.")
        if not target_snapshot_hash:
            raise RuntimeError("A delta requires the target snapshot fingerprint. Publish a full snapshot to rebaseline.")
        if base_snapshot_hash and not existing_snapshot_hash:
            raise RuntimeError("Stored branch snapshot is missing a baseline fingerprint. Publish a full snapshot to rebaseline before applying deltas.")
        if existing_snapshot_hash and base_snapshot_hash and existing_snapshot_hash != base_snapshot_hash:
            raise RuntimeError("Stored branch snapshot has changed on the server. Publish a full snapshot to rebaseline before applying this delta.")

        source_user = self._user_key(payload.source_user)
        ingested_at = utcnow()

        added_models = self._resolve_delta_model_records(server.id, payload, payload.added_models, source_user, ingested_at)
        updated_models = self._resolve_delta_model_records(server.id, payload, payload.updated_models, source_user, ingested_at)
        summary_holder: dict[str, BranchCacheSummary] = {}

        def apply_delta(connection) -> None:
            if payload.removed_model_ids:
                self.repo.delete_cached_models_by_ids(
                    server.id,
                    payload.project_id,
                    payload.branch_id,
                    payload.removed_model_ids,
                    connection=connection,
                )

            if added_models or updated_models:
                self.repo.upsert_cached_models([*added_models, *updated_models], connection=connection)

            existing_models = {
                model.model_id: model
                for model in self.repo.list_cached_models(
                    server.id,
                    payload.project_id,
                    payload.branch_id,
                    connection=connection,
                )
            }
            resolved_added_elements = self._resolve_delta_element_records(
                server.id,
                payload,
                payload.added_elements,
                existing_models,
                source_user,
                ingested_at,
            )
            resolved_updated_elements = self._resolve_delta_element_records(
                server.id,
                payload,
                payload.updated_elements,
                existing_models,
                source_user,
                ingested_at,
            )
            if payload.removed_element_ids:
                self.repo.delete_cached_elements_by_ids(
                    server.id,
                    payload.project_id,
                    payload.branch_id,
                    payload.removed_element_ids,
                    connection=connection,
                )
            self.repo.upsert_cached_elements([*resolved_added_elements, *resolved_updated_elements], connection=connection)

            current_models = self._repair_cached_model_roots(
                self.repo.list_cached_models(
                    server.id,
                    payload.project_id,
                    payload.branch_id,
                    connection=connection,
                ),
                self.repo.list_cached_elements(
                    server.id,
                    payload.project_id,
                    payload.branch_id,
                    limit=500000,
                    offset=0,
                    connection=connection,
                ).items,
            )
            refreshed_models: list[CachedModelRecord] = []
            for model in current_models:
                refreshed_models.append(
                    model.model_copy(
                        update={
                            "latest_revision": payload.to_revision_id or existing_summary.latest_revision,
                            "element_count": self.repo.count_cached_elements_for_model(
                                server.id,
                                payload.project_id,
                                payload.branch_id,
                                model.model_id,
                                connection=connection,
                            ),
                            "synced_at": ingested_at,
                            "source_user": payload.source_user,
                        }
                    )
                )
            if refreshed_models:
                self.repo.upsert_cached_models(refreshed_models, connection=connection)

            permissions = [
                ModelPermissionSnapshot(
                    user_id=source_user,
                    server_id=server.id,
                    project_id=payload.project_id,
                    branch_id=payload.branch_id,
                    workspace_id=payload.workspace_id or existing_summary.workspace_id,
                    latest_revision=payload.to_revision_id or existing_summary.latest_revision,
                    model_id=model.model_id,
                    accessible=True,
                    restricted=False,
                    editable=True,
                    source="cameo-plugin-ingest",
                    payload={"source_user": payload.source_user, "source": payload.source},
                    updated_at=ingested_at,
                )
                for model in refreshed_models
            ]
            self.repo.replace_model_permissions_for_user_branch(
                source_user,
                server.id,
                payload.project_id,
                payload.branch_id,
                permissions,
                connection=connection,
            )
            self.repo.upsert_branch_access_records(
                [
                    BranchAccessRecord(
                        user_id=source_user,
                        server_id=server.id,
                        project_id=payload.project_id,
                        branch_id=payload.branch_id,
                        workspace_id=payload.workspace_id or existing_summary.workspace_id,
                        branch_name=payload.branch_name or existing_summary.branch_name or payload.branch_id,
                        latest_revision=payload.to_revision_id or existing_summary.latest_revision,
                        accessible=True,
                        editable=True,
                        admin_access=False,
                        roles=["Snapshot Publisher"],
                        source="cameo-plugin-ingest",
                        payload={"source_user": payload.source_user, "source": payload.source},
                        updated_at=ingested_at,
                    )
                ],
                connection=connection,
            )
            self.repo.upsert_branch_permission_attachment(
                self._permission_attachment_from_upload(
                    server.id,
                    payload.project_id,
                    payload.branch_id,
                    payload.workspace_id or existing_summary.workspace_id,
                    payload.to_revision_id or existing_summary.latest_revision,
                    target_snapshot_hash or existing_snapshot_hash,
                    payload.source_user,
                    payload.permission_manifest,
                    ingested_at,
                ),
                connection=connection,
            )

            summary_holder["summary"] = BranchCacheSummary(
                server_id=server.id,
                project_id=payload.project_id,
                branch_id=payload.branch_id,
                workspace_id=payload.workspace_id or existing_summary.workspace_id,
                project_name=payload.project_name or existing_summary.project_name or payload.project_id,
                branch_name=payload.branch_name or existing_summary.branch_name or payload.branch_id,
                latest_revision=payload.to_revision_id or existing_summary.latest_revision,
                status=MaterializedCacheStatus.READY,
                message="Stored Cameo delta into the published Workbench model.",
                model_count=len(refreshed_models),
                element_count=self.repo.count_cached_elements_for_branch(
                    server.id,
                    payload.project_id,
                    payload.branch_id,
                    connection=connection,
                ),
                last_job_id=existing_summary.last_job_id,
                snapshot_hash=target_snapshot_hash or existing_snapshot_hash,
                source_kind=payload.source,
                source_user=payload.source_user,
                updated_at=ingested_at,
            )
            self.repo.upsert_branch_cache_summary(summary_holder["summary"], connection=connection)

        self.repo.run_in_transaction(apply_delta)
        summary = summary_holder["summary"]
        current_permission_attachment = self.repo.get_branch_permission_attachment(
            server.id,
            payload.project_id,
            payload.branch_id,
        )
        if self._permission_attachment_acl_hash(previous_permission_attachment) != self._permission_attachment_acl_hash(current_permission_attachment):
            # A delta can change package/project ACL evidence even though the
            # global server role/group inventory remains unchanged. Re-evaluate
            # active users promptly without forcing a server-wide admin scan.
            self.sessions.mark_server_permission_snapshots_due(server.id)
        self._write_branch_access_manifest(
            summary,
            self.repo.list_branch_access_records(server.id, payload.project_id, payload.branch_id),
        )
        self._invalidate_ingested_branch_caches(source_user, server.id, payload.project_id, payload.branch_id)
        return summary

    def tombstone_ingested_branch(self, payload: BranchTombstoneRequest) -> BranchTombstoneRecord:
        server = self._require_server(payload.server_id, include_disabled=True)
        summary = self.repo.get_branch_cache_summary(server.id, payload.project_id, payload.branch_id)
        if summary is None:
            raise KeyError(payload.branch_id)
        if payload.expected_revision_id and payload.expected_revision_id != summary.latest_revision:
            raise RuntimeError(
                "The stored branch revision changed after this tombstone was prepared. Refresh branch state before retrying."
            )
        record = self.repo.tombstone_branch_cache(
            BranchTombstoneRecord(
                server_id=server.id,
                project_id=payload.project_id,
                branch_id=payload.branch_id,
                project_name=summary.project_name,
                branch_name=summary.branch_name,
                latest_revision=summary.latest_revision,
                source_user=payload.source_user,
                reason=payload.reason,
            )
        )
        manifest_root = (
            self.settings.resolved_data_dir / "access-manifests" / server.id / payload.project_id
        ).resolve()
        manifest_path = self._branch_access_manifest_file_path(
            server.id,
            payload.project_id,
            payload.branch_id,
        ).resolve()
        if manifest_path.parent == manifest_root:
            manifest_path.unlink(missing_ok=True)
        self.sessions.mark_server_permission_snapshots_due(server.id)
        self._invalidate_shared_branch_caches(server.id, payload.project_id, payload.branch_id)
        remaining_project_branches = [
            item
            for item in self.repo.list_branch_cache_summaries(server.id)
            if item.project_id == payload.project_id
        ]
        if not remaining_project_branches:
            self.repo.mark_server_permission_inventory_dirty(server.id)
            if self._permission_inventory_dirty_notifier is not None:
                self._permission_inventory_dirty_notifier()
        return record

    def list_branch_tombstones(
        self,
        session: SessionData,
        *,
        project_id: str | None = None,
        limit: int = 100,
    ) -> list[BranchTombstoneRecord]:
        return self.repo.list_branch_tombstones(session.server.id, project_id=project_id, limit=limit)

    def tombstone_ingested_project(self, payload: ProjectTombstoneRequest) -> ProjectTombstoneRecord:
        server = self._require_server(payload.server_id, include_disabled=True)
        summaries = [
            item
            for item in self.repo.list_branch_cache_summaries(server.id)
            if item.project_id == payload.project_id
        ]
        if not summaries:
            raise KeyError(payload.project_id)
        record = self.repo.tombstone_project_cache(
            ProjectTombstoneRecord(
                server_id=server.id,
                project_id=payload.project_id,
                project_name=summaries[0].project_name,
                source_user=payload.source_user,
                reason=payload.reason,
            ),
            expected_branch_ids=payload.expected_branch_ids,
        )
        for branch_id in record.branch_ids:
            manifest_path = self._branch_access_manifest_file_path(server.id, payload.project_id, branch_id)
            manifest_path.unlink(missing_ok=True)
            self._invalidate_shared_branch_caches(server.id, payload.project_id, branch_id)
        self.sessions.mark_server_permission_snapshots_due(server.id)
        self.repo.mark_server_permission_inventory_dirty(server.id)
        if self._permission_inventory_dirty_notifier is not None:
            self._permission_inventory_dirty_notifier()
        return record

    def list_project_tombstones(
        self,
        session: SessionData,
        *,
        limit: int = 100,
    ) -> list[ProjectTombstoneRecord]:
        return self.repo.list_project_tombstones(session.server.id, limit=limit)

    def _store_ingested_branch_snapshot(
        self,
        connection,
        server_id: str,
        project_id: str,
        branch_id: str,
        source_user: str,
        models: list[CachedModelRecord],
        elements: list[CachedElementRecord],
        permissions: list[ModelPermissionSnapshot],
        access_records: list[BranchAccessRecord],
        permission_attachment: BranchPermissionAttachment,
        summary: BranchCacheSummary,
    ) -> None:
        self.repo.delete_branch_models_except(
            server_id,
            project_id,
            branch_id,
            [model.model_id for model in models],
            connection=connection,
        )
        self.repo.upsert_cached_models(models, connection=connection)
        self.repo.replace_model_permissions_for_user_branch(
            source_user,
            server_id,
            project_id,
            branch_id,
            permissions,
            connection=connection,
        )
        self.repo.upsert_branch_access_records(access_records, connection=connection)
        self.repo.upsert_branch_permission_attachment(permission_attachment, connection=connection)
        for model in models:
            model_elements = [item for item in elements if item.model_id == model.model_id]
            self.repo.replace_cached_elements(
                server_id,
                project_id,
                branch_id,
                model.model_id,
                model_elements,
                connection=connection,
            )
        self.repo.upsert_branch_cache_summary(summary, connection=connection)

    def list_cached_projects_for_user(self, server_id: str, preferred_username: str) -> list[CacheProjectEntry]:
        self._require_server(server_id, include_disabled=True)
        user_id = self._user_key(preferred_username)
        projects: dict[str, CacheProjectEntry] = {}
        for summary in self.repo.list_branch_cache_summaries(server_id):
            if self._is_plugin_managed_summary(summary):
                branch_access = self._plugin_branch_access_or_source_fallback(
                    user_id,
                    server_id,
                    summary.project_id,
                    summary.branch_id,
                    summary,
                )
                if branch_access is None or not branch_access.accessible:
                    continue
                visible_model_count = summary.model_count
                visible_element_count = summary.element_count
            else:
                visible_models = self._visible_cached_models_for_user(user_id, server_id, summary.project_id, summary.branch_id)
                if not visible_models:
                    continue
                visible_model_count = len(visible_models)
                visible_element_count = sum(model.element_count for model in visible_models)
            project_entry = projects.setdefault(
                summary.project_id,
                CacheProjectEntry(
                    project_id=summary.project_id,
                    project_name=summary.project_name or summary.project_id,
                    workspace_id=summary.workspace_id,
                    branches=[],
                ),
            )
            project_entry.branches.append(
                CacheProjectBranchEntry(
                    branch_id=summary.branch_id,
                    branch_name=summary.branch_name or summary.branch_id,
                    latest_revision=summary.latest_revision,
                    status=summary.status,
                    model_count=visible_model_count,
                    element_count=visible_element_count,
                    updated_at=summary.updated_at,
                )
            )
        return sorted(projects.values(), key=lambda item: (item.project_name.lower(), item.project_id))

    def list_cached_servers_for_user(self, preferred_username: str) -> list[CacheServerEntry]:
        entries: list[CacheServerEntry] = []
        for server in self.repo.list_servers(include_disabled=True):
            projects = self.list_cached_projects_for_user(server.id, preferred_username)
            if not projects:
                continue
            branch_entries = [branch for project in projects for branch in project.branches]
            latest_updated = max((branch.updated_at for branch in branch_entries), default=None)
            entries.append(
                CacheServerEntry(
                    server_id=server.id,
                    server_name=server.name,
                    project_count=len(projects),
                    branch_count=len(branch_entries),
                    updated_at=latest_updated,
                )
            )
        return sorted(entries, key=lambda item: (item.server_name.lower(), item.server_id))

    def get_branch_access_manifest_status(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
    ) -> BranchAccessManifestStatus:
        summary = self.repo.get_branch_cache_summary(session.server.id, project_id, branch_id)
        if summary is None:
            return BranchAccessManifestStatus(
                server_id=session.server.id,
                project_id=project_id,
                branch_id=branch_id,
                source="none",
                message="No plugin snapshot is cached for this branch yet.",
            )
        if self._is_plugin_managed_summary(summary):
            current_user_access = self._require_effective_branch_access(session, project_id, branch_id)
        else:
            visible_models = self._visible_cached_models_for_user(
                self._user_key(session.user.preferred_username),
                session.server.id,
                project_id,
                branch_id,
            )
            if not visible_models:
                raise PermissionError("The active Workbench user does not have access to this project branch.")
            model_permissions = self._permissions_by_model_for_user(
                self._user_key(session.user.preferred_username),
                session.server.id,
                project_id,
                branch_id,
            )
            current_user_access = BranchAccessRecord(
                user_id=self._user_key(session.user.preferred_username),
                server_id=session.server.id,
                project_id=project_id,
                branch_id=branch_id,
                accessible=True,
                editable=any(
                    permission.editable
                    for permission in model_permissions.values()
                    if permission.accessible and not permission.restricted
                ),
                admin_access=False,
                source="legacy-model-permission-summary",
            )

        def with_current_user_access(status: BranchAccessManifestStatus) -> BranchAccessManifestStatus:
            return status.model_copy(
                update={
                    "current_user_accessible": current_user_access.accessible,
                    "current_user_editable": current_user_access.editable,
                    "current_user_admin_access": current_user_access.admin_access,
                    "current_user_branch_admin_access": self._branch_admin_access(current_user_access),
                    "current_user_access_admin_access": self._access_admin_access(current_user_access),
                }
            )

        records = self.repo.list_branch_access_records(session.server.id, project_id, branch_id)
        status = self._branch_access_manifest_status_from_records(summary, records)
        if not self._is_plugin_managed_summary(summary):
            return with_current_user_access(status.model_copy(update={"message": "This branch is not plugin-backed."}))
        if not records:
            return with_current_user_access(
                status.model_copy(update={"message": "No shared access map has been generated for this branch yet."})
            )
        return with_current_user_access(status)

    async def refresh_branch_access_manifest(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
    ) -> BranchAccessManifestStatus:
        summary = self.repo.get_branch_cache_summary(session.server.id, project_id, branch_id)
        if not self._is_plugin_managed_summary(summary):
            raise ValueError("Shared access maps can only be generated for plugin-backed branches.")
        self._require_effective_branch_access(session, project_id, branch_id, require_access_admin=True)
        records = await self._adapter_for_session(session).build_plugin_branch_access_manifest(
            project_id,
            branch_id,
            latest_revision=summary.latest_revision,
            workspace_id=summary.workspace_id,
        )
        refreshed_at = utcnow()
        normalized_records = [
            record.model_copy(
                update={
                    "server_id": session.server.id,
                    "project_id": project_id,
                    "branch_id": branch_id,
                    "workspace_id": summary.workspace_id,
                    "branch_name": summary.branch_name or branch_id,
                    "latest_revision": summary.latest_revision,
                    "updated_at": refreshed_at,
                }
            )
            for record in records
        ]
        # The shared role map is reporting data, not authorization data. It must
        # never overwrite the login/scheduled effective-permission snapshot.
        self._write_branch_access_manifest(summary, normalized_records)
        current_user_access = self._require_effective_branch_access(
            session,
            project_id,
            branch_id,
            require_access_admin=True,
        )
        return self._branch_access_manifest_status_from_records(summary, normalized_records).model_copy(
            update={
                "current_user_accessible": current_user_access.accessible,
                "current_user_editable": current_user_access.editable,
                "current_user_admin_access": current_user_access.admin_access,
                "current_user_branch_admin_access": self._branch_admin_access(current_user_access),
                "current_user_access_admin_access": self._access_admin_access(current_user_access),
                "message": f"Generated shared access map for {len(normalized_records)} users.",
            }
        )

    def get_branch_cache_summary_for_user(
        self,
        server_id: str,
        preferred_username: str,
        project_id: str,
        branch_id: str,
    ) -> BranchCacheSummary | None:
        self._require_server(server_id, include_disabled=True)
        summary = self.repo.get_branch_cache_summary(server_id, project_id, branch_id)
        if summary is None:
            return None
        if self._is_plugin_managed_summary(summary):
            branch_access = self._plugin_branch_access_or_source_fallback(
                self._user_key(preferred_username),
                server_id,
                project_id,
                branch_id,
                summary,
            )
            if branch_access is None or not branch_access.accessible:
                return None
            return summary
        visible_models = self._visible_cached_models_for_user(self._user_key(preferred_username), server_id, project_id, branch_id)
        if not visible_models:
            return None
        return summary.model_copy(
            update={
                "model_count": len(visible_models),
                "element_count": sum(model.element_count for model in visible_models),
            }
        )

    def get_branch_cache_snapshot_for_user(
        self,
        server_id: str,
        preferred_username: str,
        project_id: str,
        branch_id: str,
    ) -> BranchCacheSnapshot | None:
        self._require_server(server_id, include_disabled=True)
        summary = self.get_branch_cache_summary_for_user(server_id, preferred_username, project_id, branch_id)
        if summary is None:
            return None
        user_id = self._user_key(preferred_username)
        if self._is_plugin_managed_summary(summary):
            branch_access = self._plugin_branch_access_or_source_fallback(
                user_id,
                server_id,
                project_id,
                branch_id,
                summary,
            )
            if branch_access is None or not branch_access.accessible:
                return None
            models = [
                CachedModelView(
                    model=model,
                    permissions=self._plugin_permission_snapshot_from_branch_access(branch_access, model),
                )
                for model in self.repo.list_cached_models(server_id, project_id, branch_id)
            ]
            return BranchCacheSnapshot(summary=summary, models=models)
        permissions = self._permissions_by_model_for_user(user_id, server_id, project_id, branch_id)
        models = [
            CachedModelView(model=model, permissions=permissions.get(model.model_id))
            for model in self._visible_cached_models_for_user(user_id, server_id, project_id, branch_id)
        ]
        return BranchCacheSnapshot(summary=summary, models=models)

    def get_cached_branch_model_for_user(
        self,
        server_id: str,
        preferred_username: str,
        project_id: str,
        branch_id: str,
        model_id: str,
    ) -> CachedModelView | None:
        self._require_server(server_id, include_disabled=True)
        user_id = self._user_key(preferred_username)
        summary = self.repo.get_branch_cache_summary(server_id, project_id, branch_id)
        if self._is_plugin_managed_summary(summary):
            branch_access = self._plugin_branch_access_or_source_fallback(
                user_id,
                server_id,
                project_id,
                branch_id,
                summary,
            )
            if branch_access is None or not branch_access.accessible:
                return None
            model = self.repo.get_cached_model(server_id, project_id, branch_id, model_id)
            if model is None:
                return None
            return CachedModelView(model=model, permissions=self._plugin_permission_snapshot_from_branch_access(branch_access, model))
        permissions = self._permissions_by_model_for_user(user_id, server_id, project_id, branch_id)
        permission = permissions.get(model_id)
        if permission is None or not permission.accessible or permission.restricted:
            return None
        model = self.repo.get_cached_model(server_id, project_id, branch_id, model_id)
        if model is None:
            return None
        return CachedModelView(model=model, permissions=permission)

    def list_cached_branch_elements_for_user(
        self,
        server_id: str,
        preferred_username: str,
        project_id: str,
        branch_id: str,
        *,
        model_id: str | None = None,
        search: str | None = None,
        limit: int = 200,
        offset: int = 0,
        all_results: bool = False,
    ) -> CachedElementQueryResponse:
        self._require_server(server_id, include_disabled=True)
        user_id = self._user_key(preferred_username)
        if all_results:
            limit = max(self.repo.count_cached_elements_for_branch(server_id, project_id, branch_id), 1)
            offset = 0
        summary = self.repo.get_branch_cache_summary(server_id, project_id, branch_id)
        if self._is_plugin_managed_summary(summary):
            branch_access = self._plugin_branch_access_or_source_fallback(
                user_id,
                server_id,
                project_id,
                branch_id,
                summary,
            )
            if branch_access is None or not branch_access.accessible:
                return CachedElementQueryResponse(total=0, items=[])
            return self.repo.list_cached_elements(
                server_id,
                project_id,
                branch_id,
                model_id=model_id,
                search=search,
                limit=limit,
                offset=offset,
            )
        permissions = self._permissions_by_model_for_user(user_id, server_id, project_id, branch_id)
        visible_models = {
            permission.model_id
            for permission in permissions.values()
            if permission.accessible and not permission.restricted
        }
        if model_id is not None and model_id not in visible_models:
            return CachedElementQueryResponse(total=0, items=[])

        raw = self.repo.list_cached_elements(
            server_id,
            project_id,
            branch_id,
            model_id=model_id,
            search=search,
            limit=limit if model_id is not None else max(limit + offset, 1),
            offset=offset if model_id is not None else 0,
        )
        if model_id is not None:
            return raw
        filtered_items = [item for item in raw.items if item.model_id in visible_models]
        return CachedElementQueryResponse(total=len(filtered_items), items=filtered_items[offset : offset + limit])

    def search_cached_branch_elements_by_stereotype_for_user(
        self,
        server_id: str,
        preferred_username: str,
        project_id: str,
        branch_id: str,
        stereotype: str,
        *,
        include_details: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> StereotypeElementSearchResponse:
        self._require_server(server_id, include_disabled=True)
        query = stereotype.strip()
        if not query:
            return StereotypeElementSearchResponse(stereotype=stereotype, include_details=include_details)

        summary = self.repo.get_branch_cache_summary(server_id, project_id, branch_id)
        if summary is None:
            return StereotypeElementSearchResponse(stereotype=stereotype, include_details=include_details)

        visible_elements = self.list_cached_branch_elements_for_user(
            server_id,
            preferred_username,
            project_id,
            branch_id,
            limit=max(self.repo.count_cached_elements_for_branch(server_id, project_id, branch_id), 1),
            offset=0,
        ).items
        visible_by_id = {item.element_id: item for item in visible_elements}
        query_normalized = normalize_lookup_key(query)

        matched_stereotype_ids: set[str] = set()
        matched_stereotype_names: set[str] = set()
        matched_elements: list[CachedElementRecord] = []
        for element in visible_elements:
            applied_ids = [
                str(value).strip()
                for value in (element.payload.get("applied_stereotype_ids") or [])
                if str(value).strip()
            ]
            if not applied_ids:
                continue
            element_matches: list[tuple[str, str | None]] = []
            for stereotype_id in applied_ids:
                stereotype_record = visible_by_id.get(stereotype_id)
                stereotype_name = stereotype_record.name.strip() if stereotype_record and stereotype_record.name else None
                if normalize_lookup_key(stereotype_id) == query_normalized:
                    element_matches.append((stereotype_id, stereotype_name))
                    continue
                if stereotype_name and query_normalized in normalize_lookup_key(stereotype_name):
                    element_matches.append((stereotype_id, stereotype_name))
            if not element_matches:
                continue
            matched_elements.append(element)
            for matched_id, matched_name in element_matches:
                matched_stereotype_ids.add(matched_id)
                if matched_name:
                    matched_stereotype_names.add(matched_name)

        paged_items = matched_elements[offset : offset + limit]
        details: list[ItemDetails] = []
        if include_details:
            details = [
                detail
                for element in paged_items
                if (detail := self._cached_item_details_for_user(server_id, preferred_username, project_id, branch_id, element.element_id)) is not None
            ]

        return StereotypeElementSearchResponse(
            stereotype=stereotype,
            include_details=include_details,
            total=len(matched_elements),
            matched_stereotype_ids=sorted(matched_stereotype_ids, key=str.lower),
            matched_stereotype_names=sorted(matched_stereotype_names, key=str.lower),
            items=paged_items,
            details=details,
        )

    def _visible_cached_elements_for_user(
        self,
        user_id: str,
        server_id: str,
        project_id: str,
        branch_id: str,
        *,
        model_id: str | None = None,
    ) -> list[CachedElementRecord]:
        summary = self.repo.get_branch_cache_summary(server_id, project_id, branch_id)
        branch_total = max(self.repo.count_cached_elements_for_branch(server_id, project_id, branch_id), 1)
        if self._is_plugin_managed_summary(summary):
            branch_access = self._plugin_branch_access_or_source_fallback(
                user_id,
                server_id,
                project_id,
                branch_id,
                summary,
            )
            if branch_access is None or not branch_access.accessible:
                return []
            return self.repo.list_cached_elements(
                server_id,
                project_id,
                branch_id,
                model_id=model_id,
                limit=branch_total,
                offset=0,
            ).items

        visible_models = {
            permission.model_id
            for permission in self._permissions_by_model_for_user(user_id, server_id, project_id, branch_id).values()
            if permission.accessible and not permission.restricted
        }
        if model_id is not None and model_id not in visible_models:
            return []
        raw = self.repo.list_cached_elements(
            server_id,
            project_id,
            branch_id,
            model_id=model_id,
            limit=branch_total,
            offset=0,
        ).items
        return [item for item in raw if item.model_id in visible_models]

    def get_cached_branch_tree_for_user(
        self,
        server_id: str,
        preferred_username: str,
        project_id: str,
        branch_id: str,
        *,
        model_id: str | None = None,
        root_id: str | None = None,
        depth: int | None = None,
        include_orphans: bool = True,
    ) -> CacheTreeResponse:
        self._require_server(server_id, include_disabled=True)
        user_id = self._user_key(preferred_username)
        visible_models = self._visible_cached_models_for_user(user_id, server_id, project_id, branch_id)
        if model_id is not None:
            visible_models = [model for model in visible_models if model.model_id == model_id]

        if depth is not None and depth <= 0 and root_id is None:
            nodes = [
                TreeNode(
                    id=model.model_id,
                    label=model.name or model.model_id,
                    node_type="model",
                    path=f"{project_id}/{branch_id}/{model.name or model.model_id}",
                    children=[],
                    metadata={
                        "project_id": project_id,
                        "branch_id": branch_id,
                        "model_id": model.model_id,
                        "child_count": len(self._sanitize_model_root_ids(model, {})) or (1 if (model.element_count or 0) > 0 else 0),
                        "element_count": model.element_count or 0,
                        "root_count": len(self._sanitize_model_root_ids(model, {})),
                        "subtitle": f"{model.element_count or 0} published elements",
                    },
                )
                for model in visible_models
            ]
            return CacheTreeResponse(
                server_id=server_id,
                project_id=project_id,
                branch_id=branch_id,
                model_id=model_id,
                root_id=root_id,
                depth=depth,
                include_orphans=include_orphans,
                total_nodes=len(nodes),
                nodes=nodes,
            )

        nodes = [
            self._tree_nodes_for_model(
                project_id,
                branch_id,
                model,
                {
                    record.element_id: record
                    for record in self._visible_cached_elements_for_user(
                        user_id,
                        server_id,
                        project_id,
                        branch_id,
                        model_id=model.model_id,
                    )
                },
                root_id=root_id,
                depth=depth,
                include_orphans=include_orphans,
            )
            for model in visible_models
        ]

        if root_id is not None:
            nodes = [node for node in nodes if node.children or node.id == root_id or any(child.id == root_id for child in node.children)]

        return CacheTreeResponse(
            server_id=server_id,
            project_id=project_id,
            branch_id=branch_id,
            model_id=model_id,
            root_id=root_id,
            depth=depth,
            include_orphans=include_orphans,
            total_nodes=self._count_tree_nodes(nodes),
            nodes=nodes,
        )

    def get_cached_branch_children_for_user(
        self,
        server_id: str,
        preferred_username: str,
        project_id: str,
        branch_id: str,
        parent_id: str,
        *,
        model_id: str | None = None,
    ) -> CacheChildrenResponse:
        self._require_server(server_id, include_disabled=True)
        user_id = self._user_key(preferred_username)
        if model_id:
            visible_models = [model for model in self._visible_cached_models_for_user(user_id, server_id, project_id, branch_id) if model.model_id == model_id]
        else:
            visible_models = self._visible_cached_models_for_user(user_id, server_id, project_id, branch_id)

        for model in visible_models:
            if parent_id == model.model_id:
                items = self._tree_children_for_model_root(
                    server_id,
                    project_id,
                    branch_id,
                    model,
                )
                return CacheChildrenResponse(
                    server_id=server_id,
                    project_id=project_id,
                    branch_id=branch_id,
                    parent_id=parent_id,
                    model_id=model.model_id,
                    total_children=len(items),
                    items=items,
                )

            parent_record = self.repo.get_cached_element_tree_summary(
                server_id,
                project_id,
                branch_id,
                parent_id,
                model_id=model.model_id,
            )
            if parent_record is None:
                continue
            items = self._tree_children_for_parent(
                server_id,
                project_id,
                branch_id,
                model.model_id,
                parent_record,
            )
            return CacheChildrenResponse(
                server_id=server_id,
                project_id=project_id,
                branch_id=branch_id,
                parent_id=parent_id,
                model_id=model.model_id,
                total_children=len(items),
                items=items,
            )

        return CacheChildrenResponse(
            server_id=server_id,
            project_id=project_id,
            branch_id=branch_id,
            parent_id=parent_id,
            model_id=model_id,
            total_children=0,
            items=[],
        )

    def get_cached_branch_item_details_for_user(
        self,
        server_id: str,
        preferred_username: str,
        project_id: str,
        branch_id: str,
        element_id: str,
    ) -> ItemDetails | None:
        self._require_server(server_id, include_disabled=True)
        return self._cached_item_details_for_user(server_id, preferred_username, project_id, branch_id, element_id)

    def search_cached_branch_elements_for_user(
        self,
        server_id: str,
        preferred_username: str,
        project_id: str,
        branch_id: str,
        *,
        query: str | None = None,
        item_type: str | None = None,
        metaclass: str | None = None,
        stereotype: str | None = None,
        owner_id: str | None = None,
        include_details: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> CacheElementSearchResponse:
        self._require_server(server_id, include_disabled=True)
        user_id = self._user_key(preferred_username)
        visible_elements = self._visible_cached_elements_for_user(user_id, server_id, project_id, branch_id)
        visible_by_id = {item.element_id: item for item in visible_elements}
        query_normalized = normalize_lookup_key(query or "")
        item_type_normalized = normalize_lookup_key(item_type or "")
        metaclass_normalized = normalize_lookup_key(metaclass or "")
        stereotype_normalized = normalize_lookup_key(stereotype or "")
        owner_id_normalized = normalize_lookup_key(owner_id or "")

        matched_items: list[CachedElementRecord] = []
        for element in visible_elements:
            payload = element.payload or {}
            if owner_id_normalized and normalize_lookup_key(str(payload.get("owner_id") or "")) != owner_id_normalized:
                continue
            if item_type_normalized and item_type_normalized not in normalize_lookup_key(element.item_type or ""):
                continue
            if metaclass_normalized and metaclass_normalized not in normalize_lookup_key(str(payload.get("metaclass") or "")):
                continue
            if stereotype_normalized:
                applied_ids = [str(value).strip() for value in payload.get("applied_stereotype_ids") or [] if str(value).strip()]
                if not applied_ids:
                    continue
                stereotype_match = False
                for stereotype_id in applied_ids:
                    stereotype_record = visible_by_id.get(stereotype_id)
                    stereotype_name = stereotype_record.name if stereotype_record else ""
                    if normalize_lookup_key(stereotype_id) == stereotype_normalized:
                        stereotype_match = True
                        break
                    if stereotype_name and stereotype_normalized in normalize_lookup_key(stereotype_name):
                        stereotype_match = True
                        break
                if not stereotype_match:
                    continue
            if query_normalized:
                search_fields = [
                    element.name,
                    element.path,
                    element.item_type,
                    element.element_id,
                    str(payload.get("qualified_name") or ""),
                    str(payload.get("documentation") or ""),
                    str(payload.get("metaclass") or ""),
                ]
                haystack = " ".join(value for value in search_fields if value)
                if query_normalized not in normalize_lookup_key(haystack):
                    continue
            matched_items.append(element)

        matched_items.sort(key=lambda item: self._cached_element_sort_key(item, item.element_id))
        paged_items = matched_items[offset : offset + limit]
        details: list[ItemDetails] = []
        if include_details:
            details = [
                detail
                for element in paged_items
                if (detail := self._cached_item_details_for_user(server_id, preferred_username, project_id, branch_id, element.element_id)) is not None
            ]

        return CacheElementSearchResponse(
            query=query or "",
            item_type=item_type,
            metaclass=metaclass,
            stereotype=stereotype,
            owner_id=owner_id,
            include_details=include_details,
            total=len(matched_items),
            items=paged_items,
            details=details,
        )

    def _item_reference_from_cached_record(self, record: CachedElementRecord, relationship_type: str) -> ItemReference:
        return ItemReference(
            id=record.element_id,
            name=record.name or record.element_id,
            item_type=record.item_type or "item",
            relationship_type=relationship_type,
            path=record.path,
        )

    def get_cached_branch_element_graph_for_user(
        self,
        server_id: str,
        preferred_username: str,
        project_id: str,
        branch_id: str,
        element_id: str,
    ) -> CacheElementGraphResponse | None:
        self._require_server(server_id, include_disabled=True)
        item = self._cached_item_details_for_user(server_id, preferred_username, project_id, branch_id, element_id)
        if item is None:
            return None

        user_id = self._user_key(preferred_username)
        visible_elements = self._visible_cached_elements_for_user(user_id, server_id, project_id, branch_id)
        visible_by_id = {record.element_id: record for record in visible_elements}
        current_record = visible_by_id.get(element_id)

        owner_chain: list[ItemReference] = []
        seen_owner_ids: set[str] = set()
        owner_id = str(current_record.payload.get("owner_id") or "").strip() if current_record else ""
        while owner_id and owner_id not in seen_owner_ids:
            seen_owner_ids.add(owner_id)
            owner_record = visible_by_id.get(owner_id)
            if owner_record is None:
                break
            owner_chain.insert(0, self._item_reference_from_cached_record(owner_record, "owner"))
            owner_id = str(owner_record.payload.get("owner_id") or "").strip()

        incoming: list[ItemReference] = []
        incoming_seen: set[tuple[str, str]] = set()
        for candidate in visible_elements:
            if candidate.element_id == element_id:
                continue
            for field, values in (candidate.payload.get("references") or {}).items():
                if any(str(value).strip() == element_id for value in values or []):
                    key = (candidate.element_id, field)
                    if key in incoming_seen:
                        continue
                    incoming_seen.add(key)
                    incoming.append(self._item_reference_from_cached_record(candidate, field))

        stereotype_refs: list[ItemReference] = []
        for stereotype_id in [str(value).strip() for value in (current_record.payload.get("applied_stereotype_ids") or []) if str(value).strip()] if current_record else []:
            stereotype_record = visible_by_id.get(stereotype_id)
            if stereotype_record is not None:
                stereotype_refs.append(self._item_reference_from_cached_record(stereotype_record, "stereotype"))
            else:
                stereotype_refs.append(
                    ItemReference(
                        id=stereotype_id,
                        name=stereotype_id,
                        item_type="stereotype",
                        relationship_type="stereotype",
                        path="",
                    )
                )

        return CacheElementGraphResponse(
            server_id=server_id,
            project_id=project_id,
            branch_id=branch_id,
            element_id=element_id,
            model_id=current_record.model_id if current_record else None,
            item=item,
            owner_chain=owner_chain,
            contained_elements=item.contained_elements,
            type_references=item.type_references,
            related_items=item.related_items,
            incoming_references=incoming,
            stereotypes=stereotype_refs,
        )

    def get_cached_branch_element_for_user(
        self,
        server_id: str,
        preferred_username: str,
        project_id: str,
        branch_id: str,
        element_id: str,
        *,
        model_id: str | None = None,
    ) -> CachedElementRecord | None:
        self._require_server(server_id, include_disabled=True)
        user_id = self._user_key(preferred_username)
        summary = self.repo.get_branch_cache_summary(server_id, project_id, branch_id)
        if self._is_plugin_managed_summary(summary):
            branch_access = self._plugin_branch_access_or_source_fallback(
                user_id,
                server_id,
                project_id,
                branch_id,
                summary,
            )
            if branch_access is None or not branch_access.accessible:
                return None
            if model_id is not None:
                return self.repo.get_cached_element(server_id, project_id, branch_id, element_id, model_id=model_id)
            for model in self.repo.list_cached_models(server_id, project_id, branch_id):
                match = self.repo.get_cached_element(server_id, project_id, branch_id, element_id, model_id=model.model_id)
                if match is not None:
                    return match
            return None
        permissions = self._permissions_by_model_for_user(user_id, server_id, project_id, branch_id)
        visible_models = [
            permission.model_id
            for permission in permissions.values()
            if permission.accessible and not permission.restricted
        ]
        if model_id is not None:
            if model_id not in visible_models:
                return None
            return self.repo.get_cached_element(server_id, project_id, branch_id, element_id, model_id=model_id)
        for visible_model_id in visible_models:
            match = self.repo.get_cached_element(server_id, project_id, branch_id, element_id, model_id=visible_model_id)
            if match is not None:
                return match
        return None

    def _cached_item_details_for_user(
        self,
        server_id: str,
        preferred_username: str,
        project_id: str,
        branch_id: str,
        element_id: str,
    ) -> ItemDetails | None:
        record = self.get_cached_branch_element_for_user(server_id, preferred_username, project_id, branch_id, element_id)
        if record is None:
            return None

        branch_access = self._branch_access_for_user(self._user_key(preferred_username), server_id, project_id, branch_id)
        editable = False
        summary = self.repo.get_branch_cache_summary(server_id, project_id, branch_id)
        if self._is_plugin_managed_summary(summary):
            branch_access = self._plugin_branch_access_or_source_fallback(
                self._user_key(preferred_username),
                server_id,
                project_id,
                branch_id,
                summary,
            )
            editable = bool(branch_access.editable) if branch_access and branch_access.accessible else False
        else:
            permission = self.repo.get_model_permission(
                self._user_key(preferred_username),
                server_id,
                project_id,
                branch_id,
                record.model_id,
            )
            editable = bool(permission.editable) if permission else False

        server = self._require_server(server_id, include_disabled=True)
        adapter = create_adapter(server, {}, self.settings.resolved_data_dir)
        resolved_payloads: dict[str, Any] = {}
        for reference_id in adapter.reference_resolution_ids(record.payload):
            referenced_record = self.get_cached_branch_element_for_user(
                server_id,
                preferred_username,
                project_id,
                branch_id,
                reference_id,
            )
            if referenced_record is not None and isinstance(referenced_record.payload, dict):
                resolved_payloads[reference_id] = referenced_record.payload
        return adapter.build_item_details_from_payload(
            record.payload,
            element_id,
            project_id,
            branch_id,
            resolved_payloads=resolved_payloads,
            editable=editable,
            version=record.latest_revision or record.synced_at.isoformat(),
        )

    def edit_cached_branch_element_for_user(
        self,
        server_id: str,
        preferred_username: str,
        project_id: str,
        branch_id: str,
        element_id: str,
        payload: CacheElementEditRequest,
    ) -> CachedElementRecord | None:
        self._require_server(server_id, include_disabled=True)
        summary = self.repo.get_branch_cache_summary(server_id, project_id, branch_id)
        if not self._is_plugin_managed_summary(summary):
            raise ValueError("Cached element edits are only supported for plugin-backed branches.")

        record = self.get_cached_branch_element_for_user(server_id, preferred_username, project_id, branch_id, element_id)
        if record is None:
            return None

        branch_access = self._plugin_branch_access_or_source_fallback(
            self._user_key(preferred_username),
            server_id,
            project_id,
            branch_id,
            summary,
        )
        if branch_access is None or not branch_access.accessible or not branch_access.editable:
            raise PermissionError("The active Workbench user does not have edit access to this cached branch.")

        updated_payload = dict(record.payload)
        if payload.name is not None:
            updated_payload["name"] = payload.name
        if payload.human_name is not None:
            updated_payload["human_name"] = payload.human_name
        if payload.qualified_name is not None:
            updated_payload["qualified_name"] = payload.qualified_name
        if payload.documentation is not None:
            updated_payload["documentation"] = payload.documentation
        if payload.attributes is not None:
            updated_payload["attributes"] = payload.attributes
        if payload.references is not None:
            updated_payload["references"] = payload.references
        if payload.owned_element_ids is not None:
            updated_payload["owned_element_ids"] = payload.owned_element_ids

        updated_name = (
            payload.human_name
            or payload.name
            or str(updated_payload.get("human_name") or updated_payload.get("name") or record.name)
        )
        updated_path = payload.qualified_name or str(updated_payload.get("qualified_name") or updated_name)
        now = utcnow()
        updated_record = record.model_copy(
            update={
                "name": updated_name,
                "path": updated_path,
                "child_count": len(updated_payload.get("owned_element_ids") or []),
                "payload": updated_payload,
                "source_user": preferred_username,
                "synced_at": now,
            }
        )
        self.repo.upsert_cached_elements([updated_record])
        if summary is not None:
            self.repo.upsert_branch_cache_summary(
                summary.model_copy(
                    update={
                        "message": f"Cached element {element_id} was edited through the Workbench cache API.",
                        "updated_at": now,
                    }
                )
            )
        self._invalidate_shared_branch_caches(server_id, project_id, branch_id)
        return updated_record

    async def _run_branch_cache_sync(
        self,
        session: SessionData,
        adapter: TeamworkAdapter,
        project_id: str,
        branch_id: str,
        workspace_id: str | None,
        report,
        cancel_requested,
        job_id: str,
        project_name: str = "",
        branch_name: str = "",
    ) -> dict[str, Any]:
        summary = self.repo.get_branch_cache_summary(session.server.id, project_id, branch_id)
        if self._is_plugin_managed_summary(summary):
            return {
                "cancelled": False,
                "superseded_by_plugin": True,
                "project_id": project_id,
                "branch_id": branch_id,
            }
        synced_model_ids: list[str] = []
        synced_models: list[CachedModelRecord] = []
        synced_permissions: list[ModelPermissionSnapshot] = []
        elements_by_model: dict[str, list[CachedElementRecord]] = {}
        total_elements = 0
        latest_revision: str | None = summary.latest_revision if summary else None
        warnings: list[str] = []
        request_pacer = self._model_cache_request_pacer()
        try:
            await report(5, "Loading branch model inventory")
            latest_revision, models, warnings = await adapter.list_branch_models(
                project_id,
                branch_id,
                workspace_id,
                request_pacer=request_pacer,
            )
            if not models and warnings:
                raise RuntimeError(warnings[-1])

            total_models = max(1, len(models))
            for index, (model_id, model_payload) in enumerate(models, start=1):
                if cancel_requested():
                    return {
                        "cancelled": True,
                        "project_id": project_id,
                        "branch_id": branch_id,
                        "model_count": len(synced_model_ids),
                        "element_count": total_elements,
                        "latest_revision": latest_revision,
                        "warnings": warnings,
                    }

                await report(min(95, 5 + int(index * 90 / total_models)), f"Syncing model {index}/{len(models)}: {model_id}")
                model_record, permission, element_records, model_warnings = await adapter.materialize_model_snapshot(
                    self._user_key(session.user.preferred_username),
                    project_id,
                    branch_id,
                    model_id,
                    model_payload,
                    latest_revision=latest_revision,
                    workspace_id=workspace_id,
                    cancel_requested=cancel_requested,
                    request_pacer=request_pacer,
                )
                synced_model_ids.append(model_id)
                synced_models.append(model_record)
                synced_permissions.append(permission)
                elements_by_model[model_id] = element_records
                total_elements += len(element_records)
                warnings.extend(model_warnings[-10:])

            final_message = f"Materialized {len(synced_model_ids)} models and {total_elements} elements into the local branch cache."
            if warnings:
                final_message = f"{final_message} Last warning: {warnings[-1]}"
            final_summary = self._branch_cache_summary(
                session,
                project_id,
                branch_id,
                workspace_id=workspace_id,
                project_name=project_name,
                branch_name=branch_name,
                latest_revision=latest_revision,
                status=MaterializedCacheStatus.READY,
                message=final_message,
                model_count=len(synced_model_ids),
                element_count=total_elements,
                last_job_id=job_id,
            )
            stored = self.repo.replace_fallback_branch_snapshot_if_not_plugin(
                final_summary,
                synced_models,
                synced_permissions,
                elements_by_model,
                permission_user_id=self._user_key(session.user.preferred_username),
            )
            if not stored:
                await report(100, "Skipped fallback write because a Cameo plugin snapshot arrived during refresh.")
                return {
                    "cancelled": False,
                    "superseded_by_plugin": True,
                    "project_id": project_id,
                    "branch_id": branch_id,
                }
            self.sessions.mark_server_permission_snapshots_due(session.server.id)
            self._remember_branch_revision(session.server.id, project_id, branch_id, latest_revision)
            await report(100, final_message)
            return {
                "cancelled": False,
                "project_id": project_id,
                "branch_id": branch_id,
                "model_count": len(synced_model_ids),
                "element_count": total_elements,
                "latest_revision": latest_revision,
                "warnings": warnings[-25:],
            }
        except Exception:
            # Keep the last complete fallback intact. Job state records the
            # failure, and a plugin snapshot must never lose a race to REST.
            raise

    def _active_branch_cache_job(self, session: SessionData, project_id: str, branch_id: str) -> JobRecord | None:
        for job in self.repo.list_jobs():
            if job.server_id != session.server.id or job.job_type != JobType.MODEL_CACHE:
                continue
            if job.status not in {JobStatus.PENDING, JobStatus.RUNNING}:
                continue
            if job.payload.get("project_id") == project_id and job.payload.get("branch_id") == branch_id:
                return job
        return None

    def _model_cache_server_lock(self, server_id: str) -> asyncio.Lock:
        lock = self._model_cache_server_locks.get(server_id)
        if lock is None:
            lock = asyncio.Lock()
            self._model_cache_server_locks[server_id] = lock
        return lock

    def _model_cache_request_pacer(self) -> callable:
        next_request_at = 0.0

        async def pace() -> None:
            nonlocal next_request_at
            loop = asyncio.get_running_loop()
            now = loop.time()
            if next_request_at > now:
                await asyncio.sleep(next_request_at - now)
                now = loop.time()
            next_request_at = now + MODEL_CACHE_SYNC_MIN_REQUEST_INTERVAL_SECONDS

        return pace

    def _remember_branch_revision(
        self,
        server_id: str,
        project_id: str,
        branch_id: str,
        latest_revision: str | None,
    ) -> None:
        self._branch_revision_probe_cache[(server_id, project_id, branch_id)] = (utcnow(), latest_revision)

    async def _probe_branch_revision(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
        *,
        workspace_id: str | None = None,
        force: bool = False,
    ) -> str | None:
        cache_key = (session.server.id, project_id, branch_id)
        if not force:
            cached = self._branch_revision_probe_cache.get(cache_key)
            if cached is not None and cached[0] >= utcnow() - timedelta(seconds=BRANCH_REVISION_PROBE_TTL_SECONDS):
                return cached[1]

        try:
            latest_revision = await self._adapter_for_session(session).get_latest_branch_revision(project_id, branch_id, workspace_id)
        except Exception as exc:
            logger.warning(
                "twc-branch-revision-probe-failed",
                server_id=session.server.id,
                project_id=project_id,
                branch_id=branch_id,
                detail=str(exc),
            )
            return None

        self._remember_branch_revision(session.server.id, project_id, branch_id, latest_revision)
        return latest_revision

    async def _schedule_branch_cache_refresh_if_stale(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
        *,
        workspace_id: str | None = None,
        refresh: bool = False,
        summary: BranchCacheSummary | None = None,
    ) -> JobRecord | None:
        existing_summary = summary or self.repo.get_branch_cache_summary(session.server.id, project_id, branch_id)
        resolved_workspace_id = workspace_id or (existing_summary.workspace_id if existing_summary is not None else None)

        if self._is_plugin_managed_summary(existing_summary):
            return None

        if refresh:
            if resolved_workspace_id is None:
                resolved_workspace_id = await self._workspace_id_for_project(session, project_id)
            return await self.submit_branch_cache_sync(
                session,
                BranchCacheSyncRequest(
                    project_id=project_id,
                    branch_id=branch_id,
                    workspace_id=resolved_workspace_id,
                    force_full_refresh=True,
                ),
            )

        if existing_summary is None:
            if resolved_workspace_id is None:
                resolved_workspace_id = await self._workspace_id_for_project(session, project_id)
            return await self.submit_branch_cache_sync(
                session,
                BranchCacheSyncRequest(
                    project_id=project_id,
                    branch_id=branch_id,
                    workspace_id=resolved_workspace_id,
                    force_full_refresh=False,
                ),
            )

        if existing_summary.status == MaterializedCacheStatus.SYNCING:
            return self._active_branch_cache_job(session, project_id, branch_id)

        if existing_summary.status == MaterializedCacheStatus.FAILED:
            if existing_summary.updated_at <= utcnow() - timedelta(seconds=FAILED_BRANCH_CACHE_RETRY_SECONDS):
                if resolved_workspace_id is None:
                    resolved_workspace_id = existing_summary.workspace_id or await self._workspace_id_for_project(session, project_id)
                return await self.submit_branch_cache_sync(
                    session,
                    BranchCacheSyncRequest(
                        project_id=project_id,
                        branch_id=branch_id,
                        workspace_id=resolved_workspace_id,
                        force_full_refresh=False,
                    ),
                )
            return None

        summary_revision = (existing_summary.latest_revision or "").strip() or None
        latest_revision = await self._probe_branch_revision(
            session,
            project_id,
            branch_id,
            workspace_id=resolved_workspace_id,
            force=False,
        )
        if not latest_revision or latest_revision == summary_revision:
            return None

        if resolved_workspace_id is None:
            resolved_workspace_id = existing_summary.workspace_id or await self._workspace_id_for_project(session, project_id)
        return await self.submit_branch_cache_sync(
            session,
            BranchCacheSyncRequest(
                project_id=project_id,
                branch_id=branch_id,
                workspace_id=resolved_workspace_id,
                force_full_refresh=False,
            ),
        )

    async def _ensure_branch_cache_webhook(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
        *,
        workspace_id: str | None,
    ) -> BranchWebhookRegistration | None:
        existing = self.repo.get_branch_webhook_registration(session.server.id, project_id, branch_id)
        callback_url = self._branch_webhook_callback_url(
            (existing.registration_id if existing is not None else None) or BranchWebhookRegistration(
                server_id=session.server.id,
                project_id=project_id,
                branch_id=branch_id,
                workspace_id=workspace_id,
            ).registration_id
        )

        if (
            existing is not None
            and existing.status == WebhookRegistrationStatus.READY
            and existing.webhook_id
            and existing.encrypted_service_credentials
            and existing.endpoint_url == callback_url
        ):
            return existing

        if not session.authorization_context.can_manage_server_presets:
            return existing

        registration = existing or BranchWebhookRegistration(
            server_id=session.server.id,
            project_id=project_id,
            branch_id=branch_id,
            workspace_id=workspace_id,
        )
        if not registration.auth_username:
            registration = registration.model_copy(update={"auth_username": f"twc-workbench-{registration.registration_id[:12]}"})
        if not registration.auth_password:
            registration = registration.model_copy(update={"auth_password": secrets.token_urlsafe(24)})

        callback_url = self._branch_webhook_callback_url(registration.registration_id)
        credentials = self.sessions.get_credentials(session)
        refreshed_credentials = await self._refresh_twc_credentials_if_needed(session.server, credentials)
        if refreshed_credentials is not credentials:
            self.sessions.update_credentials(session, refreshed_credentials)
        registration = registration.model_copy(
            update={
                "workspace_id": workspace_id,
                "endpoint_url": callback_url,
                "encrypted_service_credentials": self.sessions.cipher.encrypt(refreshed_credentials),
                "updated_at": utcnow(),
            }
        )

        try:
            ensured = await self._adapter_for_credentials(session.server, refreshed_credentials).ensure_branch_webhook(
                registration,
                callback_url=callback_url,
            )
        except Exception as exc:
            failed = registration.model_copy(
                update={
                    "status": WebhookRegistrationStatus.FAILED,
                    "enabled": False,
                    "status_message": str(exc),
                    "updated_at": utcnow(),
                }
            )
            self.repo.upsert_branch_webhook_registration(failed)
            return failed

        ensured = ensured.model_copy(
            update={
                "workspace_id": workspace_id,
                "encrypted_service_credentials": registration.encrypted_service_credentials,
                "updated_at": utcnow(),
            }
        )
        self.repo.upsert_branch_webhook_registration(ensured)
        return ensured

    async def _build_transient_session(
        self,
        server: ServerProfile,
        credentials: TokenBundle,
        *,
        fallback_username: str,
    ) -> SessionData:
        adapter = self._adapter_for_credentials(server, credentials)
        current_user_context = await adapter.current_user_context()
        preferred_username = self._resolve_preferred_username(current_user_context, fallback_username)
        capabilities = await adapter.discover_capabilities()
        if not self._has_remote_access(capabilities):
            raise PermissionError(
                "The stored Teamwork Cloud webhook service credentials no longer expose repository access. Sign in again with an admin-capable account."
            )

        user = UserContext(
            preferred_username=preferred_username,
            server_id=server.id,
            server_name=server.name,
        )
        authorization_context = self._build_authorization_context(preferred_username, current_user_context, upstream_roles=None, upstream_groups=None)
        now = utcnow()
        return SessionData(
            server=server,
            user=user,
            authorization_context=authorization_context,
            encrypted_credentials=self.sessions.cipher.encrypt(credentials),
            capabilities=capabilities,
            created_at=now,
            expires_at=now + timedelta(minutes=self.settings.session_ttl_minutes),
        )

    def _branch_webhook_callback_url(self, registration_id: str) -> str:
        return f"{self.settings.resolved_twc_webhook_callback_url.rstrip('/')}/{registration_id}"

    def _validate_branch_webhook_auth(
        self,
        registration: BranchWebhookRegistration,
        authorization_header: str | None,
    ) -> bool:
        if not authorization_header or not authorization_header.lower().startswith("basic "):
            return False
        encoded = authorization_header.split(" ", 1)[1].strip()
        try:
            decoded = base64.b64decode(encoded).decode("utf-8")
        except Exception:
            return False
        username, separator, password = decoded.partition(":")
        if not separator:
            return False
        return secrets.compare_digest(username, registration.auth_username) and secrets.compare_digest(
            password,
            registration.auth_password,
        )

    def _summarize_webhook_payload(self, payload: Any) -> str:
        if isinstance(payload, dict):
            for key in ("event", "type", "trigger", "branchId", "commitId", "eobjectId"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return f"Webhook event received ({key}={value.strip()})."
                if isinstance(value, dict) and isinstance(value.get("type"), str):
                    return f"Webhook event received (trigger={value['type']})."
            keys = ", ".join(sorted(str(key) for key in payload.keys())[:5])
            return f"Webhook event received with payload keys: {keys or 'none'}."
        if isinstance(payload, list):
            return f"Webhook event received with an array payload of {len(payload)} item(s)."
        if isinstance(payload, str) and payload.strip():
            return f"Webhook event received ({payload.strip()[:160]})."
        return "Webhook event received."

    def _branch_cache_summary(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
        *,
        status: MaterializedCacheStatus,
        message: str,
        workspace_id: str | None = None,
        latest_revision: str | None = None,
        model_count: int = 0,
        element_count: int = 0,
        last_job_id: str | None = None,
    ) -> BranchCacheSummary:
        return BranchCacheSummary(
            server_id=session.server.id,
            project_id=project_id,
            branch_id=branch_id,
            workspace_id=workspace_id,
            latest_revision=latest_revision,
            status=status,
            message=message,
            model_count=model_count,
            element_count=element_count,
            last_job_id=last_job_id,
        )

    async def _materialized_item_details(
        self,
        session: SessionData,
        item_id: str,
        project_id: str,
        branch_id: str,
    ) -> ItemDetails | None:
        cached_record = self.get_cached_branch_element(session, project_id, branch_id, item_id)
        summary = self.repo.get_branch_cache_summary(session.server.id, project_id, branch_id)
        branch_access = self._branch_access_for_session(session, project_id, branch_id) if self._is_plugin_managed_summary(summary) else None
        editable = False
        if cached_record is None:
            cached_model = self.repo.get_cached_model(session.server.id, project_id, branch_id, item_id)
            if cached_model is None:
                return None
            if self._is_plugin_managed_summary(summary):
                if branch_access is None or not branch_access.accessible:
                    return None
                editable = bool(branch_access.editable)
            else:
                permission = self.repo.get_model_permission(
                    self._user_key(session.user.preferred_username),
                    session.server.id,
                    project_id,
                    branch_id,
                    cached_model.model_id,
                )
                if permission is None or not permission.accessible or permission.restricted:
                    return None
                editable = bool(permission.editable)
            return self._materialized_model_item_details(
                session,
                cached_model,
                project_id,
                branch_id,
                editable=editable,
            )

        if self._is_plugin_managed_summary(summary):
            editable = bool(branch_access.editable) if branch_access and branch_access.accessible else False
        else:
            permission = self.repo.get_model_permission(
                self._user_key(session.user.preferred_username),
                session.server.id,
                project_id,
                branch_id,
                cached_record.model_id,
            )
            editable = bool(permission.editable) if permission else False
        adapter = self._adapter_for_session(session)
        resolved_payloads: dict[str, Any] = {}
        for reference_id in adapter.reference_resolution_ids(cached_record.payload):
            referenced_record = self.get_cached_branch_element(session, project_id, branch_id, reference_id)
            if referenced_record is not None and isinstance(referenced_record.payload, dict):
                resolved_payloads[reference_id] = referenced_record.payload

        return adapter.build_item_details_from_payload(
            cached_record.payload,
            item_id,
            project_id,
            branch_id,
            resolved_payloads=resolved_payloads,
            editable=editable,
            version=cached_record.latest_revision or cached_record.synced_at.isoformat(),
        )

    def _materialized_model_item_details(
        self,
        session: SessionData,
        model: CachedModelRecord,
        project_id: str,
        branch_id: str,
        *,
        editable: bool,
    ) -> ItemDetails:
        adapter = self._adapter_for_session(session)
        synthetic_payload: dict[str, Any] = {
            "@id": model.model_id,
            "@type": ["Model"],
            "name": model.payload.get("name") or model.name or model.model_id,
            "dcterms:title": model.payload.get("human_name") or model.name or model.model_id,
            "qualified_name": model.payload.get("qualified_name") or model.name or model.model_id,
            "human_type": "Model",
            "metaclass": "Model",
            "owner_id": model.payload.get("owner_id"),
            "root_element_ids": model.root_ids,
            "ldp:contains": [{"@id": root_id} for root_id in model.root_ids if str(root_id).strip()],
            "editable": editable,
        }
        resolved_payloads: dict[str, Any] = {}
        for root_id in model.root_ids:
            referenced_record = self.get_cached_branch_element(session, project_id, branch_id, root_id)
            if referenced_record is not None and isinstance(referenced_record.payload, dict):
                resolved_payloads[root_id] = referenced_record.payload
        return adapter.build_item_details_from_payload(
            synthetic_payload,
            model.model_id,
            project_id,
            branch_id,
            resolved_payloads=resolved_payloads,
            editable=editable,
            version=model.latest_revision or model.synced_at.isoformat(),
        )

    def _accessible_cached_models(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
    ) -> list[CachedModelRecord]:
        summary = self.repo.get_branch_cache_summary(session.server.id, project_id, branch_id)
        if self._is_plugin_managed_summary(summary):
            branch_access = self._branch_access_for_session(session, project_id, branch_id)
            if branch_access is None or not branch_access.accessible:
                return []
            return self.repo.list_cached_models(session.server.id, project_id, branch_id)
        permissions = {
            item.model_id: item
            for item in self.repo.list_model_permissions(
                self._user_key(session.user.preferred_username),
                session.server.id,
                project_id,
                branch_id,
            )
        }
        return [
            model
            for model in self.repo.list_cached_models(session.server.id, project_id, branch_id)
            if (permission := permissions.get(model.model_id)) is not None and permission.accessible and not permission.restricted
        ]

    def _materialized_model_tree(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
        *,
        depth: int | None = None,
    ) -> list[TreeNode] | None:
        models = self._accessible_cached_models(session, project_id, branch_id)
        if not models:
            return None
        if depth is not None and depth <= 0:
            top_level_nodes: list[TreeNode] = []
            for model in models:
                sanitized_root_count = len([root_id for root_id in model.root_ids if str(root_id).strip() and str(root_id).strip() != model.model_id])
                top_level_nodes.append(
                    TreeNode(
                        id=model.model_id,
                        label=model.name or model.model_id,
                        node_type="model",
                        path=f"{project_id}/{branch_id}/{model.name or model.model_id}",
                        children=[],
                        metadata={
                            "project_id": project_id,
                            "branch_id": branch_id,
                            "model_id": model.model_id,
                            "child_count": sanitized_root_count or (1 if (model.element_count or 0) > 0 else 0),
                            "element_count": model.element_count or 0,
                            "root_count": sanitized_root_count,
                            "subtitle": f"{model.element_count or 0} published elements",
                        },
                    )
                )
            return top_level_nodes
        nodes: list[TreeNode] = []
        for model in models:
            model_records = {
                record.element_id: record
                for record in self._visible_cached_elements_for_user(
                    self._user_key(session.user.preferred_username),
                    session.server.id,
                    project_id,
                    branch_id,
                    model_id=model.model_id,
                )
            }
            nodes.append(
                self._tree_nodes_for_model(
                    project_id,
                    branch_id,
                    model,
                    model_records,
                    depth=depth,
                )
            )
        return nodes

    def _tree_record_field(self, record: CachedElementRecord | dict[str, Any], field: str, default: Any = "") -> Any:
        if isinstance(record, CachedElementRecord):
            if field == "element_id":
                return record.element_id
            if field == "name":
                return record.name
            if field == "item_type":
                return record.item_type
            if field == "path":
                return record.path
            if field == "child_count":
                return record.child_count
            return record.payload.get(field, default)
        return record.get(field, default)

    def _cached_element_sort_key(self, record: CachedElementRecord | dict[str, Any] | None, fallback_id: str = "") -> tuple[int, str]:
        if record is None:
            return (99, fallback_id.lower())
        item_type = str(self._tree_record_field(record, "item_type") or self._tree_record_field(record, "metaclass") or "element").strip().lower()
        display_name = str(
            self._tree_record_field(record, "name")
            or self._tree_record_field(record, "qualified_name")
            or self._tree_record_field(record, "element_id")
            or fallback_id
        ).strip().lower()
        if item_type in {"package", "model"}:
            rank = 0
        elif "diagram" in item_type or item_type in {"table", "matrix", "chart"}:
            rank = 1
        elif item_type in {"block", "class", "requirement", "use case", "activity"}:
            rank = 2
        else:
            rank = 3
        element_id = str(self._tree_record_field(record, "element_id") or fallback_id).lower()
        return (rank, display_name or element_id)

    def _sanitize_model_root_ids(
        self,
        model: CachedModelRecord,
        model_records: dict[str, CachedElementRecord | dict[str, Any]],
    ) -> list[str]:
        root_ids: list[str] = []
        for root_id in model.root_ids:
            root_text = str(root_id).strip()
            if not root_text or root_text == model.model_id:
                continue
            if root_text in model_records and root_text not in root_ids:
                root_ids.append(root_text)

        if root_ids:
            return self._normalize_model_root_ids(model, model_records, root_ids)

        model_record = model_records.get(model.model_id)
        if model_record is not None:
            for child_id in [str(value).strip() for value in self._tree_record_field(model_record, "owned_element_ids", []) or [] if str(value).strip()]:
                if child_id != model.model_id and child_id in model_records and child_id not in root_ids:
                    root_ids.append(child_id)
        return self._normalize_model_root_ids(model, model_records, root_ids)

    def _normalize_model_root_ids(
        self,
        model: CachedModelRecord,
        model_records: dict[str, CachedElementRecord | dict[str, Any]],
        root_ids: list[str],
    ) -> list[str]:
        normalized_root_ids = [root_id for root_id in root_ids if root_id and root_id != model.model_id]
        if len(normalized_root_ids) != 1:
            return normalized_root_ids
        root_record = model_records.get(normalized_root_ids[0])
        if root_record is None or not self._is_modelish_record(root_record):
            return normalized_root_ids
        root_name = normalize_lookup_key(str(self._tree_record_field(root_record, "name") or self._tree_record_field(root_record, "human_name") or ""))
        model_name = normalize_lookup_key(str(model.name or model.payload.get("human_name") or ""))
        if not root_name or root_name != model_name:
            return normalized_root_ids
        lifted_ids = [
            child_id
            for child_id in [str(value).strip() for value in self._tree_record_field(root_record, "owned_element_ids", []) or [] if str(value).strip()]
            if child_id != model.model_id and child_id in model_records
        ]
        return lifted_ids or normalized_root_ids

    def _is_modelish_record(self, record: CachedElementRecord | dict[str, Any]) -> bool:
        normalized_type = normalize_lookup_key(
            str(
                self._tree_record_field(record, "metaclass")
                or self._tree_record_field(record, "item_type")
                or self._tree_record_field(record, "human_type")
                or "element"
            )
        )
        return normalized_type in {"model", "sysml model", "uml model"}

    def _final_named_segment(self, path: str) -> str:
        return next((segment.strip() for segment in reversed(path.split("/")) if segment.strip()), "")

    def _looks_like_opaque_identifier(self, value: str) -> bool:
        return bool(OPAQUE_IDENTIFIER_RE.fullmatch(value.strip()))

    def _presentable_name_from_path(
        self,
        raw_label: str,
        *,
        qualified_name: str = "",
        fallback_path: str = "",
    ) -> str:
        clean_label = raw_label.strip()
        for candidate in (qualified_name, fallback_path):
            final_segment = self._final_named_segment(candidate)
            if not final_segment or self._looks_like_opaque_identifier(final_segment):
                continue
            return final_segment
        return clean_label

    def _tree_node_summary_from_record(
        self,
        *,
        server_id: str,
        project_id: str,
        branch_id: str,
        model_id: str,
        record: CachedElementRecord | dict[str, Any],
    ) -> TreeNode:
        element_id = str(self._tree_record_field(record, "element_id")).strip()
        item_type = str(self._tree_record_field(record, "item_type") or "element").strip()
        path = str(self._tree_record_field(record, "path") or "").strip()
        owner_id = str(self._tree_record_field(record, "owner_id") or "").strip()
        qualified_name = str(self._tree_record_field(record, "qualified_name") or path).strip()
        child_ids = [str(value).strip() for value in self._tree_record_field(record, "owned_element_ids", []) or [] if str(value).strip()]
        metaclass = str(self._tree_record_field(record, "metaclass") or item_type or "element").strip()
        stereotypes = [str(value).strip() for value in self._tree_record_field(record, "applied_stereotype_ids", []) or [] if str(value).strip()]
        child_count = max(int(self._tree_record_field(record, "child_count", 0) or 0), len(child_ids))
        label = self._presentable_tree_label(server_id, project_id, branch_id, record)
        subtitle = self._presentable_tree_subtitle(server_id, project_id, branch_id, record)
        return TreeNode(
            id=element_id,
            label=label,
            node_type=item_type,
            path=qualified_name or path or str(self._tree_record_field(record, "name") or element_id),
            children=[],
            metadata={
                "project_id": project_id,
                "branch_id": branch_id,
                "model_id": model_id,
                "owner_id": owner_id,
                "child_count": child_count,
                "children_loaded": False,
                "qualified_name": qualified_name,
                "metaclass": metaclass,
                "stereotypes": stereotypes,
                "subtitle": subtitle,
            },
        )

    def _presentable_tree_label(
        self,
        server_id: str,
        project_id: str,
        branch_id: str,
        record: CachedElementRecord | dict[str, Any],
    ) -> str:
        raw_label = str(self._tree_record_field(record, "name") or self._tree_record_field(record, "element_id")).strip() or str(
            self._tree_record_field(record, "element_id")
        )
        qualified_name = str(self._tree_record_field(record, "qualified_name") or self._tree_record_field(record, "path") or "").strip()
        normalized_type = normalize_lookup_key(str(self._tree_record_field(record, "item_type") or self._tree_record_field(record, "metaclass") or "element"))
        if normalized_type == "comment":
            documentation = str(self._tree_record_field(record, "documentation") or "").strip()
            if documentation:
                first_line = documentation.splitlines()[0].strip()
                if first_line:
                    return first_line[:96]
        return self._presentable_name_from_path(
            raw_label,
            qualified_name=qualified_name,
            fallback_path=str(self._tree_record_field(record, "path") or "").strip(),
        ) or raw_label

    def _presentable_tree_subtitle(
        self,
        server_id: str,
        project_id: str,
        branch_id: str,
        record: CachedElementRecord | dict[str, Any],
    ) -> str:
        normalized_type = normalize_lookup_key(str(self._tree_record_field(record, "item_type") or self._tree_record_field(record, "metaclass") or "element"))
        diagram_type = str(self._tree_record_field(record, "diagram_type") or "").strip()
        if diagram_type:
            return diagram_type
        if normalized_type in {"package import", "element import"}:
            return ""
        return ""

    def _tree_children_for_model_root(
        self,
        server_id: str,
        project_id: str,
        branch_id: str,
        model: CachedModelRecord,
    ) -> list[TreeNode]:
        initial_records = self.repo.list_cached_element_tree_summaries_by_ids(
            server_id,
            project_id,
            branch_id,
            [model.model_id, *model.root_ids],
            model_id=model.model_id,
        )
        records_by_id = {str(record["element_id"]): record for record in initial_records}
        root_ids = self._sanitize_model_root_ids(model, records_by_id)
        missing_root_ids = [root_id for root_id in root_ids if root_id not in records_by_id]
        if missing_root_ids:
            for record in self.repo.list_cached_element_tree_summaries_by_ids(
                server_id,
                project_id,
                branch_id,
                missing_root_ids,
                model_id=model.model_id,
            ):
                records_by_id[str(record["element_id"])] = record
        ordered_records = [records_by_id[root_id] for root_id in root_ids if root_id in records_by_id]
        return [
            self._tree_node_summary_from_record(
                project_id=project_id,
                server_id=server_id,
                branch_id=branch_id,
                model_id=model.model_id,
                record=record,
            )
            for record in ordered_records
        ]

    def _tree_children_for_parent(
        self,
        server_id: str,
        project_id: str,
        branch_id: str,
        model_id: str,
        parent_record: CachedElementRecord | dict[str, Any],
    ) -> list[TreeNode]:
        owned_child_ids = [
            child_id
            for child_id in [str(value).strip() for value in self._tree_record_field(parent_record, "owned_element_ids", []) or [] if str(value).strip()]
            if child_id and child_id != str(self._tree_record_field(parent_record, "element_id"))
        ]
        child_records = {
            str(record["element_id"]): record
            for record in self.repo.list_cached_element_tree_summaries_by_owner(
                server_id,
                project_id,
                branch_id,
                model_id,
                str(self._tree_record_field(parent_record, "element_id")),
            )
            if str(record["element_id"]) != str(self._tree_record_field(parent_record, "element_id"))
        }
        missing_owned_child_ids = [child_id for child_id in owned_child_ids if child_id not in child_records]
        if missing_owned_child_ids:
            for record in self.repo.list_cached_element_tree_summaries_by_ids(
                server_id,
                project_id,
                branch_id,
                missing_owned_child_ids,
                model_id=model_id,
            ):
                if str(record["element_id"]) != str(self._tree_record_field(parent_record, "element_id")):
                    child_records[str(record["element_id"])] = record

        ordered_records = [child_records[child_id] for child_id in owned_child_ids if child_id in child_records]
        extra_records = sorted(
            [record for child_id, record in child_records.items() if child_id not in owned_child_ids],
            key=lambda item: self._cached_element_sort_key(item, str(item.get("element_id") or "")),
        )
        return [
            self._tree_node_summary_from_record(
                project_id=project_id,
                server_id=server_id,
                branch_id=branch_id,
                model_id=model_id,
                record=record,
            )
            for record in [*ordered_records, *extra_records]
        ]

    def _repair_cached_model_roots(
        self,
        models: list[CachedModelRecord],
        elements: list[CachedElementRecord],
    ) -> list[CachedModelRecord]:
        elements_by_model: dict[str, dict[str, CachedElementRecord]] = {}
        for element in elements:
            elements_by_model.setdefault(element.model_id, {})[element.element_id] = element

        repaired: list[CachedModelRecord] = []
        for model in models:
            model_records = elements_by_model.get(model.model_id, {})
            repaired_roots = self._sanitize_model_root_ids(model, model_records)
            if repaired_roots != model.root_ids:
                repaired.append(model.model_copy(update={"root_ids": repaired_roots}))
            else:
                repaired.append(model)
        return repaired

    def _tree_indexes_for_model(
        self,
        model: CachedModelRecord,
        model_records: dict[str, CachedElementRecord],
    ) -> tuple[dict[str, list[str]], list[str]]:
        parent_to_children: dict[str, list[str]] = {}

        def append_child(parent_id: str, child_id: str) -> None:
            if not parent_id or not child_id or parent_id == child_id or child_id not in model_records:
                return
            bucket = parent_to_children.setdefault(parent_id, [])
            if child_id not in bucket:
                bucket.append(child_id)

        # Cameo publishes getOwnedElement() order. Preserve that explicit order
        # first so Workbench resembles the desktop containment browser.
        for record in model_records.values():
            for child_id in [str(value).strip() for value in record.payload.get("owned_element_ids") or [] if str(value).strip()]:
                append_child(record.element_id, child_id)

        # Repair incomplete payloads from owner_id, but keep repaired children
        # after the explicitly ordered children.
        for record in sorted(
            model_records.values(),
            key=lambda item: self._cached_element_sort_key(item, item.element_id),
        ):
            owner_id = str(record.payload.get("owner_id") or "").strip()
            if owner_id:
                append_child(owner_id, record.element_id)

        root_ids = self._sanitize_model_root_ids(model, model_records)

        detached_root_ids = [
            element_id
            for element_id, record in model_records.items()
            if element_id != model.model_id and str(record.payload.get("owner_id") or "").strip() not in model_records and element_id not in root_ids
        ]
        root_ids.extend(
            sorted(
                detached_root_ids,
                key=lambda element_id: self._cached_element_sort_key(model_records.get(element_id), element_id),
            )
        )
        return parent_to_children, root_ids

    def _build_tree_node_from_record(
        self,
        *,
        server_id: str,
        project_id: str,
        branch_id: str,
        model_id: str,
        model_records: dict[str, CachedElementRecord],
        parent_to_children: dict[str, list[str]],
        element_id: str,
        parent_path: str,
        trail: tuple[str, ...],
        covered: set[str],
        depth: int | None = None,
        current_depth: int = 0,
    ) -> TreeNode:
        record = model_records.get(element_id)
        if record is None:
            return TreeNode(
                id=element_id,
                label=element_id,
                node_type="element",
                path=f"{parent_path}/{element_id}",
                children=[],
                metadata={"project_id": project_id, "branch_id": branch_id, "model_id": model_id},
            )

        node_name = self._presentable_tree_label(
            server_id=server_id,
            project_id=project_id,
            branch_id=branch_id,
            record=record,
        ) or record.name or record.element_id
        qualified_name = str(record.payload.get("qualified_name") or record.path or "").strip()
        node_path = qualified_name or f"{parent_path}/{node_name}"
        if element_id in trail:
            return TreeNode(
                id=record.element_id,
                label=node_name,
                node_type=record.item_type,
                path=node_path,
                children=[],
                metadata={
                    "project_id": project_id,
                    "branch_id": branch_id,
                    "model_id": model_id,
                    "cycle_detected": True,
                    "subtitle": "Cycle detected",
                },
            )

        covered.add(record.element_id)
        child_ids = list(parent_to_children.get(record.element_id, []))
        if depth is not None and current_depth >= depth:
            child_nodes: list[TreeNode] = []
        else:
            child_nodes = [
                self._build_tree_node_from_record(
                    server_id=server_id,
                    project_id=project_id,
                    branch_id=branch_id,
                    model_id=model_id,
                    model_records=model_records,
                    parent_to_children=parent_to_children,
                    element_id=child_id,
                    parent_path=node_path,
                    trail=(*trail, element_id),
                    covered=covered,
                    depth=depth,
                    current_depth=current_depth + 1,
                )
                for child_id in child_ids
            ]
        stereotypes = [str(value).strip() for value in record.payload.get("applied_stereotype_ids") or [] if str(value).strip()]
        metaclass = str(record.payload.get("metaclass") or record.item_type or "element").strip()
        subtitle = self._presentable_tree_subtitle(
            server_id,
            project_id,
            branch_id,
            record,
        )
        return TreeNode(
            id=record.element_id,
            label=node_name,
            node_type=record.item_type,
            path=node_path,
            children=child_nodes,
            metadata={
                "project_id": project_id,
                "branch_id": branch_id,
                "model_id": model_id,
                "owner_id": str(record.payload.get("owner_id") or "").strip(),
                "child_count": len(child_ids),
                "qualified_name": qualified_name,
                "metaclass": metaclass,
                "stereotypes": stereotypes,
                "subtitle": subtitle,
            },
        )

    def _tree_nodes_for_model(
        self,
        project_id: str,
        branch_id: str,
        model: CachedModelRecord,
        model_records: dict[str, CachedElementRecord],
        *,
        root_id: str | None = None,
        depth: int | None = None,
        include_orphans: bool = True,
    ) -> TreeNode:
        model_name = self._presentable_name_from_path(
            str(model.name or model.model_id).strip() or model.model_id,
            qualified_name=str(model.payload.get("qualified_name") or "").strip(),
            fallback_path=str(model.payload.get("human_name") or "").strip(),
        ) or model.name or model.model_id
        model_path = f"{project_id}/{branch_id}/{model_name}"
        sanitized_root_ids = self._sanitize_model_root_ids(model, model_records)
        if depth is not None and depth <= 0:
            return TreeNode(
                id=model.model_id,
                label=model_name,
                node_type="model",
                path=model_path,
                children=[],
                metadata={
                    "project_id": project_id,
                    "branch_id": branch_id,
                    "model_id": model.model_id,
                    "child_count": len(sanitized_root_ids),
                    "element_count": model.element_count or len(model_records),
                    "root_count": len(sanitized_root_ids),
                    "subtitle": f"{model.element_count or len(model_records)} published elements",
                },
            )
        if not model_records:
            sanitized_root_count = len([root_id for root_id in model.root_ids if str(root_id).strip() and str(root_id).strip() != model.model_id])
            return TreeNode(
                id=model.model_id,
                label=model_name,
                node_type="model",
                path=model_path,
                children=[],
                metadata={
                    "project_id": project_id,
                    "branch_id": branch_id,
                    "model_id": model.model_id,
                    "element_count": model.element_count or 0,
                    "child_count": sanitized_root_count or (1 if (model.element_count or 0) > 0 else 0),
                    "root_count": sanitized_root_count,
                    "subtitle": "Published model snapshot",
                },
            )

        parent_to_children, root_ids = self._tree_indexes_for_model(model, model_records)
        covered: set[str] = set()

        if root_id:
            seed_ids = [root_id] if root_id in model_records else []
        else:
            seed_ids = list(root_ids)

        children = [
            self._build_tree_node_from_record(
                server_id=model.server_id,
                project_id=project_id,
                branch_id=branch_id,
                model_id=model.model_id,
                model_records=model_records,
                parent_to_children=parent_to_children,
                element_id=seed_id,
                parent_path=model_path,
                trail=(model.model_id,),
                covered=covered,
                depth=depth,
            )
            for seed_id in seed_ids
        ]

        if include_orphans and not root_id:
            unlinked_ids = sorted(
                [element_id for element_id in model_records if element_id not in covered],
                key=lambda element_id: self._cached_element_sort_key(model_records.get(element_id), element_id),
            )
            if unlinked_ids:
                children.append(
                    TreeNode(
                        id=f"{model.model_id}::additional",
                        label="Additional Elements",
                        node_type="group",
                        path=f"{model_path}/Additional Elements",
                        children=[
                            self._build_tree_node_from_record(
                                server_id=model.server_id,
                                project_id=project_id,
                                branch_id=branch_id,
                                model_id=model.model_id,
                                model_records=model_records,
                                parent_to_children=parent_to_children,
                                element_id=element_id,
                                parent_path=f"{model_path}/Additional Elements",
                                trail=(model.model_id,),
                                covered=covered,
                                depth=depth,
                            )
                            for element_id in unlinked_ids
                        ],
                        metadata={
                            "project_id": project_id,
                            "branch_id": branch_id,
                            "model_id": model.model_id,
                            "child_count": len(unlinked_ids),
                            "subtitle": "Elements not attached to a published root",
                        },
                    )
                )

        return TreeNode(
            id=model.model_id,
            label=model_name,
            node_type="model",
            path=model_path,
            children=children,
            metadata={
                "project_id": project_id,
                "branch_id": branch_id,
                "model_id": model.model_id,
                "element_count": model.element_count or len(model_records),
                "root_count": len(root_ids),
                "child_count": len(root_ids),
                "subtitle": f"{model.element_count or len(model_records)} published elements",
            },
        )

    def _count_tree_nodes(self, nodes: list[TreeNode]) -> int:
        total = 0
        stack = list(nodes)
        while stack:
            node = stack.pop()
            total += 1
            stack.extend(node.children)
        return total

    def _materialized_element_discovery(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
        summary: BranchCacheSummary | None,
    ) -> ElementDiscoveryResult | None:
        if summary is None:
            return None
        models = self.repo.list_cached_models(session.server.id, project_id, branch_id)
        if not models:
            return None
        if self._is_plugin_managed_summary(summary):
            branch_access = self._branch_access_for_session(session, project_id, branch_id)
            if branch_access is None or not branch_access.accessible:
                return None
            accessible_models = models
        else:
            permissions = {
                item.model_id: item
                for item in self.repo.list_model_permissions(
                    self._user_key(session.user.preferred_username),
                    session.server.id,
                    project_id,
                    branch_id,
                )
            }
            accessible_models = [
                model
                for model in models
                if (permission := permissions.get(model.model_id)) is not None and permission.accessible and not permission.restricted
            ]
        if not accessible_models:
            return None

        cached_elements = self.repo.list_cached_elements(
            session.server.id,
            project_id,
            branch_id,
            limit=max(1, summary.element_count or sum(model.element_count for model in accessible_models) or 1),
            offset=0,
        )
        visible_model_ids = {model.model_id for model in accessible_models}
        entries_by_id: dict[str, Any] = {}
        ids: list[str] = []
        for item in cached_elements.items:
            if item.model_id not in visible_model_ids or item.element_id in entries_by_id:
                continue
            ids.append(item.element_id)
            entries_by_id[item.element_id] = {
                "id": item.element_id,
                "name": item.name,
                "item_type": item.item_type,
                "child_count": item.child_count,
            }

        if not ids:
            return None

        warnings = [f"Serving elements from the local materialized cache for {project_id}/{branch_id}."]
        if summary.message:
            warnings.append(summary.message)
        if summary.status == MaterializedCacheStatus.SYNCING:
            warnings.append("The materialized cache is refreshing in the background; results may lag the latest branch revision.")

        seed_ids = list(dict.fromkeys(root_id for model in accessible_models for root_id in model.root_ids if root_id))
        return ElementDiscoveryResult(
            project_id=project_id,
            branch_id=branch_id,
            workspace_id=summary.workspace_id,
            latest_revision=summary.latest_revision,
            seed_source="materialized-model-cache",
            seed_ids=seed_ids,
            ids=ids,
            entries=[ElementDiscoveryEntry(**payload) for payload in entries_by_id.values()],
            total_ids=len(ids),
            traversed_elements=0,
            hydrated_elements=len(ids),
            batch_count=0,
            batch_size=0,
            cache_status="cache-hit",
            warnings=warnings[-50:],
            discovered_at=summary.updated_at,
        )

    async def _refresh_element_cache_incrementally(
        self,
        cached_result: ElementDiscoveryResult,
        *,
        adapter: TeamworkAdapter,
        project_id: str,
        branch_id: str,
        workspace_id: str | None,
        source_revision: str,
        target_revision: str,
    ) -> ElementDiscoveryResult | None:
        added_ids, changed_ids, removed_ids = await adapter.changed_elements_between_revisions(
            project_id,
            source_revision,
            target_revision,
            workspace_id,
        )
        touched_ids = [element_id for element_id in dict.fromkeys([*added_ids, *changed_ids]) if element_id]
        if not touched_ids and not removed_ids:
            return cached_result.model_copy(
                update={
                    "latest_revision": target_revision,
                    "cache_status": "incremental-refresh",
                    "warnings": list(cached_result.warnings),
                    "discovered_at": utcnow(),
                }
            )

        payloads_by_id = await adapter.get_elements_by_ids(project_id, branch_id, touched_ids, workspace_id)
        if touched_ids and not payloads_by_id:
            return None

        removed_set = set(removed_ids)
        updated_entries_by_id = {entry.id: entry for entry in cached_result.entries if entry.id not in removed_set}
        updated_ids = [element_id for element_id in cached_result.ids if element_id not in removed_set]

        for element_id in touched_ids:
            payload = payloads_by_id.get(element_id)
            if payload is None:
                continue
            entry = adapter.element_discovery_entry(element_id, payload, updated_entries_by_id.get(element_id))
            updated_entries_by_id[element_id] = entry
            if element_id not in updated_ids:
                updated_ids.append(element_id)

        updated_entries = [updated_entries_by_id[element_id] for element_id in updated_ids if element_id in updated_entries_by_id]
        warnings = [warning for warning in cached_result.warnings if warning]
        warnings.append(
            f"Incremental cache refresh applied from revision {source_revision} to {target_revision} for {len(touched_ids)} added or changed elements and {len(removed_set)} removed elements."
        )
        return cached_result.model_copy(
            update={
                "workspace_id": workspace_id,
                "latest_revision": target_revision,
                "ids": updated_ids,
                "entries": updated_entries,
                "total_ids": len(updated_ids),
                "hydrated_elements": len(updated_entries),
                "cache_status": "incremental-refresh",
                "warnings": warnings[-50:],
                "discovered_at": utcnow(),
            }
        )

    async def update_branch(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
        payload: BranchUpdateRequest,
    ):
        summary = self.repo.get_branch_cache_summary(session.server.id, project_id, branch_id)
        if summary is not None:
            await self._ensure_plugin_branch_permissions(session, project_id, branch_id, summary=summary)
            self._require_effective_branch_access(session, project_id, branch_id, require_branch_admin=True)
        return await self._adapter_for_session(session).update_branch(project_id, branch_id, payload.model_dump(exclude_none=True))

    async def get_item(
        self,
        session: SessionData,
        item_id: str,
        project_id: str | None = None,
        branch_id: str | None = None,
        workspace_id: str | None = None,
        refresh: bool = False,
    ) -> ItemDetails:
        cache_key = self._item_cache_key(project_id, branch_id, item_id)
        use_branch_materialized_cache = bool(project_id and branch_id)
        if cache_key and not refresh and not use_branch_materialized_cache:
            cached_item = self._cached_model(session, cache_key, ItemDetails)
            if cached_item is not None:
                return cached_item

        if project_id and branch_id:
            summary = self.repo.get_branch_cache_summary(session.server.id, project_id, branch_id)
            if summary is not None:
                if refresh or not self._plugin_branch_permissions_known_for_user(
                    session,
                    project_id,
                    branch_id,
                    summary=summary,
                ):
                    await self._ensure_plugin_branch_permissions(
                        session,
                        project_id,
                        branch_id,
                        workspace_id=workspace_id,
                        summary=summary,
                        force=refresh,
                    )
                materialized_item = await self._materialized_item_details(session, item_id, project_id, branch_id)
                if materialized_item is None:
                    raise KeyError(item_id)
                self.sessions.add_recent_item(
                    session,
                    Bookmark(
                        title=materialized_item.name,
                        item_id=materialized_item.id,
                        item_type=materialized_item.item_type,
                        path=materialized_item.path,
                        project_id=materialized_item.project_id,
                        branch_id=materialized_item.branch_id,
                    ),
                )
                return materialized_item
        raise RuntimeError(self._fallback_cache_missing_message(project_id or "", branch_id or ""))

    async def update_item(
        self,
        session: SessionData,
        item_id: str,
        payload: dict[str, Any],
        project_id: str | None = None,
        branch_id: str | None = None,
    ) -> ItemDetails:
        if project_id and branch_id:
            summary = self.repo.get_branch_cache_summary(session.server.id, project_id, branch_id)
            if summary is not None:
                await self._ensure_plugin_branch_permissions(session, project_id, branch_id, summary=summary)
                self._require_effective_branch_access(session, project_id, branch_id, require_edit=True)
        item = await self._adapter_for_session(session).update_item(item_id, payload, project_id, branch_id)
        shared_cache_updated = False
        if project_id and branch_id:
            shared_cache_updated = self._publish_updated_item_to_shared_branch_cache(
                session,
                item,
                project_id,
                branch_id,
            )
            self._invalidate_shared_branch_caches(session.server.id, project_id, branch_id)
        cache_key = self._item_cache_key(project_id, branch_id, item_id)
        if cache_key and not shared_cache_updated:
            self.repo.upsert_user_cache(
                self._user_key(session.user.preferred_username),
                session.server.id,
                cache_key,
                json.loads(item.model_dump_json()),
            )
        tree_cache_key = self._tree_cache_key(project_id, branch_id)
        if tree_cache_key:
            self.repo.delete_user_cache(
                self._user_key(session.user.preferred_username),
                session.server.id,
                tree_cache_key,
            )
        if project_id and branch_id:
            self.repo.delete_user_cache(
                self._user_key(session.user.preferred_username),
                session.server.id,
                self._element_discovery_cache_key(project_id, branch_id),
            )
        self.sessions.add_recent_item(
            session,
            Bookmark(
                title=item.name,
                item_id=item.id,
                item_type=item.item_type,
                path=item.path,
                project_id=item.project_id,
                branch_id=item.branch_id,
            ),
        )
        return item

    def _publish_updated_item_to_shared_branch_cache(
        self,
        session: SessionData,
        item: ItemDetails,
        project_id: str,
        branch_id: str,
    ) -> bool:
        record = self.repo.get_cached_element(session.server.id, project_id, branch_id, item.id)
        if record is None:
            return False

        updated_payload = dict(record.payload)
        updated_payload["name"] = item.name
        updated_payload["human_name"] = item.name
        updated_payload["documentation"] = item.documentation_markdown or item.description
        if isinstance(item.source_payload, dict):
            for field in ("attributes", "references", "owned_element_ids", "applied_stereotype_ids", "spec_sections"):
                if field in item.source_payload:
                    updated_payload[field] = item.source_payload[field]

        now = utcnow()
        updated_record = record.model_copy(
            update={
                "name": item.name or record.name,
                "path": item.path or record.path,
                "item_type": item.item_type or record.item_type,
                "latest_revision": item.version or record.latest_revision,
                "payload": updated_payload,
                "source_user": session.user.preferred_username,
                "synced_at": now,
            }
        )
        self.repo.upsert_cached_elements([updated_record])
        summary = self.repo.get_branch_cache_summary(session.server.id, project_id, branch_id)
        if summary is not None:
            self.repo.upsert_branch_cache_summary(
                summary.model_copy(
                    update={
                        "latest_revision": item.version or summary.latest_revision,
                        "message": f"Element {item.id} was committed through Workbench by {session.user.preferred_username}.",
                        "updated_at": now,
                    }
                )
            )
        return True

    async def search(self, session: SessionData, query: str) -> SearchResponse:
        return await self._adapter_for_session(session).search(query)

    async def compare_items(
        self,
        session: SessionData,
        left_id: str,
        right_id: str,
        left_project_id: str | None = None,
        left_branch_id: str | None = None,
        right_project_id: str | None = None,
        right_branch_id: str | None = None,
    ) -> CompareResult:
        adapter = self._adapter_for_session(session)
        if left_project_id and left_project_id == right_project_id and left_id.isdigit() and right_id.isdigit():
            revision_diff = await adapter.compare_items(
                left_id,
                right_id,
                left_project_id,
                left_branch_id,
                right_project_id,
                right_branch_id,
            )
            if revision_diff.compare_type == "revisiondiff":
                return revision_diff

        left = (await self.get_item(session, left_id, left_project_id, left_branch_id)).model_dump(mode="json")
        right = (await self.get_item(session, right_id, right_project_id, right_branch_id)).model_dump(mode="json")
        differences: list[CompareDifference] = _dict_diff(left, right)
        return CompareResult(
            compare_type="item",
            left_id=left_id,
            right_id=right_id,
            summary=f"{len(differences)} field differences detected.",
            differences=differences,
            total_differences=len(differences),
        )

    async def compare_branches(
        self,
        session: SessionData,
        left_project_id: str,
        left_branch_id: str,
        right_project_id: str,
        right_branch_id: str,
    ) -> CompareResult:
        left_summary = self.get_branch_cache_summary_for_user(
            session.server.id,
            session.user.preferred_username,
            left_project_id,
            left_branch_id,
        )
        right_summary = self.get_branch_cache_summary_for_user(
            session.server.id,
            session.user.preferred_username,
            right_project_id,
            right_branch_id,
        )
        if left_summary is None:
            raise KeyError(f"Left project branch is not available in this user's Workbench cache: {left_project_id}/{left_branch_id}")
        if right_summary is None:
            raise KeyError(f"Right project branch is not available in this user's Workbench cache: {right_project_id}/{right_branch_id}")

        user_id = self._user_key(session.user.preferred_username)
        left_elements = self._visible_cached_elements_for_user(
            user_id,
            session.server.id,
            left_project_id,
            left_branch_id,
        )
        right_elements = self._visible_cached_elements_for_user(
            user_id,
            session.server.id,
            right_project_id,
            right_branch_id,
        )
        same_project = left_project_id == right_project_id
        left_by_key, left_id_aliases = self._branch_compare_records(left_elements, same_project=same_project)
        right_by_key, right_id_aliases = self._branch_compare_records(right_elements, same_project=same_project)

        max_returned_differences = 5000
        differences: list[CompareDifference] = []
        total_differences = 0
        added_elements = 0
        removed_elements = 0
        changed_elements = 0

        for match_key in sorted(set(left_by_key) | set(right_by_key), key=str.casefold):
            left_record = left_by_key.get(match_key)
            right_record = right_by_key.get(match_key)
            field_prefix = f"elements[{match_key}]"
            if left_record is None and right_record is not None:
                added_elements += 1
                total_differences += 1
                if len(differences) < max_returned_differences:
                    differences.append(
                        CompareDifference(
                            field_path=field_prefix,
                            left_value=None,
                            right_value=self._branch_compare_element_summary(right_record),
                            summary="Element added on the right",
                        )
                    )
                continue
            if right_record is None and left_record is not None:
                removed_elements += 1
                total_differences += 1
                if len(differences) < max_returned_differences:
                    differences.append(
                        CompareDifference(
                            field_path=field_prefix,
                            left_value=self._branch_compare_element_summary(left_record),
                            right_value=None,
                            summary="Element missing from the right",
                        )
                    )
                continue
            if left_record is None or right_record is None:
                continue

            left_document = self._branch_compare_element_document(left_record, left_id_aliases)
            right_document = self._branch_compare_element_document(right_record, right_id_aliases)
            element_differences = _dict_diff(left_document, right_document, field_prefix)
            if element_differences:
                changed_elements += 1
                total_differences += len(element_differences)
                remaining = max_returned_differences - len(differences)
                if remaining > 0:
                    differences.extend(element_differences[:remaining])

        compare_type = "branch" if same_project else "project"
        left_context = CompareContext(
            project_id=left_project_id,
            branch_id=left_branch_id,
            project_name=left_summary.project_name or left_project_id,
            branch_name=left_summary.branch_name or left_branch_id,
            revision=left_summary.latest_revision,
            element_count=len(left_elements),
        )
        right_context = CompareContext(
            project_id=right_project_id,
            branch_id=right_branch_id,
            project_name=right_summary.project_name or right_project_id,
            branch_name=right_summary.branch_name or right_branch_id,
            revision=right_summary.latest_revision,
            element_count=len(right_elements),
        )
        summary = (
            f"{total_differences} field differences across {added_elements} added, "
            f"{removed_elements} removed, and {changed_elements} changed elements."
        )
        return CompareResult(
            compare_type=compare_type,
            left_id=f"{left_project_id}:{left_branch_id}",
            right_id=f"{right_project_id}:{right_branch_id}",
            summary=summary,
            differences=differences,
            left_context=left_context,
            right_context=right_context,
            total_differences=total_differences,
            truncated=total_differences > len(differences),
        )

    def _branch_compare_records(
        self,
        records: list[CachedElementRecord],
        *,
        same_project: bool,
    ) -> tuple[dict[str, CachedElementRecord], dict[str, str]]:
        grouped: dict[str, list[CachedElementRecord]] = {}
        for record in records:
            if same_project:
                base_key = f"id:{record.element_id}"
            else:
                qualified_name = str(record.payload.get("qualified_name") or record.path or "").strip()
                metaclass = str(record.payload.get("metaclass") or record.item_type or "element").strip()
                if qualified_name:
                    base_key = f"path:{qualified_name.casefold()}|type:{metaclass.casefold()}"
                else:
                    base_key = f"id:{record.element_id}"
            grouped.setdefault(base_key, []).append(record)

        keyed: dict[str, CachedElementRecord] = {}
        aliases: dict[str, str] = {}
        for base_key, matches in grouped.items():
            ordered = sorted(matches, key=lambda item: (item.path.casefold(), item.name.casefold(), item.element_id))
            for index, record in enumerate(ordered, start=1):
                match_key = base_key if len(ordered) == 1 else f"{base_key}#{index}"
                keyed[match_key] = record
                aliases[record.element_id] = match_key
        return keyed, aliases

    def _branch_compare_element_document(self, record: CachedElementRecord, id_aliases: dict[str, str]) -> dict[str, Any]:
        payload = dict(record.payload)
        for identity_field in ("element_id", "elementId", "model_id", "modelId", "local_id", "localId"):
            payload.pop(identity_field, None)
        return {
            "name": record.name,
            "item_type": record.item_type,
            "path": record.path,
            "payload": self._branch_compare_normalize_value(payload, id_aliases),
        }

    def _branch_compare_normalize_value(self, value: Any, id_aliases: dict[str, str]) -> Any:
        if isinstance(value, dict):
            return {
                str(key): self._branch_compare_normalize_value(nested_value, id_aliases)
                for key, nested_value in value.items()
            }
        if isinstance(value, list):
            return [self._branch_compare_normalize_value(item, id_aliases) for item in value]
        if isinstance(value, tuple):
            return [self._branch_compare_normalize_value(item, id_aliases) for item in value]
        if isinstance(value, str):
            return id_aliases.get(value, value)
        return value

    def _branch_compare_element_summary(self, record: CachedElementRecord) -> dict[str, Any]:
        return {
            "id": record.element_id,
            "name": record.name,
            "item_type": record.item_type,
            "path": record.path,
        }

    def swagger_contract_manifest(self) -> SwaggerContractManifest:
        return self.contract.manifest()

    async def execute_swagger_operation(self, session: SessionData, payload: SwaggerExecuteRequest) -> SwaggerExecuteResponse:
        operation, candidate_path = self.contract.build_candidate_path(
            payload.operation_key,
            path_params=payload.path_params,
            query_params=payload.query_params,
        )
        content_payload, headers = self._swagger_content_payload(
            operation_key=payload.operation_key,
            body=payload.body,
            content_type=payload.content_type,
        )
        response, requested_path = await self._adapter_for_session(session).execute_contract_request(
            operation.method,
            candidate_path,
            content_payload=content_payload,
            extra_headers=headers,
            timeout=payload.timeout_seconds,
        )
        return self._swagger_response(payload.operation_key, operation.method, operation.path, requested_path, response)

    async def execute_swagger_upload(
        self,
        session: SessionData,
        *,
        operation_key: str,
        path_params: dict[str, Any],
        query_params: dict[str, Any],
        file_name: str,
        content_type: str,
        content: bytes,
    ) -> SwaggerExecuteResponse:
        operation, candidate_path = self.contract.build_candidate_path(
            operation_key,
            path_params=path_params,
            query_params=query_params,
        )
        if not operation.supports_file_upload:
            raise ValueError("This Swagger operation does not declare a file upload parameter.")
        file_parameter = next((parameter for parameter in operation.form_parameters if parameter.is_file), None)
        if file_parameter is None:
            raise ValueError("This Swagger operation does not declare a file upload parameter.")
        files = {file_parameter.name: (file_name, content, content_type or "application/octet-stream")}
        response, requested_path = await self._adapter_for_session(session).execute_contract_request(
            operation.method,
            candidate_path,
            files=files,
            timeout=60.0,
        )
        return self._swagger_response(operation_key, operation.method, operation.path, requested_path, response)

    async def oslc_status(self, session: SessionData) -> OSLCAuthorizationStatus:
        server = self._require_server(session.server.id, include_disabled=False)
        session_consumer = self.sessions.get_oslc_consumer_credentials(session)
        shared_consumer, _ = self._shared_oslc_consumer_credentials(server.id)
        resolved_consumer = self.oauth.effective_consumer_credentials(server, shared_consumer, session_consumer)
        configured = resolved_consumer is not None
        authorized = self.sessions.get_oslc_credentials(session) is not None
        consumer_source = resolved_consumer.source if resolved_consumer else "none"
        try:
            discovery = await self.oauth.discover(server)
            return OSLCAuthorizationStatus(
                server_id=server.id,
                configured=configured,
                authorized=authorized,
                rootservices=discovery.summary,
                consumer_key_configured=bool(resolved_consumer),
                consumer_key_source=consumer_source,
                can_generate_consumer_key=bool(discovery.summary.request_consumer_key_url),
            )
        except RuntimeError as exc:
            return OSLCAuthorizationStatus(
                server_id=server.id,
                configured=configured,
                authorized=authorized,
                consumer_key_configured=bool(resolved_consumer),
                consumer_key_source=consumer_source,
                message=str(exc),
            )

    async def generate_oslc_consumer(
        self,
        session: SessionData,
        *,
        consumer_name: str,
        consumer_secret: str,
        remember_for_session: bool = True,
    ) -> OSLCGenerateConsumerResponse:
        consumer_name = consumer_name.strip()
        consumer_secret = consumer_secret.strip()
        if not consumer_name or not consumer_secret:
            raise ValueError("OSLC consumer name and secret are required.")
        server = self._require_server(session.server.id, include_disabled=False)
        discovery = await self.oauth.discover(server)
        if not discovery.summary.request_consumer_key_url:
            raise RuntimeError("OSLC root services did not publish a consumer key registration URL.")
        consumer_key = await self.oauth.request_consumer_key(
            server,
            discovery.summary,
            consumer_name=consumer_name,
            consumer_secret=consumer_secret,
        )
        stored_for_session = False
        if remember_for_session:
            self.sessions.set_oslc_consumer_credentials(
                session,
                OSLCConsumerCredentials(
                    consumer_key=consumer_key,
                    consumer_secret=consumer_secret,
                    source="session",
                ),
            )
            self.sessions.clear_oslc_credentials(session)
            stored_for_session = True
        return OSLCGenerateConsumerResponse(
            consumer_key=consumer_key,
            request_consumer_key_url=discovery.summary.request_consumer_key_url,
            stored_for_session=stored_for_session,
            approval_required=True,
            message=(
                "The consumer key was generated successfully. It still must be approved in Magic Collaboration Studio Settings before OSLC authorization will succeed."
            ),
        )

    def set_oslc_consumer(self, session: SessionData, *, consumer_key: str, consumer_secret: str) -> OSLCAuthorizationStatus:
        consumer_key = consumer_key.strip()
        consumer_secret = consumer_secret.strip()
        if not consumer_key or not consumer_secret:
            raise ValueError("OSLC consumer key and secret are required.")
        self.sessions.set_oslc_consumer_credentials(
            session,
            OSLCConsumerCredentials(
                consumer_key=consumer_key,
                consumer_secret=consumer_secret,
                source="session",
            ),
        )
        self.sessions.clear_oslc_credentials(session)
        return OSLCAuthorizationStatus(
            server_id=session.server.id,
            configured=True,
            authorized=False,
            consumer_key_configured=True,
            consumer_key_source="session",
            message="Session-scoped OSLC consumer credentials were stored. If the key is already approved, you can connect OSLC now.",
        )

    def clear_oslc_consumer(self, session: SessionData) -> None:
        self.sessions.clear_oslc_consumer_credentials(session)
        self.sessions.clear_oslc_credentials(session)

    async def execute_oslc_request(self, session: SessionData, payload: OSLCExecuteRequest) -> OSLCExecuteResponse:
        server = self._require_server(session.server.id, include_disabled=False)
        credentials = self.sessions.get_oslc_credentials(session)
        if credentials is None:
            raise PermissionError("Connect OSLC for this server before running OSLC requests.")
        response = await self.oauth.signed_request(
            server,
            credentials,
            method="GET",
            path_or_url=payload.path_or_url,
            accept=payload.accept,
            timeout=payload.timeout_seconds,
        )
        return self._oslc_response(response, self.oauth.request_url(credentials.rootservices_url, payload.path_or_url))

    def disconnect_oslc(self, session: SessionData) -> None:
        self.sessions.clear_oslc_credentials(session)

    async def simulation_configs(self, session: SessionData, project_id: str | None) -> list[SimulationConfig]:
        return await self._adapter_for_session(session).list_simulation_configs(project_id)

    def simulation_history(self, session: SessionData) -> list[JobRecord]:
        return [job for job in self.jobs.list_jobs(session.user.preferred_username) if job.job_type == JobType.SIMULATION]

    def submit_simulation(self, session: SessionData, request: SimulationRunRequest) -> JobRecord:
        job = self.jobs.create_job(
            job_type=JobType.SIMULATION,
            title=f"Simulation: {request.config_id}",
            owner=session.user.preferred_username,
            server_id=session.server.id,
            payload=request.model_dump(mode="json"),
        )
        adapter = self._adapter_for_session(session)

        async def handler(context):
            return await adapter.run_simulation(request, context.report, context.cancel_requested)

        return self.jobs.submit(job, handler)

    def submit_publish(self, session: SessionData, request: PublishRequest) -> JobRecord:
        job = self.jobs.create_job(
            job_type=JobType.PUBLISH,
            title=f"Publish: {request.project_id}/{request.branch_id}",
            owner=session.user.preferred_username,
            server_id=session.server.id,
            payload=request.model_dump(mode="json"),
        )
        artifact_dir = self.settings.resolved_export_dir / "publish"

        async def handler(context):
            return await self.publisher.publish(request, artifact_dir, context.report, context.cancel_requested)

        return self.jobs.submit(job, handler)

    async def list_documents(self, session: SessionData):
        return await self._adapter_for_session(session).list_documents()

    async def get_document(self, session: SessionData, document_id: str):
        return await self._adapter_for_session(session).get_document(document_id)

    async def update_document(self, session: SessionData, document_id: str, body_markdown: str):
        return await self._adapter_for_session(session).update_document(document_id, body_markdown)

    async def list_attachments(self, session: SessionData, document_id: str):
        return await self._adapter_for_session(session).list_attachments(document_id)

    async def upload_attachment(self, session: SessionData, document_id: str, file_name: str, content_type: str, content: bytes):
        return await self._adapter_for_session(session).upload_attachment(document_id, file_name, content_type, content)

    async def delete_attachment(self, session: SessionData, document_id: str, attachment_id: str) -> bool:
        return await self._adapter_for_session(session).delete_attachment(document_id, attachment_id)

    async def get_attachment_path(self, session: SessionData, document_id: str, attachment_id: str) -> Path | None:
        return await self._adapter_for_session(session).get_attachment_file(document_id, attachment_id)

    async def list_comments(self, session: SessionData, document_id: str) -> list[CommentEntry]:
        return await self._adapter_for_session(session).list_comments(document_id)

    async def add_comment(self, session: SessionData, document_id: str, content: str) -> CommentEntry:
        return await self._adapter_for_session(session).add_comment(document_id, session.user.preferred_username, content)

    def list_jobs(self, session: SessionData) -> list[JobRecord]:
        return self.jobs.list_jobs(session.user.preferred_username)

    def get_job(self, session: SessionData, job_id: str) -> JobRecord | None:
        job = self.jobs.get_job(job_id)
        if not job or job.owner != session.user.preferred_username:
            return None
        return job

    def cancel_job(self, session: SessionData, job_id: str) -> JobRecord | None:
        job = self.jobs.get_job(job_id)
        if not job or job.owner != session.user.preferred_username:
            return None
        return self.jobs.cancel_job(job_id)

    def list_permission_refresh_audit(
        self,
        session: SessionData,
        user_id: str | None = None,
        *,
        limit: int = 100,
    ) -> list[PermissionRefreshAuditRecord]:
        return self.repo.list_permission_refresh_audit(session.server.id, user_id, limit=limit)

    def permission_inventory_status(self, session: SessionData) -> ServerPermissionInventoryStatus:
        inventory = self.repo.get_server_permission_inventory(session.server.id)
        audits = self.repo.list_server_permission_inventory_audit(session.server.id, limit=10)
        audit_counts = self.repo.server_permission_inventory_audit_counts(session.server.id)
        active_server_administrators = [
            item
            for item in self.sessions.list_active_sessions()
            if item.server.id == session.server.id and self._is_twc_server_administrator(item)
        ]
        jobs = [
            job
            for job in self.repo.list_jobs()
            if job.server_id == session.server.id and job.job_type == JobType.PERMISSION_INVENTORY_REFRESH
        ]
        latest_job = jobs[0] if jobs else None
        running = bool(latest_job and latest_job.status in {JobStatus.PENDING, JobStatus.RUNNING})
        due_at = (
            inventory.captured_at + timedelta(hours=self.settings.permission_inventory_refresh_hours)
            if inventory
            else None
        )
        if running:
            state = "refreshing"
        elif latest_job and latest_job.status == JobStatus.FAILED and self._server_permission_inventory_due(session.server.id):
            state = "failed"
        elif inventory is None:
            state = "missing"
        elif inventory.dirty:
            state = "dirty"
        else:
            state = "clean"
        messages = {
            "missing": "No complete server role/group inventory has been captured yet.",
            "clean": "The shared server role/group inventory is current.",
            "dirty": "A full upload changed the project registry. A background administrator refresh is due.",
            "refreshing": "The server role/group inventory is refreshing in the background.",
            "failed": "The last background inventory refresh failed; the prior complete inventory remains available.",
        }
        warning = None
        if self._server_permission_inventory_due(session.server.id) and not active_server_administrators:
            warning = "Inventory refresh is due, but no active TWC Server Administrator session is available."
        consecutive_failures = 0
        for audit in audits:
            if audit.status == "succeeded":
                break
            if audit.status == "failed":
                consecutive_failures += 1
        return ServerPermissionInventoryStatus(
            server_id=session.server.id,
            state=state,
            dirty=bool(inventory and inventory.dirty),
            role_count=len(inventory.roles) if inventory else 0,
            group_count=len(inventory.groups) if inventory else 0,
            captured_at=inventory.captured_at if inventory else None,
            refresh_due_at=due_at,
            current_user_can_refresh=self._is_twc_server_administrator(session),
            last_job_id=latest_job.id if latest_job else None,
            last_job_status=latest_job.status if latest_job else None,
            last_attempt_at=(latest_job.started_at or latest_job.created_at) if latest_job else None,
            last_triggered_by=latest_job.owner if latest_job else None,
            last_failure=(latest_job.message if latest_job and latest_job.status == JobStatus.FAILED else None),
            active_server_administrator_count=len(active_server_administrators),
            inventory_age_seconds=(max(0, int((utcnow() - inventory.captured_at).total_seconds())) if inventory else None),
            successful_refresh_count=audit_counts.get("succeeded", 0),
            failed_refresh_count=audit_counts.get("failed", 0),
            consecutive_failure_count=consecutive_failures,
            alert_forwarding_configured=bool(getattr(self.settings, "permission_alert_webhook_url", None)),
            last_duration_ms=(audits[0].duration_ms if audits else None),
            last_affected_user_count=(audits[0].affected_user_count if audits else 0),
            audit_count=sum(audit_counts.values()),
            warning=warning,
            recent_audits=audits[:10],
            message=messages[state],
        )

    def list_server_permission_inventory_audit(
        self,
        session: SessionData,
        *,
        limit: int = 100,
    ) -> list[ServerPermissionInventoryAuditRecord]:
        return self.repo.list_server_permission_inventory_audit(session.server.id, limit=limit)

    @staticmethod
    def _server_permission_inventory_hash(inventory: ServerPermissionInventory | None) -> str:
        if inventory is None:
            return ""
        encoded = json.dumps(
            {"roles": inventory.roles, "groups": inventory.groups},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    async def _forward_permission_inventory_failure_alert(
        self,
        *,
        server_id: str,
        job_id: str,
        triggered_by: str,
        reason: str,
        error: str,
    ) -> None:
        webhook_url = self.settings.permission_alert_webhook_url
        if not webhook_url:
            return
        audits = self.repo.list_server_permission_inventory_audit(server_id, limit=100)
        consecutive_failures = 0
        for audit in audits:
            if audit.status == "succeeded":
                break
            if audit.status == "failed":
                consecutive_failures += 1
        threshold = self.settings.permission_refresh_warning_failures
        if consecutive_failures < threshold or consecutive_failures % threshold != 0:
            return
        payload = {
            "event": "twc_permission_inventory_refresh_repeated_failure",
            "server_id": server_id,
            "job_id": job_id,
            "triggered_by": triggered_by,
            "reason": reason,
            "consecutive_failures": consecutive_failures,
            "error": error,
            "occurred_at": utcnow().isoformat(),
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(webhook_url, json=payload)
                response.raise_for_status()
            logger.info(
                "twc-server-permission-inventory-alert-forwarded",
                server_id=server_id,
                job_id=job_id,
                consecutive_failures=consecutive_failures,
            )
        except Exception as alert_exc:
            logger.warning(
                "twc-server-permission-inventory-alert-forward-failed",
                server_id=server_id,
                job_id=job_id,
                detail=self._permission_error_text(alert_exc),
            )

    def _server_permission_inventory_due(self, server_id: str) -> bool:
        inventory = self.repo.get_server_permission_inventory(server_id)
        return bool(
            inventory is None
            or inventory.dirty
            or inventory.captured_at + timedelta(hours=self.settings.permission_inventory_refresh_hours) <= utcnow()
        )

    def _submit_server_permission_inventory_refresh(
        self,
        session: SessionData,
        *,
        reason: str,
        force: bool = False,
    ) -> JobRecord | None:
        if not self._is_twc_server_administrator(session) or (not force and not self._server_permission_inventory_due(session.server.id)):
            return None
        existing_job = next(
            (
                job
                for job in self.repo.list_jobs()
                if job.server_id == session.server.id
                and job.job_type == JobType.PERMISSION_INVENTORY_REFRESH
                and job.status in {JobStatus.PENDING, JobStatus.RUNNING}
                and job.updated_at >= utcnow() - timedelta(minutes=5)
            ),
            None,
        )
        if existing_job is not None:
            return existing_job
        job = self.jobs.create_job(
            job_type=JobType.PERMISSION_INVENTORY_REFRESH,
            title="Refresh Teamwork Cloud server roles and groups",
            owner=session.user.preferred_username,
            server_id=session.server.id,
            payload={"reason": reason},
        )

        async def handler(context) -> dict[str, Any]:
            started_at = utcnow()
            await context.report(10, "Loading Teamwork Cloud server roles and groups")
            live_session = self.sessions.get_session(session.session_id)
            if live_session is None:
                raise RuntimeError("The Server Administrator session ended before the inventory refresh started.")
            live_session = await self._refresh_session_credentials_if_needed(live_session)
            lease_key = f"permission-inventory:{live_session.server.id}"
            lease_owner = f"{self._permission_refresh_instance_id}:{job.id}"
            acquired = self.repo.acquire_permission_refresh_lease(
                lease_key,
                lease_owner,
                ttl_seconds=self.settings.permission_refresh_lease_seconds,
            )
            if not acquired:
                current = self.repo.get_server_permission_inventory(live_session.server.id)
                self.repo.append_server_permission_inventory_audit(
                    ServerPermissionInventoryAuditRecord(
                        server_id=live_session.server.id,
                        job_id=job.id,
                        triggered_by=live_session.user.preferred_username,
                        reason=reason,
                        status="coalesced",
                        previous_hash=self._server_permission_inventory_hash(current),
                        current_hash=self._server_permission_inventory_hash(current),
                        previous_role_count=len(current.roles) if current else 0,
                        current_role_count=len(current.roles) if current else 0,
                        previous_group_count=len(current.groups) if current else 0,
                        current_group_count=len(current.groups) if current else 0,
                        duration_ms=max(0, int((utcnow() - started_at).total_seconds() * 1000)),
                    )
                )
                return {"coalesced": True, "server_id": live_session.server.id}
            previous = self.repo.get_server_permission_inventory(live_session.server.id)

            async def renew_inventory_lease() -> None:
                interval = max(self.settings.permission_refresh_lease_seconds // 3, 20)
                while True:
                    await asyncio.sleep(interval)
                    if not self.repo.renew_permission_refresh_lease(
                        lease_key,
                        lease_owner,
                        ttl_seconds=self.settings.permission_refresh_lease_seconds,
                    ):
                        logger.warning(
                            "twc-server-permission-inventory-lease-lost",
                            server_id=live_session.server.id,
                            job_id=job.id,
                        )
                        return

            lease_heartbeat = asyncio.create_task(
                renew_inventory_lease(),
                name=f"twc-permission-inventory-lease-{live_session.server.id}",
            )
            try:
                inventory = await self._server_permission_inventory(
                    self._adapter_for_session(live_session),
                    live_session.server.id,
                    allow_refresh=True,
                    force_refresh=force,
                )
                if (
                    inventory is None
                    or inventory.dirty
                    or inventory.captured_at + timedelta(hours=self.settings.permission_inventory_refresh_hours) <= utcnow()
                ):
                    raise RuntimeError("Teamwork Cloud did not return a complete current server role/group inventory.")
                self.repo.append_server_permission_inventory_audit(
                    ServerPermissionInventoryAuditRecord(
                        server_id=live_session.server.id,
                        job_id=job.id,
                        triggered_by=live_session.user.preferred_username,
                        reason=reason,
                        status="succeeded",
                        previous_hash=self._server_permission_inventory_hash(previous),
                        current_hash=self._server_permission_inventory_hash(inventory),
                        previous_role_count=len(previous.roles) if previous else 0,
                        current_role_count=len(inventory.roles),
                        previous_group_count=len(previous.groups) if previous else 0,
                        current_group_count=len(inventory.groups),
                        affected_user_count=len({
                            self._user_key(item.user.preferred_username)
                            for item in self.sessions.list_active_sessions()
                            if item.server.id == live_session.server.id
                        }),
                        duration_ms=max(0, int((utcnow() - started_at).total_seconds() * 1000)),
                    )
                )
                await context.report(95, "Server role/group inventory replaced; user permission snapshots marked due")
                return {
                    "server_id": live_session.server.id,
                    "captured_at": inventory.captured_at.isoformat(),
                    "role_count": len(inventory.roles),
                    "group_count": len(inventory.groups),
                    "affected_user_count": len({
                        self._user_key(item.user.preferred_username)
                        for item in self.sessions.list_active_sessions()
                        if item.server.id == live_session.server.id
                    }),
                    "reason": reason,
                }
            except Exception as exc:
                current = self.repo.get_server_permission_inventory(live_session.server.id)
                safe_error = self._permission_error_text(exc)
                self.repo.append_server_permission_inventory_audit(
                    ServerPermissionInventoryAuditRecord(
                        server_id=live_session.server.id,
                        job_id=job.id,
                        triggered_by=live_session.user.preferred_username,
                        reason=reason,
                        status="failed",
                        previous_hash=self._server_permission_inventory_hash(previous),
                        current_hash=self._server_permission_inventory_hash(current),
                        previous_role_count=len(previous.roles) if previous else 0,
                        current_role_count=len(current.roles) if current else 0,
                        previous_group_count=len(previous.groups) if previous else 0,
                        current_group_count=len(current.groups) if current else 0,
                        duration_ms=max(0, int((utcnow() - started_at).total_seconds() * 1000)),
                        error=safe_error,
                    )
                )
                await self._forward_permission_inventory_failure_alert(
                    server_id=live_session.server.id,
                    job_id=job.id,
                    triggered_by=live_session.user.preferred_username,
                    reason=reason,
                    error=safe_error,
                )
                raise
            finally:
                lease_heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await lease_heartbeat
                self.repo.release_permission_refresh_lease(lease_key, lease_owner)

        return self.jobs.submit(job, handler)

    def retry_server_permission_inventory(self, session: SessionData) -> JobRecord:
        if not self._is_twc_server_administrator(session):
            raise PermissionError("A current TWC Server Administrator session is required.")
        job = self._submit_server_permission_inventory_refresh(
            session,
            reason="administrator-manual-retry",
            force=True,
        )
        if job is None:
            raise RuntimeError("The inventory refresh could not be queued.")
        return job

    def _fallback_cache_window(self, now: datetime | None = None) -> tuple[bool, str | None, datetime]:
        timezone = ZoneInfo(self.settings.fallback_cache_sync_timezone)
        local_now = (now or utcnow()).astimezone(timezone)
        hour, minute = (int(part) for part in self.settings.fallback_cache_sync_time.split(":", 1))
        today_start = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        starts = (today_start - timedelta(days=1), today_start)
        for start in starts:
            if start <= local_now < start + timedelta(minutes=self.settings.fallback_cache_sync_window_minutes):
                return True, start.date().isoformat(), local_now
        return False, None, local_now

    def fallback_cache_refresh_status(self, session: SessionData) -> FallbackCacheRefreshStatus:
        _, _, local_now = self._fallback_cache_window()
        summaries = self.repo.list_branch_cache_summaries(session.server.id)
        self._active_fallback_cache_refresh_job(session.server.id)
        jobs = [
            job
            for job in self.repo.list_jobs()
            if job.server_id == session.server.id and job.job_type == JobType.FALLBACK_CACHE_REFRESH
        ]
        latest_job = jobs[0] if jobs else None
        active_admins = [
            item
            for item in self.sessions.list_active_sessions()
            if item.server.id == session.server.id and self._is_twc_server_administrator(item)
        ]
        message = (
            "REST model and element fallback is disabled. Workbench uses TWC REST only for permission data; "
            "Cameo plugin snapshots populate projects, branches, models, and elements."
        )
        return FallbackCacheRefreshStatus(
            server_id=session.server.id,
            schedule_time=self.settings.fallback_cache_sync_time,
            schedule_timezone=self.settings.fallback_cache_sync_timezone,
            schedule_window_minutes=self.settings.fallback_cache_sync_window_minutes,
            current_local_time=local_now,
            current_user_can_refresh=False,
            active_server_administrator_count=len(active_admins),
            fallback_branch_count=sum(not self._is_plugin_managed_summary(item) for item in summaries),
            plugin_branch_count=sum(self._is_plugin_managed_summary(item) for item in summaries),
            last_job_id=latest_job.id if latest_job else None,
            last_job_status=latest_job.status if latest_job else None,
            last_job_message=latest_job.message if latest_job else None,
            last_triggered_by=latest_job.owner if latest_job else None,
            last_trigger_reason=str(latest_job.payload.get("reason") or "") if latest_job else None,
            last_started_at=latest_job.started_at if latest_job else None,
            last_finished_at=latest_job.finished_at if latest_job else None,
            nightly_window_open=False,
            message=message,
        )

    def _active_fallback_cache_refresh_job(self, server_id: str) -> JobRecord | None:
        now = utcnow()
        stale_pending_before = now - timedelta(minutes=1)
        for job in self.repo.list_jobs():
            if job.server_id != server_id or job.job_type != JobType.FALLBACK_CACHE_REFRESH:
                continue
            if job.status == JobStatus.PENDING and job.updated_at <= stale_pending_before:
                job.status = JobStatus.FAILED
                job.message = "Background fallback refresh never started; it may be queued again."
                job.logs.append(f"[{now.strftime('%H:%M:%S')}] ERROR {job.message}")
                job.updated_at = now
                job.finished_at = now
                self.repo.upsert_job(job)
                continue
            if job.status in {JobStatus.PENDING, JobStatus.RUNNING}:
                return job
        return None

    def _submit_fallback_cache_refresh(
        self,
        session: SessionData,
        request: FallbackCacheRefreshRequest,
        *,
        reason: str,
        schedule_date: str | None = None,
    ) -> JobRecord:
        raise RuntimeError(
            "TWC REST model and element fallback is disabled. "
            "Use the Cameo Workbench plugin to publish a model snapshot."
        )
        if not self._is_twc_server_administrator(session):
            raise PermissionError("A current TWC Server Administrator session is required.")
        if request.branch_id and not request.project_id:
            raise ValueError("project_id is required when branch_id is supplied.")
        active = self._active_fallback_cache_refresh_job(session.server.id)
        if active is not None:
            return active
        payload: dict[str, Any] = {
            "reason": reason,
            "project_id": request.project_id,
            "branch_id": request.branch_id,
        }
        if schedule_date:
            payload["schedule_date"] = schedule_date
        job = self.jobs.create_job(
            job_type=JobType.FALLBACK_CACHE_REFRESH,
            title="Refresh TWC REST fallback model caches",
            owner=session.user.preferred_username,
            server_id=session.server.id,
            payload=payload,
        )

        async def handler(context) -> dict[str, Any]:
            live_session = self.sessions.get_session(session.session_id)
            if live_session is None:
                raise RuntimeError("The TWC Server Administrator session ended before fallback refresh started.")
            live_session = await self._refresh_session_credentials_if_needed(live_session)
            lease_key = f"fallback-cache:{live_session.server.id}"
            lease_owner = f"{self._permission_refresh_instance_id}:{job.id}"
            if not self.repo.acquire_permission_refresh_lease(
                lease_key,
                lease_owner,
                ttl_seconds=self.settings.permission_refresh_lease_seconds,
            ):
                return {"coalesced": True, "server_id": live_session.server.id}

            async def renew_lease() -> None:
                interval = max(self.settings.permission_refresh_lease_seconds // 3, 20)
                while True:
                    await asyncio.sleep(interval)
                    if not self.repo.renew_permission_refresh_lease(
                        lease_key,
                        lease_owner,
                        ttl_seconds=self.settings.permission_refresh_lease_seconds,
                    ):
                        return

            heartbeat = asyncio.create_task(renew_lease(), name=f"twc-fallback-cache-lease-{live_session.server.id}")
            try:
                await context.report(2, "Discovering TWC projects and branches")
                adapter = self._adapter_for_session(live_session)
                projects = await adapter.list_projects(include_branches=True)
                if request.project_id:
                    projects = [item for item in projects if item.id == request.project_id]
                    if not projects:
                        raise RuntimeError(f"Project {request.project_id} was not returned by TWC.")

                targets: list[tuple[ProjectSummary, BranchSummary]] = []
                for project in projects:
                    branches = project.branches
                    if not branches:
                        branches = await adapter.list_project_branches(project.id, project.workspace_id)
                    if request.branch_id:
                        branches = [item for item in branches if item.id == request.branch_id]
                    targets.extend((project, branch) for branch in branches)
                if request.branch_id and not targets:
                    raise RuntimeError(f"Branch {request.branch_id} was not returned by TWC.")

                eligible = [
                    (project, branch)
                    for project, branch in targets
                    if not self._is_plugin_managed_summary(
                        self.repo.get_branch_cache_summary(live_session.server.id, project.id, branch.id)
                    )
                ]
                skipped_plugin = len(targets) - len(eligible)
                refreshed = 0
                superseded = 0
                failures: list[dict[str, str]] = []
                server_lock = self._model_cache_server_lock(live_session.server.id)
                async with server_lock:
                    for index, (project, branch) in enumerate(eligible, start=1):
                        if context.cancel_requested():
                            break

                        async def branch_report(percent: int, message: str, *, position: int = index) -> None:
                            overall = 5 + int(((position - 1) + percent / 100) * 90 / max(1, len(eligible)))
                            await context.report(min(95, overall), f"{project.name} / {branch.name}: {message}")

                        try:
                            result = await self._run_branch_cache_sync(
                                live_session,
                                adapter,
                                project.id,
                                branch.id,
                                project.workspace_id,
                                branch_report,
                                context.cancel_requested,
                                job.id,
                                project_name=project.name,
                                branch_name=branch.name,
                            )
                            if result.get("superseded_by_plugin"):
                                superseded += 1
                            elif not result.get("cancelled"):
                                refreshed += 1
                        except Exception as exc:
                            failures.append({
                                "project_id": project.id,
                                "branch_id": branch.id,
                                "error": self._permission_error_text(exc),
                            })
                if eligible and refreshed == 0 and superseded == 0 and failures:
                    raise RuntimeError(f"Every eligible fallback branch failed; first error: {failures[0]['error']}")
                await context.report(98, "Fallback refresh complete; user permission snapshots are queued for background replacement")
                self.sessions.mark_server_permission_snapshots_due(live_session.server.id)
                return {
                    "server_id": live_session.server.id,
                    "reason": reason,
                    "schedule_date": schedule_date,
                    "discovered_branch_count": len(targets),
                    "refreshed_branch_count": refreshed,
                    "plugin_branch_count": skipped_plugin,
                    "superseded_by_plugin_count": superseded,
                    "failed_branch_count": len(failures),
                    "failures": failures[:100],
                    "cancelled": context.cancel_requested(),
                }
            finally:
                heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat
                self.repo.release_permission_refresh_lease(lease_key, lease_owner)

        return self.jobs.submit(job, handler)

    def trigger_fallback_cache_refresh(
        self,
        session: SessionData,
        request: FallbackCacheRefreshRequest,
    ) -> JobRecord:
        return self._submit_fallback_cache_refresh(session, request, reason="server-administrator-manual-trigger")

    async def refresh_due_fallback_caches(self) -> None:
        return None
        window_open, schedule_date, _ = self._fallback_cache_window()
        if not window_open or not schedule_date:
            return
        sessions_by_server: dict[str, list[SessionData]] = {}
        for session in self.sessions.list_active_sessions():
            if self._is_twc_server_administrator(session):
                sessions_by_server.setdefault(session.server.id, []).append(session)
        for server_id, sessions in sessions_by_server.items():
            already_attempted = any(
                job.server_id == server_id
                and job.job_type == JobType.FALLBACK_CACHE_REFRESH
                and job.payload.get("reason") == "nightly-fallback-window"
                and job.payload.get("schedule_date") == schedule_date
                for job in self.repo.list_jobs()
            )
            if already_attempted:
                continue
            representative = max(sessions, key=lambda item: item.expires_at)
            self._submit_fallback_cache_refresh(
                representative,
                FallbackCacheRefreshRequest(),
                reason="nightly-fallback-window",
                schedule_date=schedule_date,
            )

    async def refresh_due_server_permission_inventories(self) -> None:
        sessions_by_server: dict[str, list[SessionData]] = {}
        for session in self.sessions.list_active_sessions():
            if self._is_twc_server_administrator(session):
                sessions_by_server.setdefault(session.server.id, []).append(session)
        for sessions in sessions_by_server.values():
            representative = max(sessions, key=lambda item: item.expires_at)
            self._submit_server_permission_inventory_refresh(
                representative,
                reason="active-administrator-dirty-inventory",
            )

    def current_permission_status(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
        model_id: str | None = None,
    ) -> CurrentPermissionStatus:
        user_id = self._user_key(session.user.preferred_username)
        server_id = session.server.id
        summary = self.repo.get_branch_cache_summary(server_id, project_id, branch_id)
        plugin_managed = self._is_plugin_managed_summary(summary)
        branch = (
            self._plugin_branch_access_or_source_fallback(
                user_id,
                server_id,
                project_id,
                branch_id,
                summary,
            )
            if plugin_managed
            else self.repo.get_branch_access_record(user_id, server_id, project_id, branch_id)
        )
        model_permissions = self._permissions_by_model_for_user(user_id, server_id, project_id, branch_id)
        visible_permissions = [
            permission
            for permission in model_permissions.values()
            if permission.accessible and not permission.restricted
        ]
        branch_accessible = (
            bool(branch and branch.accessible)
            if plugin_managed
            else bool(visible_permissions)
        )
        branch_editable = (
            bool(branch_accessible and branch and branch.editable)
            if plugin_managed
            else bool(branch_accessible and any(permission.editable for permission in visible_permissions))
        )
        model = model_permissions.get(model_id) if model_id else None
        cached_model = self.repo.get_cached_model(server_id, project_id, branch_id, model_id) if model_id else None
        model_accessible = (
            bool(branch_accessible and cached_model)
            if plugin_managed and model_id
            else bool(branch_accessible and model and model.accessible and not model.restricted)
            if model_id
            else None
        )
        model_editable = (
            bool(model_accessible and branch_editable)
            if plugin_managed and model_id
            else bool(model_accessible and model and model.editable)
            if model_id
            else None
        )
        return CurrentPermissionStatus(
            project_id=project_id,
            branch_id=branch_id,
            model_id=model_id,
            project_accessible=branch_accessible or any(
                record.accessible and record.project_id == project_id
                for record in self.repo.list_user_branch_access_records(user_id, server_id)
            ),
            branch_accessible=branch_accessible,
            branch_editable=branch_editable,
            branch_admin_access=bool(branch_accessible and branch and branch.admin_access),
            model_accessible=model_accessible,
            model_editable=model_editable,
            snapshot_updated_at=(branch.updated_at if branch else summary.updated_at if summary else None),
        )

    def submit_export(self, session: SessionData, request: ExportRequest) -> JobRecord:
        job = self.jobs.create_job(
            job_type=JobType.EXPORT,
            title=f"Export: {request.export_type}/{request.export_format}",
            owner=session.user.preferred_username,
            server_id=session.server.id,
            payload=request.model_dump(mode="json"),
        )
        export_dir = self.settings.resolved_export_dir / "exports"

        async def handler(context):
            return await self._run_export(session, request, export_dir, context.report, context.cancel_requested)

        return self.jobs.submit(job, handler)

    async def _run_export(self, session: SessionData, request: ExportRequest, export_dir: Path, report, cancel_requested):
        export_dir.mkdir(parents=True, exist_ok=True)
        await report(15, "Loading export source")
        payload = await self._resolve_export_payload(session, request)
        if cancel_requested():
            return {"cancelled": True}
        await report(60, f"Rendering {request.export_format.upper()} artifact")
        artifact_path = self._write_export(export_dir, request, payload)
        await report(100, "Export ready")
        return {"artifact_path": str(artifact_path), "format": request.export_format}

    async def _resolve_export_payload(self, session: SessionData, request: ExportRequest) -> dict[str, Any]:
        if request.export_type == "item" and request.reference_id:
            item = await self.get_item(session, request.reference_id, request.project_id, request.branch_id)
            return item.model_dump(mode="json")
        if request.export_type == "compare":
            return request.payload
        if request.export_type == "search":
            search = await self.search(session, str(request.payload.get("query", "")))
            return search.model_dump(mode="json")
        if request.export_type == "simulation":
            job = self.get_job(session, str(request.reference_id or ""))
            return job.model_dump(mode="json") if job else {}
        return request.payload

    def _write_export(self, export_dir: Path, request: ExportRequest, payload: dict[str, Any]) -> Path:
        base_name = f"{request.export_type}-{request.reference_id or 'workspace'}"
        if request.export_format == "json":
            output = export_dir / f"{base_name}.json"
            output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return output
        if request.export_format == "markdown":
            output = export_dir / f"{base_name}.md"
            output.write_text(self._to_markdown(payload), encoding="utf-8")
            return output
        if request.export_format == "html":
            output = export_dir / f"{base_name}.html"
            output.write_text(self._to_html(payload), encoding="utf-8")
            return output
        if request.export_format == "csv":
            output = export_dir / f"{base_name}.csv"
            output.write_text(self._to_csv(payload), encoding="utf-8")
            return output
        output = export_dir / f"{base_name}.pdf"
        output.write_bytes(render_pdf_document("Export", json.dumps(payload, indent=2)))
        return output

    def _to_markdown(self, payload: dict[str, Any]) -> str:
        lines = ["# Export", ""]
        for key, value in payload.items():
            lines.append(f"## {key}")
            lines.append("")
            lines.append(f"```json\n{json.dumps(value, indent=2)}\n```")
            lines.append("")
        return "\n".join(lines)

    def _to_html(self, payload: dict[str, Any]) -> str:
        pretty = json.dumps(payload, indent=2)
        return (
            "<!doctype html><html><head><meta charset='utf-8'><title>Export</title>"
            "<style>body{font-family:IBM Plex Sans,Arial,sans-serif;margin:2rem;background:#f5f7fb;color:#14213d;}pre{background:white;padding:1rem;border-radius:14px;box-shadow:0 18px 45px rgba(20,33,61,.08);}</style>"
            "</head><body><h1>Export</h1><pre>"
            + pretty.replace("<", "&lt;")
            + "</pre></body></html>"
        )

    def _to_csv(self, payload: dict[str, Any]) -> str:
        stream = StringIO()
        writer = csv.writer(stream)
        writer.writerow(["field", "value"])
        for key, value in payload.items():
            writer.writerow([key, json.dumps(value)])
        return stream.getvalue()

    def artifact_path(self, session: SessionData, job_id: str) -> Path | None:
        job = self.get_job(session, job_id)
        if not job or not job.artifact_path:
            return None
        path = Path(job.artifact_path)
        if path.exists():
            return path
        return None

    def _swagger_content_payload(
        self,
        *,
        operation_key: str,
        body: Any,
        content_type: str | None,
    ) -> tuple[str | bytes | None, dict[str, str]]:
        operation = self.contract.operation(operation_key)
        if body is None:
            if operation.request_body and operation.request_body.required:
                raise ValueError("This Swagger operation requires a request body.")
            return None, {}
        if operation.request_body is None:
            raise ValueError("This Swagger operation does not declare a request body.")

        valid_content_types = operation.request_body.content_types
        selected_content_type = content_type or (valid_content_types[0] if valid_content_types else "application/json")
        if valid_content_types and selected_content_type not in valid_content_types:
            raise ValueError(
                f"Content-Type '{selected_content_type}' is not declared by this operation. "
                f"Allowed: {', '.join(valid_content_types)}"
            )

        if selected_content_type == "text/plain":
            if isinstance(body, str):
                content_payload = body
            elif isinstance(body, (list, tuple, set)):
                content_payload = ",".join(str(item) for item in body)
            elif isinstance(body, dict) and "value" in body:
                content_payload = str(body["value"])
            else:
                content_payload = json.dumps(body, separators=(",", ":"))
        elif "json" in selected_content_type:
            if isinstance(body, str):
                try:
                    json.loads(body)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Request body is not valid JSON for {selected_content_type}: {exc.msg}") from exc
                content_payload = body
            else:
                content_payload = json.dumps(body)
        else:
            content_payload = body if isinstance(body, (str, bytes)) else json.dumps(body)

        return content_payload, {"Content-Type": selected_content_type}

    def _swagger_response(
        self,
        operation_key: str,
        method: str,
        path: str,
        requested_path: str,
        response: httpx.Response,
    ) -> SwaggerExecuteResponse:
        force_download = "download=true" in requested_path.lower()
        content_type, content, body, text, body_base64, is_binary, visible_headers = self._response_payload(
            response,
            force_download=force_download,
        )
        return SwaggerExecuteResponse(
            operation_key=operation_key,
            method=method,
            path=path,
            requested_path=requested_path,
            status_code=response.status_code,
            ok=200 <= response.status_code < 300,
            content_type=content_type,
            headers=visible_headers,
            body=body,
            text=text,
            body_base64=body_base64,
            is_binary=is_binary,
            size_bytes=len(content),
            filename=self._filename_from_content_disposition(response.headers.get("content-disposition", "")),
        )

    def _oslc_response(self, response: httpx.Response, requested_url: str) -> OSLCExecuteResponse:
        content_type, content, body, text, body_base64, is_binary, visible_headers = self._response_payload(response)
        return OSLCExecuteResponse(
            requested_url=requested_url,
            status_code=response.status_code,
            ok=200 <= response.status_code < 300,
            content_type=content_type,
            headers=visible_headers,
            body=body,
            text=text,
            body_base64=body_base64,
            is_binary=is_binary,
            size_bytes=len(content),
            filename=self._filename_from_content_disposition(response.headers.get("content-disposition", "")),
        )

    def _response_payload(
        self,
        response: httpx.Response,
        *,
        force_download: bool = False,
    ) -> tuple[str, bytes, Any, str | None, str | None, bool, dict[str, str]]:
        content_type = response.headers.get("content-type", "")
        content = response.content or b""
        body: Any = None
        text: str | None = None
        body_base64: str | None = None
        is_binary = False

        if content:
            if "application/json" in content_type or "application/ld+json" in content_type or "application/problem+json" in content_type:
                try:
                    body = response.json()
                except ValueError:
                    text = response.text
            elif force_download or not self._is_textual_content_type(content_type):
                body_base64 = base64.b64encode(content).decode("ascii")
                is_binary = True
            else:
                text = response.text

        visible_headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in {"set-cookie", "authorization", "proxy-authorization"}
        }
        return content_type, content, body, text, body_base64, is_binary, visible_headers

    def _is_textual_content_type(self, content_type: str) -> bool:
        normalized = content_type.lower()
        return normalized.startswith("text/") or any(marker in normalized for marker in ("xml", "html", "csv"))

    def _filename_from_content_disposition(self, content_disposition: str) -> str | None:
        for part in content_disposition.split(";"):
            name, _, value = part.strip().partition("=")
            if name.lower() == "filename" and value:
                return value.strip().strip('"')
        return None

    def _adapter_for_session(self, session: SessionData) -> TeamworkAdapter:
        return self._adapter_for_credentials(session.server, self.sessions.get_credentials(session))

    def _adapter_for_credentials(self, server: ServerProfile, tokens) -> TeamworkAdapter:
        return create_adapter(server, tokens, self.settings.resolved_data_dir)

    def _token_bundle_from_login_token(self, raw_token: str) -> TokenBundle:
        token = raw_token.strip()
        for scheme in ("Basic", "Bearer", "Token"):
            prefix = f"{scheme} "
            if token.lower().startswith(prefix.lower()):
                access_token = token[len(prefix):].strip()
                return TokenBundle(
                    access_token=access_token,
                    token_type=scheme,
                    expires_at=infer_token_expiry(access_token) if scheme != "Basic" else None,
                )
        if ":" in token:
            encoded = base64.b64encode(token.encode("utf-8")).decode("ascii")
            return TokenBundle(access_token=encoded, token_type="Basic")
        return TokenBundle(access_token=token, token_type="Token", expires_at=infer_token_expiry(token))

    async def _refresh_session_credentials_if_needed(self, session: SessionData) -> SessionData:
        credentials = self.sessions.get_credentials(session)
        refreshed_credentials = await self._refresh_twc_credentials_if_needed(session.server, credentials)
        if refreshed_credentials is not credentials:
            self.sessions.update_credentials(session, refreshed_credentials)
        return session

    async def _refresh_twc_credentials_if_needed(self, server: ServerProfile, credentials: TokenBundle) -> TokenBundle:
        if credentials.token_type != "Token":
            return credentials
        if not credentials.access_token:
            return credentials

        expires_at = credentials.expires_at or infer_token_expiry(credentials.id_token) or infer_token_expiry(credentials.access_token)
        if expires_at and credentials.expires_at != expires_at:
            credentials = credentials.model_copy(update={"expires_at": expires_at})

        refresh_skew = timedelta(seconds=90)
        now = datetime.now(UTC)
        if expires_at and expires_at > now + refresh_skew:
            return credentials
        if not credentials.refresh_token:
            if expires_at and expires_at <= now:
                raise PermissionError("Your Teamwork Cloud session expired. Sign in again.")
            return credentials

        try:
            refreshed = await refresh_twc_auth_token(self.settings, server, credentials.refresh_token)
        except PermissionError as exc:
            if expires_at and expires_at > now:
                logger.warning("twc-token-refresh-failed", server_id=server.id, detail=str(exc))
                return credentials
            raise PermissionError("Your Teamwork Cloud login expired and could not be refreshed. Sign in again.") from exc

        return refreshed.model_copy(
            update={
                "refresh_token": refreshed.refresh_token or credentials.refresh_token,
                "session_cookies": credentials.session_cookies,
                "upstream_user": credentials.upstream_user,
            }
        )

    async def _create_authenticated_session(
        self,
        server: ServerProfile,
        credentials: TokenBundle,
        *,
        fallback_username: str | None = None,
        upstream_roles: list[str] | None = None,
        upstream_groups: list[str] | None = None,
        log_event: str,
    ) -> SessionData:
        adapter = self._adapter_for_credentials(server, credentials)
        current_user_context = await adapter.current_user_context()
        preferred_username = self._resolve_preferred_username(current_user_context, fallback_username)
        capabilities = self._snapshot_capabilities(server)

        user = UserContext(
            preferred_username=preferred_username,
            server_id=server.id,
            server_name=server.name,
        )
        authorization_context = self._build_authorization_context(
            preferred_username,
            current_user_context,
            upstream_roles=upstream_roles,
            upstream_groups=upstream_groups,
        )
        session = self.sessions.create_session(server, user, authorization_context, credentials, capabilities)
        session = self._attach_inventory_role_names(
            session,
            self.repo.get_server_permission_inventory(server.id),
        )
        is_twc_server_administrator = self._is_twc_server_administrator(session)
        self._update_user_server_state(user.preferred_username, server.id, session.created_at)
        try:
            await self._refresh_permission_snapshot_guarded(
                session,
                reason="login",
                refresh_shared_inventory=False,
            )
        except Exception as exc:
            self.sessions.destroy_session(session.session_id)
            logger.exception(
                "twc-login-permission-snapshot-failed",
                user=user.preferred_username,
                server_id=server.id,
                detail=str(exc),
            )
            raise PermissionError(
                "Workbench could not establish a complete permission snapshot for this login. No session was created."
            ) from exc
        if is_twc_server_administrator:
            try:
                self._submit_server_permission_inventory_refresh(
                    session,
                    reason="server-administrator-login",
                )
            except Exception as exc:
                # Inventory submission is deliberately outside the login
                # critical path. The application loop retries while this
                # administrator session remains active.
                logger.exception(
                    "twc-server-permission-inventory-submit-deferred",
                    user=user.preferred_username,
                    server_id=server.id,
                    detail=str(exc),
                )
        logger.info(log_event, user=user.preferred_username, server_id=server.id)
        return session

    def _resolve_preferred_username(self, current_user_context, fallback_username: str | None = None) -> str:
        preferred_username = current_user_context.preferred_username if current_user_context else None
        if preferred_username:
            return preferred_username
        if fallback_username and fallback_username.strip():
            return fallback_username.strip()
        raise PermissionError(
            "Unable to resolve the authenticated Teamwork Cloud user from /osmc/admin/currentUser. Ensure the supplied session cookie or token is valid for TWC."
        )

    def _cached_model_list(self, session: SessionData, cache_key: str, model_class):
        cached_payload = self.repo.get_user_cache(self._user_key(session.user.preferred_username), session.server.id, cache_key)
        if not isinstance(cached_payload, list):
            return None
        try:
            return [model_class.model_validate(item) for item in cached_payload]
        except Exception:
            self.repo.delete_user_cache(self._user_key(session.user.preferred_username), session.server.id, cache_key)
            return None

    def _cached_model(self, session: SessionData, cache_key: str, model_class):
        cached_payload = self.repo.get_user_cache(self._user_key(session.user.preferred_username), session.server.id, cache_key)
        if not isinstance(cached_payload, dict):
            return None
        try:
            return model_class.model_validate(cached_payload)
        except Exception:
            self.repo.delete_user_cache(self._user_key(session.user.preferred_username), session.server.id, cache_key)
            return None

    def _branch_cache_key(self, project_id: str) -> str:
        return f"project:{project_id}:branches"

    def _is_plugin_managed_summary(self, summary: BranchCacheSummary | None) -> bool:
        return bool(summary is not None and summary.source_kind == PLUGIN_CACHE_SOURCE_KIND)

    def _fallback_cache_missing_message(self, project_id: str, branch_id: str) -> str:
        return (
            f"Project {project_id} / branch {branch_id} has no Cameo Workbench snapshot yet. "
            "Publish the branch from the Cameo Workbench plugin to populate it."
        )

    def _tree_cache_key(self, project_id: str | None, branch_id: str | None) -> str | None:
        if not project_id:
            return None
        normalized_branch = branch_id or "_default"
        return f"project:{project_id}:branch:{normalized_branch}:tree"

    def _element_discovery_cache_key(self, project_id: str, branch_id: str) -> str:
        return f"project:{project_id}:branch:{branch_id}:elements"

    def _item_cache_key(self, project_id: str | None, branch_id: str | None, item_id: str) -> str | None:
        if not project_id:
            return None
        normalized_branch = branch_id or "_default"
        return f"project:{project_id}:branch:{normalized_branch}:item:{item_id}"

    async def _workspace_id_for_project(self, session: SessionData, project_id: str) -> str | None:
        projects = await self.list_projects(session, refresh=False)
        for project in projects:
            if project.id == project_id and project.workspace_id:
                return project.workspace_id
        return None

    def _branch_access_manifest_file_path(
        self,
        server_id: str,
        project_id: str,
        branch_id: str,
    ) -> Path:
        for label, value in (("server", server_id), ("project", project_id), ("branch", branch_id)):
            if not value or value in {".", ".."} or "/" in value or "\\" in value:
                raise ValueError(f"Invalid {label} identifier for an access-manifest path.")
        return (
            self.settings.resolved_data_dir
            / "access-manifests"
            / server_id
            / project_id
            / f"{branch_id}.json"
        )

    def _write_branch_access_manifest(
        self,
        summary: BranchCacheSummary,
        records: list[BranchAccessRecord],
    ) -> None:
        manifest_path = self._branch_access_manifest_file_path(summary.server_id, summary.project_id, summary.branch_id)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "server_id": summary.server_id,
            "project_id": summary.project_id,
            "branch_id": summary.branch_id,
            "workspace_id": summary.workspace_id,
            "project_name": summary.project_name,
            "branch_name": summary.branch_name,
            "latest_revision": summary.latest_revision,
            "updated_at": max((record.updated_at for record in records), default=summary.updated_at).isoformat(),
            "source": records[0].source if records else "none",
            "records": [record.model_dump(mode="json") for record in records],
        }
        manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _branch_access_manifest_status_from_records(
        self,
        summary: BranchCacheSummary,
        records: list[BranchAccessRecord],
    ) -> BranchAccessManifestStatus:
        manifest_path = self._branch_access_manifest_file_path(summary.server_id, summary.project_id, summary.branch_id)
        updated_at = max((record.updated_at for record in records), default=None)
        source = records[0].source if records else "none"
        return BranchAccessManifestStatus(
            server_id=summary.server_id,
            project_id=summary.project_id,
            branch_id=summary.branch_id,
            workspace_id=summary.workspace_id,
            branch_name=summary.branch_name or summary.branch_id,
            latest_revision=summary.latest_revision,
            accessible_user_count=sum(1 for record in records if record.accessible),
            editable_user_count=sum(1 for record in records if record.accessible and record.editable),
            admin_user_count=sum(1 for record in records if record.admin_access),
            updated_at=updated_at,
            source=source,
            file_path=str(manifest_path) if manifest_path.exists() else None,
            message="",
        )

    async def _ensure_plugin_listing_permissions(
        self,
        session: SessionData,
        *,
        project_id: str | None = None,
        force: bool = False,
    ) -> None:
        # Listing is storage-only even when the caller refreshes project data.
        # Permission refresh belongs only to login and the scheduled lifecycle.
        return None

    async def _ensure_plugin_branch_permissions(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
        *,
        workspace_id: str | None = None,
        project_name: str = "",
        branch_name: str = "",
        summary: BranchCacheSummary | None = None,
        force: bool = False,
        prefer_manifest: bool = True,
    ) -> None:
        # Per-request authorization is storage-only, including content refresh
        # requests. Login and the scheduled lifecycle own permission refresh.
        return None

    async def refresh_user_permission_snapshot(
        self,
        session: SessionData,
        *,
        reason: str,
        refresh_shared_inventory: bool = False,
        priority_project_id: str | None = None,
        priority_branch_id: str | None = None,
    ) -> datetime:
        user_id = self._user_key(session.user.preferred_username)
        lock_key = (session.server.id, user_id)
        lock = self._permission_snapshot_locks.setdefault(lock_key, asyncio.Lock())
        async with lock:
            refreshed_at = utcnow()
            adapter = self._adapter_for_session(session)
            # Login already fetched and attached this exact current-user
            # permission response while creating the session. Do not repeat
            # the same TWC call immediately.
            current_user_context = None if reason == "login" else await adapter.current_user_context()
            if current_user_context is not None:
                session = self.sessions.update_authorization_context(
                    session,
                    self._build_authorization_context(
                        session.user.preferred_username,
                        current_user_context,
                        upstream_roles=None,
                        upstream_groups=None,
                    ),
                )
            permission_inventory = await self._server_permission_inventory(
                adapter,
                session.server.id,
                allow_refresh=refresh_shared_inventory,
            )
            session = self._attach_inventory_role_names(session, permission_inventory)
            registered_summaries = self.repo.list_branch_cache_summaries(session.server.id)
            summaries = self._permission_candidate_summaries(session, registered_summaries)
            summaries.sort(
                key=lambda summary: (
                    0
                    if summary.project_id == priority_project_id
                    and (not priority_branch_id or summary.branch_id == priority_branch_id)
                    else 1,
                    summary.project_name.lower(),
                    summary.branch_name.lower(),
                    summary.project_id,
                    summary.branch_id,
                )
            )
            # Keep the upstream pressure hard-capped even if a deployment
            # carries forward an older, higher environment setting.
            max_parallel_probes = min(2, self.settings.permission_snapshot_max_parallel_probes)
            semaphore = asyncio.Semaphore(max_parallel_probes)

            # Read-only branch overrides are project-scoped in TWC. Fetch them
            # once per candidate project and share the result across every
            # locally registered branch instead of repeating the same API call
            # for every branch. Keep this small fan-out bounded independently
            # of the branch resolver.
            readonly_project_ids = sorted({
                summary.project_id
                for summary in summaries
                if (
                    not session.authorization_context.permissions_included
                    or self._session_resource_permission_flags(
                        session,
                        summary.project_id,
                        summary.workspace_id,
                    )["editable"]
                )
            })
            readonly_by_project: dict[str, list[str]] = {}
            readonly_semaphore = asyncio.Semaphore(min(2, max_parallel_probes))

            async def load_readonly_branches(project_id: str) -> None:
                async with readonly_semaphore:
                    try:
                        readonly_by_project[project_id] = await adapter._user_readonly_branches(
                            project_id,
                            user_id,
                        )
                    except Exception as exc:
                        readonly_by_project[project_id] = []
                        logger.info(
                            "twc-current-user-readonly-branches-unavailable",
                            user=session.user.preferred_username,
                            server_id=session.server.id,
                            project_id=project_id,
                            detail=self._permission_error_text(exc),
                        )

            if readonly_project_ids:
                await asyncio.gather(*(load_readonly_branches(project_id) for project_id in readonly_project_ids))

            async def resolve(summary: BranchCacheSummary):
                async with semaphore:
                    return await self._resolve_user_branch_permission_snapshot(
                        session,
                        summary,
                        adapter=adapter,
                        permission_inventory=permission_inventory,
                        readonly_branch_ids=readonly_by_project.get(summary.project_id, []),
                        refreshed_at=refreshed_at,
                    )

            resolved = await asyncio.gather(*(resolve(summary) for summary in summaries))
            branch_records = [branch_record for branch_record, _, _ in resolved]
            model_permissions = [permission for _, permissions, _ in resolved for permission in permissions]
            permission_attachments = [attachment for _, _, attachment in resolved if attachment is not None]

            # Security boundary: delete the old user/server snapshot and insert
            # this complete result in one transaction. Revoked and removed
            # branches therefore disappear instead of surviving an upsert.
            self.repo.replace_user_permission_snapshot(
                user_id,
                session.server.id,
                branch_records,
                model_permissions,
                permission_attachments,
            )
            self.sessions.mark_permission_snapshot_attempt(session, refreshed_at, successful=True)
            self.repo.delete_user_cache(user_id, session.server.id, PROJECT_LIST_CACHE_KEY)
            self.repo.delete_user_cache_prefix(user_id, session.server.id, "project:")
            logger.info(
                "twc-user-permission-snapshot-replaced",
                user=session.user.preferred_username,
                server_id=session.server.id,
                branch_count=len(branch_records),
                model_permission_count=len(model_permissions),
                permission_attachment_count=len(permission_attachments),
                registered_branch_count=len(registered_summaries),
                permission_candidate_count=len(summaries),
                readonly_project_probe_count=len(readonly_project_ids),
                direct_branch_probe_count=(
                    0 if session.authorization_context.permissions_included else len(summaries)
                ),
                reason=reason,
                refreshed_at=refreshed_at.isoformat(),
            )
            return refreshed_at

    def _permission_snapshot_state(self, user_id: str, server_id: str) -> dict[str, Any]:
        branches = [
            record
            for record in self.repo.list_user_branch_access_records(user_id, server_id)
            if record.accessible
        ]
        models = [
            record
            for record in self.repo.list_user_model_permissions(user_id, server_id)
            if record.accessible and not record.restricted
        ]
        branch_values = {
            f"{record.project_id}/{record.branch_id}": {
                "editable": record.editable,
                "admin": record.admin_access,
            }
            for record in branches
        }
        model_values = {
            f"{record.project_id}/{record.branch_id}/{record.model_id}": {
                "editable": record.editable,
            }
            for record in models
        }
        serialized = json.dumps(
            {"branches": branch_values, "models": model_values},
            sort_keys=True,
            separators=(",", ":"),
        )
        return {
            "hash": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
            "projects": {record.project_id for record in branches},
            "branches": set(branch_values),
            "models": set(model_values),
        }

    def _permission_snapshot_delta(
        self,
        previous: dict[str, Any],
        current: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "previous_hash": previous["hash"],
            "current_hash": current["hash"],
            "granted_projects": sorted(current["projects"] - previous["projects"]),
            "revoked_projects": sorted(previous["projects"] - current["projects"]),
            "granted_branches": sorted(current["branches"] - previous["branches"]),
            "revoked_branches": sorted(previous["branches"] - current["branches"]),
            "granted_models": sorted(current["models"] - previous["models"]),
            "revoked_models": sorted(previous["models"] - current["models"]),
        }

    async def _refresh_permission_snapshot_guarded(
        self,
        session: SessionData,
        *,
        reason: str,
        refresh_shared_inventory: bool = False,
        priority_project_id: str | None = None,
        priority_branch_id: str | None = None,
    ) -> tuple[datetime, dict[str, Any]]:
        user_id = self._user_key(session.user.preferred_username)
        lease_key = f"permission-refresh:{session.server.id}:{user_id}"
        lease_owner = f"{self._permission_refresh_instance_id}:{secrets.token_hex(8)}"
        previous = self._permission_snapshot_state(user_id, session.server.id)
        acquired = self.repo.acquire_permission_refresh_lease(
            lease_key,
            lease_owner,
            ttl_seconds=self.settings.permission_refresh_lease_seconds,
        )
        if not acquired:
            if previous["branches"]:
                logger.info(
                    "twc-permission-refresh-coalesced",
                    user=session.user.preferred_username,
                    server_id=session.server.id,
                    reason=reason,
                )
                refreshed_at = session.permission_snapshot_refreshed_at or utcnow()
                return refreshed_at, {**self._permission_snapshot_delta(previous, previous), "coalesced": True}
            raise RuntimeError("Another Workbench process is establishing this user's initial permission snapshot.")

        async def renew_lease() -> None:
            interval = max(self.settings.permission_refresh_lease_seconds // 3, 20)
            while True:
                await asyncio.sleep(interval)
                if not self.repo.renew_permission_refresh_lease(
                    lease_key,
                    lease_owner,
                    ttl_seconds=self.settings.permission_refresh_lease_seconds,
                ):
                    logger.warning(
                        "twc-permission-refresh-lease-lost",
                        user=session.user.preferred_username,
                        server_id=session.server.id,
                        reason=reason,
                    )
                    return

        lease_heartbeat = asyncio.create_task(renew_lease(), name=f"twc-permission-lease-{user_id}")
        try:
            refreshed_at = await self.refresh_user_permission_snapshot(
                session,
                reason=reason,
                refresh_shared_inventory=refresh_shared_inventory,
                priority_project_id=priority_project_id,
                priority_branch_id=priority_branch_id,
            )
            current = self._permission_snapshot_state(user_id, session.server.id)
            delta = self._permission_snapshot_delta(previous, current)
            self.repo.append_permission_refresh_audit(
                PermissionRefreshAuditRecord(
                    user_id=user_id,
                    server_id=session.server.id,
                    reason=reason,
                    authoritative=True,
                    status="succeeded",
                    **delta,
                )
            )
            return refreshed_at, delta
        except Exception as exc:
            safe_error = self._permission_error_text(exc)
            self.repo.append_permission_refresh_audit(
                PermissionRefreshAuditRecord(
                    user_id=user_id,
                    server_id=session.server.id,
                    reason=reason,
                    authoritative=False,
                    status="indeterminate",
                    previous_hash=previous["hash"],
                    current_hash=previous["hash"],
                    error=safe_error,
                )
            )
            raise
        finally:
            lease_heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await lease_heartbeat
            self.repo.release_permission_refresh_lease(lease_key, lease_owner)

    async def _server_permission_inventory(
        self,
        adapter,
        server_id: str,
        *,
        allow_refresh: bool = True,
        force_refresh: bool = False,
    ) -> ServerPermissionInventory | None:
        refresh_after = timedelta(hours=self.settings.permission_inventory_refresh_hours)
        existing = self.repo.get_server_permission_inventory(server_id)
        if not allow_refresh:
            return existing
        if not force_refresh and existing and not existing.dirty and existing.captured_at + refresh_after > utcnow():
            return existing

        lock = self._permission_inventory_locks.setdefault(server_id, asyncio.Lock())
        async with lock:
            existing = self.repo.get_server_permission_inventory(server_id)
            if not force_refresh and existing and not existing.dirty and existing.captured_at + refresh_after > utcnow():
                return existing
            try:
                roles, groups = await asyncio.gather(
                    adapter._admin_roles(),
                    adapter._admin_usergroups(),
                )
            except Exception as exc:
                logger.warning(
                    "twc-server-permission-inventory-refresh-deferred",
                    server_id=server_id,
                    retained_previous_inventory=existing is not None,
                    detail=self._permission_error_text(exc),
                )
                return existing
            # A session without admin inventory rights must not erase a
            # complete inventory captured by a more privileged session.
            if not roles and existing is not None:
                return existing
            if not roles:
                return None
            inventory = ServerPermissionInventory(
                server_id=server_id,
                roles=roles,
                groups=groups,
                captured_at=utcnow(),
            )
            self.repo.upsert_server_permission_inventory(inventory)
            if sessions := getattr(self, "sessions", None):
                sessions.mark_server_permission_snapshots_due(server_id)
            logger.info(
                "twc-server-permission-inventory-refreshed",
                server_id=server_id,
                role_count=len(roles),
                group_count=len(groups),
                refresh_hours=self.settings.permission_inventory_refresh_hours,
            )
            return inventory

    def _permission_candidate_summaries(
        self,
        session: SessionData,
        summaries: list[BranchCacheSummary],
    ) -> list[BranchCacheSummary]:
        # REST-created model caches are legacy partial data. Only branches
        # published by the Cameo plugin participate in user visibility and
        # permission refresh.
        summaries = [summary for summary in summaries if self._is_plugin_managed_summary(summary)]
        # When TWC returned effective permissions, Read Resources scopes are a
        # complete, user-specific project filter. If an older TWC response did
        # not include permissions, retain the direct-probe compatibility path.
        if not session.authorization_context.permissions_included:
            return summaries
        return [
            summary
            for summary in summaries
            if self._session_resource_permission_flags(
                session,
                summary.project_id,
                summary.workspace_id,
            )["accessible"]
        ]

    def _attach_inventory_role_names(
        self,
        session: SessionData,
        inventory: ServerPermissionInventory | None,
    ) -> SessionData:
        if inventory is None or not session.authorization_context.role_ids:
            return session
        roles_by_id = {
            self._user_key(str(role.get("ID") or role.get("id") or "")): str(role.get("name") or "").strip()
            for role in inventory.roles
            if isinstance(role, dict)
        }
        resolved_names = [
            roles_by_id.get(self._user_key(role_id), "")
            for role_id in session.authorization_context.role_ids
        ]
        merged_roles = self._merge_claims(
            *session.authorization_context.roles,
            *(name for name in resolved_names if name),
        )
        if merged_roles == session.authorization_context.roles:
            return session
        return self.sessions.update_authorization_context(
            session,
            session.authorization_context.model_copy(update={"roles": merged_roles}),
        )

    async def refresh_due_permission_snapshots(self) -> None:
        now = utcnow()
        refresh_after = timedelta(minutes=self.settings.permission_snapshot_refresh_minutes)
        sessions_by_identity: dict[tuple[str, str], list[SessionData]] = {}
        for session in self.sessions.list_active_sessions():
            key = (session.server.id, self._user_key(session.user.preferred_username))
            sessions_by_identity.setdefault(key, []).append(session)

        due_groups: list[list[SessionData]] = []
        for sessions in sessions_by_identity.values():
            last_attempt = max(
                (
                    session.permission_snapshot_attempted_at
                    or session.permission_snapshot_refreshed_at
                    or session.created_at
                    for session in sessions
                ),
                default=now,
            )
            if last_attempt + refresh_after <= now:
                due_groups.append(sessions)

        semaphore = asyncio.Semaphore(3)

        async def refresh_group(group: list[SessionData]) -> None:
            async with semaphore:
                representative = max(group, key=lambda item: item.expires_at)
                live_session = representative
                attempted_at = utcnow()
                try:
                    live_session = await self._refresh_session_credentials_if_needed(representative)
                    refreshed_at, _ = await self._refresh_permission_snapshot_guarded(
                        live_session,
                        reason="scheduled-permission-refresh",
                        refresh_shared_inventory=False,
                    )
                except Exception as exc:
                    for item in group:
                        session_to_mark = live_session if item.session_id == live_session.session_id else item
                        self._mark_permission_refresh_failure(
                            session_to_mark,
                            exc,
                            reason="scheduled-permission-refresh",
                            attempted_at=attempted_at,
                        )
                    logger.warning(
                        "twc-user-permission-snapshot-refresh-deferred",
                        user=representative.user.preferred_username,
                        server_id=representative.server.id,
                        detail=str(exc),
                        retained_last_valid_snapshot=True,
                    )
                    return
                for item in group:
                    if item.session_id != representative.session_id:
                        self.sessions.mark_permission_snapshot_attempt(item, refreshed_at, successful=True)

        if due_groups:
            await asyncio.gather(*(refresh_group(group) for group in due_groups))

    def _mark_permission_refresh_failure(
        self,
        session: SessionData,
        exc: Exception,
        *,
        reason: str,
        attempted_at: datetime | None = None,
    ) -> None:
        safe_error = self._permission_error_text(exc)
        updated = self.sessions.mark_permission_snapshot_attempt(
            session,
            attempted_at or utcnow(),
            successful=False,
            error=safe_error,
        )
        failure_count = getattr(updated, "permission_snapshot_failure_count", 0)
        warning_threshold = getattr(self.settings, "permission_refresh_warning_failures", 3)
        if failure_count >= warning_threshold:
            logger.error(
                "twc-permission-refresh-administrator-warning",
                user=session.user.preferred_username,
                server_id=session.server.id,
                reason=reason,
                consecutive_failures=failure_count,
                retained_last_valid_snapshot=True,
            )

    def _permission_error_text(self, exc: Exception) -> str:
        text = str(exc).strip() or exc.__class__.__name__
        text = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[redacted]", text)
        text = re.sub(r"(?i)((?:access_)?token\s*[=:]\s*)[^\s,;]+", r"\1[redacted]", text)
        return text[:1000]

    async def _resolve_user_branch_permission_snapshot(
        self,
        session: SessionData,
        summary: BranchCacheSummary,
        *,
        adapter=None,
        permission_inventory: ServerPermissionInventory | None = None,
        readonly_branch_ids: list[str] | None = None,
        refreshed_at: datetime,
    ) -> tuple[BranchAccessRecord, list[ModelPermissionSnapshot], BranchPermissionAttachment | None]:
        user_id = self._user_key(session.user.preferred_username)
        models = self.repo.list_cached_models(session.server.id, summary.project_id, summary.branch_id)
        model_ids = [model.model_id for model in models]
        adapter = adapter or self._adapter_for_session(session)
        manifest_user_access: BranchAccessRecord | None = None
        rest_attachment: BranchPermissionAttachment | None = None
        attached_before_refresh = self.repo.get_branch_permission_attachment(
            session.server.id,
            summary.project_id,
            summary.branch_id,
        )
        manifest_error: str | None = None
        if self._attached_rest_manifest_is_current(summary, attached_before_refresh, permission_inventory):
            manifest_user_access = self._branch_access_from_attached_manifest(
                session,
                summary,
                attached_before_refresh,
            )

        probe_error: str | None = None
        permissions: list[ModelPermissionSnapshot] = []
        direct_probe_performed = not getattr(
            getattr(session, "authorization_context", None),
            "permissions_included",
            False,
        )
        if direct_probe_performed:
            try:
                permissions = await adapter.probe_plugin_branch_permissions(
                    user_id,
                    summary.project_id,
                    summary.branch_id,
                    model_ids,
                    latest_revision=summary.latest_revision,
                    workspace_id=summary.workspace_id,
                )
            except Exception as exc:
                probe_error = str(exc)
                logger.warning(
                    "twc-user-permission-probe-indeterminate",
                    user=session.user.preferred_username,
                    server_id=session.server.id,
                    project_id=summary.project_id,
                    branch_id=summary.branch_id,
                    detail=probe_error,
                )
                raise PermissionSnapshotIndeterminateError(
                    f"Teamwork Cloud did not return an authoritative permission result for "
                    f"{summary.project_id}/{summary.branch_id}; the last valid snapshot was retained."
                ) from exc

        direct_accessible = bool(permissions) and any(
            permission.accessible and not permission.restricted for permission in permissions
        )
        permission_claim_access = self._session_resource_permission_flags(
            session,
            summary.project_id,
            summary.workspace_id,
        )
        # Security authority remains fresh per-user evidence. The six-hour
        # group/role inventory is discovery and comparison data only.
        accessible = bool(
            direct_accessible
            or permission_claim_access["accessible"]
        )
        direct_editable = any(
            permission.accessible and not permission.restricted and permission.editable for permission in permissions
        )
        direct_editability_known = any(
            any(
                key in permission.payload
                for key in ("editable", "permission", "permissions", "allowedActions", "allowedOperations")
            )
            for permission in permissions
        )
        readonly_branch_ids = list(dict.fromkeys([
            *(readonly_branch_ids or []),
            *(
                (manifest_user_access.payload or {}).get("readonly_branch_ids", [])
                if manifest_user_access
                else []
            ),
        ]))
        branch_read_only = summary.branch_id in readonly_branch_ids
        editable = bool(
            accessible
            and not branch_read_only
            and (
                direct_editable
                or permission_claim_access["editable"]
            )
        )
        if not direct_probe_performed:
            permissions = [
                ModelPermissionSnapshot(
                    user_id=user_id,
                    server_id=session.server.id,
                    project_id=summary.project_id,
                    branch_id=summary.branch_id,
                    model_id=model_id,
                    accessible=accessible,
                    restricted=not accessible,
                    editable=editable,
                    source="twc-current-user-permissions",
                    updated_at=refreshed_at,
                    payload={
                        "permission_source": "current-user-effective-permissions",
                        "remote_model_probe": False,
                    },
                )
                for model_id in model_ids
            ]
        permission_comparison = self._compare_attached_and_live_permissions(
            session,
            attached_before_refresh,
            accessible=accessible,
            editable=editable,
            branch_admin=bool(accessible and not branch_read_only and permission_claim_access["branch_admin_access"]),
            access_admin=bool(accessible and permission_claim_access["access_admin_access"]),
        )
        effective_permissions = [
            permission.model_copy(
                update={
                    "accessible": accessible,
                    "restricted": not accessible,
                    "editable": editable,
                    "source": "twc-user-permission-snapshot",
                    "updated_at": refreshed_at,
                    "payload": {
                        **(permission.payload or {}),
                        "manifest_roles": manifest_user_access.roles if manifest_user_access else [],
                        "manifest_groups": manifest_user_access.via_groups if manifest_user_access else [],
                        "manifest_branch_admin_access": self._branch_admin_access(manifest_user_access),
                        "manifest_access_admin_access": self._access_admin_access(manifest_user_access),
                        "readonly_branch_ids": readonly_branch_ids,
                        "branch_read_only": branch_read_only,
                        "current_user_permission_claims": permission_claim_access["matched_permissions"],
                        "attached_permission_comparison": permission_comparison,
                    },
                }
            )
            for permission in permissions
        ]
        branch_record = BranchAccessRecord(
            user_id=user_id,
            server_id=session.server.id,
            project_id=summary.project_id,
            branch_id=summary.branch_id,
            workspace_id=summary.workspace_id,
            branch_name=summary.branch_name or summary.branch_id,
            latest_revision=summary.latest_revision,
            accessible=accessible,
            editable=editable,
            admin_access=bool(
                accessible
                and (
                    (not branch_read_only and permission_claim_access["branch_admin_access"])
                    or permission_claim_access["access_admin_access"]
                )
            ),
            roles=list(dict.fromkeys([
                *(manifest_user_access.roles if manifest_user_access else []),
                *session.authorization_context.roles,
            ])),
            via_groups=list(dict.fromkeys([
                *(manifest_user_access.via_groups if manifest_user_access else []),
                *session.authorization_context.groups,
            ])),
            source="twc-user-permission-snapshot",
            payload={
                "model_ids": model_ids,
                "direct_probe": direct_probe_performed and probe_error is None,
                "direct_accessible": direct_accessible,
                "probe_error": probe_error,
                "manifest_match": manifest_user_access is not None,
                "manifest_error": manifest_error,
                "direct_editability_known": direct_editability_known,
                "manifest_payload": manifest_user_access.payload if manifest_user_access else {},
                "branch_admin_access": bool(
                    accessible and not branch_read_only and permission_claim_access["branch_admin_access"]
                ),
                "access_admin_access": bool(accessible and permission_claim_access["access_admin_access"]),
                "readonly_branch_ids": readonly_branch_ids,
                "branch_read_only": branch_read_only,
                "current_user_permission_claims": permission_claim_access["matched_permissions"],
                "snapshot_replaced_at": refreshed_at.isoformat(),
                "attached_permission_comparison": permission_comparison,
            },
            updated_at=refreshed_at,
        )
        return branch_record, effective_permissions, rest_attachment

    def _session_resource_permission_flags(
        self,
        session: SessionData,
        project_id: str,
        workspace_id: str | None,
    ) -> dict[str, Any]:
        target_ids = {
            value.strip().lower()
            for value in (project_id, workspace_id or "")
            if value and value.strip()
        }
        matched_terms: list[str] = []
        matched_permissions: list[dict[str, Any]] = []
        for claim in getattr(session.authorization_context, "permissions", []):
            related_resources = {
                value.strip().lower()
                for value in claim.related_resources
                if value and value.strip()
            }
            if related_resources and not (related_resources & target_ids):
                continue
            terms = " ".join(
                value
                for value in (claim.name, claim.operation_name, claim.display_name)
                if value
            )
            normalized = re.sub(r"[^a-z0-9]+", " ", terms.lower()).strip()
            if not normalized:
                continue
            matched_terms.append(normalized)
            matched_permissions.append(claim.model_dump())

        def has_permission(*names: str) -> bool:
            return any(name in term for term in matched_terms for name in names)

        has_read = has_permission("read resources", "read resource")
        has_edit = has_permission("edit resources")
        has_edit_properties = has_permission("edit resource properties", "edit resource property")
        has_administer = has_permission("administer resources", "administer resource")
        has_manage_access = has_permission(
            "manage owned resource access right",
            "manage model permissions",
            "manage user permissions",
        )
        return {
            "accessible": has_read,
            "editable": bool(has_read and has_edit),
            "branch_admin_access": bool(has_read and has_edit and has_edit_properties and has_administer),
            "access_admin_access": bool(has_read and has_manage_access),
            "matched_permissions": matched_permissions,
        }

    def _permission_attachment_from_rest_manifest(
        self,
        session: SessionData,
        summary: BranchCacheSummary,
        records: list[BranchAccessRecord],
        captured_at: datetime,
        previous_attachment: BranchPermissionAttachment | None,
    ) -> BranchPermissionAttachment:
        package_entries = (
            [entry for entry in previous_attachment.manifest.entries if entry.scope_type == "package"]
            if previous_attachment
            else []
        )
        role_entries = [
            PermissionManifestEntry(
                scope_id=summary.branch_id,
                scope_type="project-branch",
                principal_name=record.user_id,
                principal_type="user",
                role_name=", ".join(record.roles),
                accessible=record.accessible,
                editable=record.editable,
                branch_admin_access=self._branch_admin_access(record),
                access_admin_access=self._access_admin_access(record),
                via_groups=record.via_groups,
                readonly_branch_ids=list((record.payload or {}).get("readonly_branch_ids", [])),
            )
            for record in records
        ]
        entries = [*package_entries, *role_entries]
        prior_warnings = list(previous_attachment.manifest.warnings) if previous_attachment else []
        source = (
            "cameo-package-permissions+twc-rest-role-manifest"
            if package_entries
            else "twc-rest-role-manifest"
        )
        return BranchPermissionAttachment(
            server_id=session.server.id,
            project_id=summary.project_id,
            branch_id=summary.branch_id,
            workspace_id=summary.workspace_id,
            latest_revision=summary.latest_revision,
            snapshot_hash=summary.snapshot_hash,
            manifest=PermissionManifest(
                captured_at=captured_at,
                captured_by=session.user.preferred_username,
                source=source,
                complete=True,
                entries=entries,
                warnings=prior_warnings,
            ),
            attached_at=captured_at,
        )

    def _attached_rest_manifest_is_current(
        self,
        summary: BranchCacheSummary,
        attachment: BranchPermissionAttachment | None,
        inventory: ServerPermissionInventory | None,
    ) -> bool:
        if attachment is None or not attachment.manifest.complete:
            return False
        if "twc-rest-role-manifest" not in attachment.manifest.source:
            return False
        if attachment.latest_revision != summary.latest_revision:
            return False
        if inventory is not None and inventory.dirty:
            return False
        freshness_floor = (
            inventory.captured_at
            if inventory is not None
            else utcnow() - timedelta(hours=self.settings.permission_inventory_refresh_hours)
        )
        return attachment.attached_at >= freshness_floor

    def _branch_access_from_attached_manifest(
        self,
        session: SessionData,
        summary: BranchCacheSummary,
        attachment: BranchPermissionAttachment,
    ) -> BranchAccessRecord | None:
        user_id = self._user_key(session.user.preferred_username)
        entry = next(
            (
                item
                for item in attachment.manifest.entries
                if self._user_key(item.principal_type) == "user"
                and self._user_key(item.principal_name or item.principal_id) == user_id
                and item.scope_type == "project-branch"
            ),
            None,
        )
        if entry is None:
            return None
        return BranchAccessRecord(
            user_id=user_id,
            server_id=session.server.id,
            project_id=summary.project_id,
            branch_id=summary.branch_id,
            workspace_id=summary.workspace_id,
            branch_name=summary.branch_name or summary.branch_id,
            latest_revision=summary.latest_revision,
            accessible=entry.accessible,
            editable=entry.editable,
            admin_access=entry.branch_admin_access or entry.access_admin_access,
            roles=[value.strip() for value in entry.role_name.split(",") if value.strip()],
            via_groups=entry.via_groups,
            source="attached-derived-project-acl",
            payload={
                "branch_admin_access": entry.branch_admin_access,
                "access_admin_access": entry.access_admin_access,
                "readonly_branch_ids": entry.readonly_branch_ids,
                "acl_attached_at": attachment.attached_at.isoformat(),
            },
            updated_at=attachment.attached_at,
        )

    def _compare_attached_and_live_permissions(
        self,
        session: SessionData,
        attachment: BranchPermissionAttachment | None,
        *,
        accessible: bool,
        editable: bool,
        branch_admin: bool,
        access_admin: bool,
    ) -> dict[str, Any]:
        live_flags = {
            "accessible": accessible,
            "editable": editable,
            "branch_admin_access": branch_admin,
            "access_admin_access": access_admin,
        }
        if attachment is None:
            return {
                "result": "no-attached-manifest",
                "manifest_complete": False,
                "matched_entry_count": 0,
                "attached": None,
                "live": live_flags,
                "enforced_source": "twc-rest-current-user",
            }

        identities = {
            self._user_key(session.user.preferred_username),
            *(self._user_key(value) for value in session.authorization_context.roles),
            *(self._user_key(value) for value in session.authorization_context.groups),
        }
        matched_entries: list[PermissionManifestEntry] = []
        for entry in attachment.manifest.entries:
            principal_type = self._user_key(entry.principal_type)
            principal_names = {
                self._user_key(entry.principal_name),
                self._user_key(entry.principal_id),
                *(self._user_key(value) for value in entry.via_groups),
            }
            if "everyone" in principal_type or "everyone" in principal_names or identities & principal_names:
                matched_entries.append(entry)

        action_terms = {self._user_key(entry.action).replace("_", "-") for entry in matched_entries}
        attached_flags = {
            "accessible": any(entry.accessible for entry in matched_entries)
            or any("read" in action for action in action_terms),
            "editable": any(entry.editable for entry in matched_entries)
            or any("write" in action for action in action_terms),
            "branch_admin_access": any(entry.branch_admin_access for entry in matched_entries),
            "access_admin_access": any(entry.access_admin_access for entry in matched_entries),
        }
        if not attachment.manifest.complete:
            result = "incomplete-attached-reference"
        elif attached_flags == live_flags:
            result = "consistent"
        elif any(attached_flags[key] and not live_flags[key] for key in live_flags):
            result = "live-more-restrictive"
        else:
            result = "live-more-permissive"
        return {
            "result": result,
            "manifest_source": attachment.manifest.source,
            "manifest_complete": attachment.manifest.complete,
            "manifest_revision": attachment.latest_revision,
            "manifest_snapshot_hash": attachment.snapshot_hash,
            "matched_entry_count": len(matched_entries),
            "attached": attached_flags,
            "live": live_flags,
            "enforced_source": "twc-rest-current-user",
        }

    def _permissions_by_model_for_user(
        self,
        user_id: str,
        server_id: str,
        project_id: str,
        branch_id: str,
    ) -> dict[str, ModelPermissionSnapshot]:
        return {
            item.model_id: item
            for item in self.repo.list_model_permissions(user_id, server_id, project_id, branch_id)
        }

    def _branch_access_for_user(
        self,
        user_id: str,
        server_id: str,
        project_id: str,
        branch_id: str,
    ) -> BranchAccessRecord | None:
        return self.repo.get_branch_access_record(user_id, server_id, project_id, branch_id)

    def _plugin_branch_access_or_source_fallback(
        self,
        user_id: str,
        server_id: str,
        project_id: str,
        branch_id: str,
        summary: BranchCacheSummary | None = None,
    ) -> BranchAccessRecord | None:
        branch_access = self._branch_access_for_user(user_id, server_id, project_id, branch_id)
        if branch_access is not None:
            return branch_access
        resolved_summary = summary or self.repo.get_branch_cache_summary(server_id, project_id, branch_id)
        if not self._is_plugin_managed_summary(resolved_summary):
            return None
        source_user = self._user_key(resolved_summary.source_user or "")
        if not source_user or source_user != user_id:
            return None
        return BranchAccessRecord(
            user_id=user_id,
            server_id=server_id,
            project_id=project_id,
            branch_id=branch_id,
            workspace_id=resolved_summary.workspace_id,
            branch_name=resolved_summary.branch_name or branch_id,
            latest_revision=resolved_summary.latest_revision,
            accessible=True,
            editable=True,
            admin_access=False,
            roles=["Snapshot Publisher"],
            source="cameo-plugin-ingest-fallback",
            payload={"source_user": resolved_summary.source_user, "fallback": True},
            updated_at=resolved_summary.updated_at,
        )

    def _branch_access_for_session(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
    ) -> BranchAccessRecord | None:
        return self._plugin_branch_access_or_source_fallback(
            self._user_key(session.user.preferred_username),
            session.server.id,
            project_id,
            branch_id,
            self.repo.get_branch_cache_summary(session.server.id, project_id, branch_id),
        )

    def _require_effective_branch_access(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
        *,
        require_edit: bool = False,
        require_branch_admin: bool = False,
        require_access_admin: bool = False,
    ) -> BranchAccessRecord:
        access = self._branch_access_for_session(session, project_id, branch_id)
        if access is None or not access.accessible:
            raise PermissionError("The active Workbench user does not have access to this project branch.")
        if require_branch_admin and not self._branch_admin_access(access):
            raise PermissionError("The active Workbench user does not have branch-administration access to this project.")
        if require_access_admin and not self._access_admin_access(access):
            raise PermissionError("The active Workbench user cannot manage access rights for this project.")
        if require_edit and not access.editable:
            raise PermissionError("The active Workbench user does not have edit access to this branch.")
        return access

    def _branch_admin_access(self, access: BranchAccessRecord | None) -> bool:
        if access is None:
            return False
        payload = access.payload or {}
        manifest_payload = payload.get("manifest_payload") if isinstance(payload.get("manifest_payload"), dict) else {}
        return bool(payload.get("branch_admin_access") or manifest_payload.get("branch_admin_access"))

    def _access_admin_access(self, access: BranchAccessRecord | None) -> bool:
        if access is None:
            return False
        payload = access.payload or {}
        manifest_payload = payload.get("manifest_payload") if isinstance(payload.get("manifest_payload"), dict) else {}
        return bool(payload.get("access_admin_access") or manifest_payload.get("access_admin_access"))

    def _plugin_branch_permissions_known_for_user(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
        *,
        summary: BranchCacheSummary | None = None,
    ) -> bool:
        # Branch/model load is where we refresh live permissions. Browsing paths
        # should trust the stored branch access we already established there.
        return (
            self._plugin_branch_access_or_source_fallback(
                self._user_key(session.user.preferred_username),
                session.server.id,
                project_id,
                branch_id,
                summary,
            )
            is not None
        )

    def _plugin_permission_snapshot_from_branch_access(
        self,
        branch_access: BranchAccessRecord,
        model: CachedModelRecord,
    ) -> ModelPermissionSnapshot:
        return ModelPermissionSnapshot(
            user_id=branch_access.user_id,
            server_id=branch_access.server_id,
            project_id=branch_access.project_id,
            branch_id=branch_access.branch_id,
            model_id=model.model_id,
            workspace_id=branch_access.workspace_id or model.workspace_id,
            latest_revision=branch_access.latest_revision or model.latest_revision,
            accessible=branch_access.accessible,
            restricted=not branch_access.accessible,
            editable=branch_access.editable,
            source=branch_access.source,
            payload={
                "roles": branch_access.roles,
                "via_groups": branch_access.via_groups,
                "branch_access": True,
                **(branch_access.payload or {}),
            },
            updated_at=branch_access.updated_at,
        )

    def _visible_cached_models_for_user(
        self,
        user_id: str,
        server_id: str,
        project_id: str,
        branch_id: str,
    ) -> list[CachedModelRecord]:
        summary = self.repo.get_branch_cache_summary(server_id, project_id, branch_id)
        if self._is_plugin_managed_summary(summary):
            branch_access = self._plugin_branch_access_or_source_fallback(
                user_id,
                server_id,
                project_id,
                branch_id,
                summary,
            )
            if branch_access is None or not branch_access.accessible:
                return []
            return self.repo.list_cached_models(server_id, project_id, branch_id)
        permissions = self._permissions_by_model_for_user(user_id, server_id, project_id, branch_id)
        return [
            model
            for model in self.repo.list_cached_models(server_id, project_id, branch_id)
            if (permission := permissions.get(model.model_id)) is not None and permission.accessible and not permission.restricted
        ]

    def _resolve_snapshot_model_records(
        self,
        server_id: str,
        payload: BranchSnapshotIngestRequest,
        source_user: str,
        ingested_at: datetime,
    ) -> list[CachedModelRecord]:
        records: list[CachedModelRecord] = []
        for model in payload.models:
            model_name = model.human_name or model.name or model.model_id
            records.append(
                CachedModelRecord(
                    server_id=server_id,
                    project_id=payload.project_id,
                    branch_id=payload.branch_id,
                    model_id=model.model_id,
                    workspace_id=payload.workspace_id,
                    latest_revision=payload.revision_id,
                    name=model_name,
                    root_ids=list(dict.fromkeys(model.root_element_ids)),
                    payload={
                        "model_id": model.model_id,
                        "name": model.name,
                        "human_name": model.human_name,
                        "qualified_name": model.qualified_name,
                        "owner_id": model.owner_id,
                        "primary": model.primary,
                        "usage_type": model.usage_type,
                        "resource_uri": model.resource_uri,
                        "root_element_ids": model.root_element_ids,
                    },
                    element_count=0,
                    source_user=payload.source_user,
                    synced_at=ingested_at,
                )
            )
        return records

    def _resolve_snapshot_element_records(
        self,
        server_id: str,
        payload: BranchSnapshotIngestRequest,
        models: list[CachedModelRecord],
        source_user: str,
        ingested_at: datetime,
    ) -> list[CachedElementRecord]:
        model_ids = {model.model_id for model in models}
        root_lookup = {
            root_id: model.model_id
            for model in models
            for root_id in model.root_ids
            if root_id
        }
        owner_lookup = {item.element_id: item.owner_id for item in payload.elements}
        resolved_by_id: dict[str, str] = {}
        records: list[CachedElementRecord] = []
        for element in payload.elements:
            resolved_model_id = self._resolve_ingest_element_model_id(
                explicit_model_id=element.model_id,
                element_id=element.element_id,
                owner_id=element.owner_id,
                model_ids=model_ids,
                root_lookup=root_lookup,
                owner_lookup=owner_lookup,
                resolved_by_id=resolved_by_id,
            )
            if resolved_model_id is None:
                raise ValueError(f"Unable to resolve model_id for element {element.element_id}")
            resolved_by_id[element.element_id] = resolved_model_id
            records.append(
                self._cached_element_record_from_ingest(
                    server_id=server_id,
                    project_id=payload.project_id,
                    branch_id=payload.branch_id,
                    workspace_id=payload.workspace_id,
                    latest_revision=payload.revision_id,
                    source_user=payload.source_user,
                    ingested_at=ingested_at,
                    resolved_model_id=resolved_model_id,
                    element=element,
                )
            )
        return records

    def _resolve_delta_model_records(
        self,
        server_id: str,
        payload: BranchDeltaIngestRequest,
        models: list,
        source_user: str,
        ingested_at: datetime,
    ) -> list[CachedModelRecord]:
        records: list[CachedModelRecord] = []
        revision_id = payload.to_revision_id or payload.from_revision_id
        for model in models:
            model_name = model.human_name or model.name or model.model_id
            records.append(
                CachedModelRecord(
                    server_id=server_id,
                    project_id=payload.project_id,
                    branch_id=payload.branch_id,
                    model_id=model.model_id,
                    workspace_id=payload.workspace_id,
                    latest_revision=revision_id,
                    name=model_name,
                    root_ids=list(dict.fromkeys(model.root_element_ids)),
                    payload={
                        "model_id": model.model_id,
                        "name": model.name,
                        "human_name": model.human_name,
                        "qualified_name": model.qualified_name,
                        "owner_id": model.owner_id,
                        "primary": model.primary,
                        "usage_type": model.usage_type,
                        "resource_uri": model.resource_uri,
                        "root_element_ids": model.root_element_ids,
                    },
                    element_count=self.repo.count_cached_elements_for_model(server_id, payload.project_id, payload.branch_id, model.model_id),
                    source_user=payload.source_user,
                    synced_at=ingested_at,
                )
            )
        return records

    def _resolve_delta_element_records(
        self,
        server_id: str,
        payload: BranchDeltaIngestRequest,
        elements: list,
        existing_models: dict[str, CachedModelRecord],
        source_user: str,
        ingested_at: datetime,
    ) -> list[CachedElementRecord]:
        model_ids = set(existing_models)
        root_lookup = {
            root_id: model.model_id
            for model in existing_models.values()
            for root_id in model.root_ids
            if root_id
        }
        owner_lookup = {item.element_id: item.owner_id for item in elements}
        resolved_by_id: dict[str, str] = {}
        records: list[CachedElementRecord] = []
        revision_id = payload.to_revision_id or payload.from_revision_id
        for element in elements:
            existing = self.repo.get_cached_element(server_id, payload.project_id, payload.branch_id, element.element_id)
            resolved_model_id = self._resolve_ingest_element_model_id(
                explicit_model_id=element.model_id or (existing.model_id if existing else None),
                element_id=element.element_id,
                owner_id=element.owner_id,
                model_ids=model_ids,
                root_lookup=root_lookup,
                owner_lookup=owner_lookup,
                resolved_by_id=resolved_by_id,
            )
            if resolved_model_id is None:
                raise ValueError(f"Unable to resolve model_id for delta element {element.element_id}")
            resolved_by_id[element.element_id] = resolved_model_id
            records.append(
                self._cached_element_record_from_ingest(
                    server_id=server_id,
                    project_id=payload.project_id,
                    branch_id=payload.branch_id,
                    workspace_id=payload.workspace_id,
                    latest_revision=revision_id,
                    source_user=payload.source_user,
                    ingested_at=ingested_at,
                    resolved_model_id=resolved_model_id,
                    element=element,
                )
            )
        return records

    def _cached_element_record_from_ingest(
        self,
        *,
        server_id: str,
        project_id: str,
        branch_id: str,
        workspace_id: str | None,
        latest_revision: str | None,
        source_user: str,
        ingested_at: datetime,
        resolved_model_id: str,
        element,
    ) -> CachedElementRecord:
        display_name = element.human_name or element.name or element.element_id
        item_type = element.human_type or element.metaclass or "element"
        path = element.qualified_name or display_name
        return CachedElementRecord(
            server_id=server_id,
            project_id=project_id,
            branch_id=branch_id,
            model_id=resolved_model_id,
            element_id=element.element_id,
            workspace_id=workspace_id,
            latest_revision=latest_revision,
            name=display_name,
            item_type=item_type,
            path=path,
            child_count=len(element.owned_element_ids),
            payload={
                "element_id": element.element_id,
                "model_id": resolved_model_id,
                "local_id": element.local_id,
                "owner_id": element.owner_id,
                "name": element.name,
                "human_name": element.human_name,
                "qualified_name": element.qualified_name,
                "human_type": element.human_type,
                "metaclass": element.metaclass,
                "documentation": element.documentation,
                "diagram_type": element.diagram_type,
                "diagram_preview_format": element.diagram_preview_format,
                "diagram_preview_base64": element.diagram_preview_base64,
                "owned_element_ids": element.owned_element_ids,
                "applied_stereotype_ids": element.applied_stereotype_ids,
                "diagram_element_ids": element.diagram_element_ids,
                "attributes": element.attributes,
                "references": element.references,
                "spec_sections": element.spec_sections,
            },
            source_user=source_user,
            synced_at=ingested_at,
        )

    def _resolve_ingest_element_model_id(
        self,
        *,
        explicit_model_id: str | None,
        element_id: str,
        owner_id: str | None,
        model_ids: set[str],
        root_lookup: dict[str, str],
        owner_lookup: dict[str, str | None],
        resolved_by_id: dict[str, str],
    ) -> str | None:
        if explicit_model_id and explicit_model_id in model_ids:
            return explicit_model_id
        if element_id in root_lookup:
            return root_lookup[element_id]

        current_owner = owner_id
        visited: set[str] = set()
        while current_owner and current_owner not in visited:
            visited.add(current_owner)
            if current_owner in model_ids:
                return current_owner
            if current_owner in root_lookup:
                return root_lookup[current_owner]
            if current_owner in resolved_by_id:
                return resolved_by_id[current_owner]
            current_owner = owner_lookup.get(current_owner)
        return None

    def _invalidate_ingested_branch_caches(
        self,
        source_user: str,
        server_id: str,
        project_id: str,
        branch_id: str,
    ) -> None:
        self.repo.delete_user_cache(
            source_user,
            server_id,
            self._element_discovery_cache_key(project_id, branch_id),
        )
        tree_key = self._tree_cache_key(project_id, branch_id)
        if tree_key:
            self.repo.delete_user_cache(source_user, server_id, tree_key)
        self.repo.delete_user_cache_prefix(source_user, server_id, f"project:{project_id}:branch:{branch_id}:item:")
        self._invalidate_shared_branch_caches(server_id, project_id, branch_id)

    def _invalidate_shared_branch_caches(
        self,
        server_id: str,
        project_id: str,
        branch_id: str,
    ) -> None:
        prefix = f"project:{project_id}:branch:{branch_id}:"
        self.repo.delete_user_cache_prefix_for_server(server_id, prefix)
        self.repo.delete_user_cache_prefix_for_server(server_id, self._branch_cache_key(project_id))

    def _workbench_agent_scope(self, server_id: str, user_id: str) -> str:
        return f"workbench-agent:{server_id}:{user_id}"

    def _normalize_openwebui_base_url(self, base_url: str) -> str:
        normalized = base_url.strip().rstrip("/")
        if normalized.endswith("/api"):
            normalized = normalized[:-4]
        return normalized.rstrip("/")

    def _workbench_agent_secret(self, session: SessionData) -> WorkbenchAgentSecret | None:
        user_id = self._user_key(session.user.preferred_username)
        stored = self.repo.get_app_secret(self._workbench_agent_scope(session.server.id, user_id))
        if not stored:
            return None
        encrypted_payload, _updated_at_raw = stored
        try:
            raw = self.sessions.cipher.decrypt_raw(encrypted_payload)
            secret = WorkbenchAgentSecret.model_validate_json(raw)
        except Exception:
            self.repo.delete_app_secret(self._workbench_agent_scope(session.server.id, user_id))
            return None
        if not secret.base_url or not secret.api_key:
            self.repo.delete_app_secret(self._workbench_agent_scope(session.server.id, user_id))
            return None
        return secret

    def _store_workbench_agent_secret(self, session: SessionData, secret: WorkbenchAgentSecret) -> None:
        user_id = self._user_key(session.user.preferred_username)
        encrypted_payload = self.sessions.cipher.encrypt_raw(secret.model_dump_json().encode("utf-8"))
        self.repo.upsert_app_secret(self._workbench_agent_scope(session.server.id, user_id), encrypted_payload)

    def _openwebui_headers(self, api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }

    def _openwebui_http_error_message(self, exc: httpx.HTTPError) -> str:
        if isinstance(exc, httpx.TimeoutException):
            return "the request timed out while waiting on Open WebUI"
        if isinstance(exc, httpx.ConnectError):
            return "Workbench could not connect to the configured Open WebUI host"
        return str(exc).strip() or exc.__class__.__name__

    def _parse_openwebui_models(self, payload: Any) -> list[OpenWebUIModelEntry]:
        if isinstance(payload, dict):
            candidates = payload.get("data") if isinstance(payload.get("data"), list) else payload.get("models")
        else:
            candidates = payload
        if not isinstance(candidates, list):
            return []
        models: list[OpenWebUIModelEntry] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            model_id = str(candidate.get("id") or candidate.get("model") or "").strip()
            if not model_id:
                continue
            models.append(
                OpenWebUIModelEntry(
                    id=model_id,
                    name=str(candidate.get("name") or candidate.get("title") or model_id).strip() or model_id,
                    owned_by=str(candidate.get("owned_by") or candidate.get("ownedBy") or "").strip() or None,
                    description=str(candidate.get("description") or "").strip(),
                )
            )
        return sorted(models, key=lambda item: (item.name.lower(), item.id.lower()))

    def _openwebui_file_id(self, payload: Any) -> str | None:
        if isinstance(payload, dict):
            for key in ("id", "file_id"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            nested = payload.get("data")
            if isinstance(nested, dict):
                return self._openwebui_file_id(nested)
        return None

    async def _upload_openwebui_markdown_file(
        self,
        secret: WorkbenchAgentSecret,
        file_name: str,
        file_content: bytes,
    ) -> str:
        upload_url = f"{secret.base_url}/api/v1/files/?process=true&process_in_background=true"
        upload_timeout = httpx.Timeout(connect=30.0, read=120.0, write=900.0, pool=60.0)
        try:
            async with httpx.AsyncClient(timeout=upload_timeout, verify=False, follow_redirects=True) as client:
                response = await client.post(
                    upload_url,
                    headers={"Authorization": f"Bearer {secret.api_key}", "Accept": "application/json"},
                    files={"file": (file_name, file_content, "text/markdown; charset=utf-8")},
                )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Open WebUI knowledge upload failed: {self._openwebui_http_error_message(exc)}") from exc
        if response.status_code >= 400:
            raise RuntimeError(f"Open WebUI knowledge upload failed: {response.text or response.reason_phrase}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Open WebUI did not return JSON for the uploaded knowledge file.") from exc
        file_id = self._openwebui_file_id(payload)
        if not file_id:
            raise RuntimeError("Open WebUI did not return a knowledge file id after upload.")
        await self._wait_for_openwebui_file_processing(secret, file_id)
        return file_id

    async def _wait_for_openwebui_file_processing(self, secret: WorkbenchAgentSecret, file_id: str) -> None:
        status_url = f"{secret.base_url}/api/v1/files/{file_id}/process/status"
        status_timeout = httpx.Timeout(connect=30.0, read=120.0, write=30.0, pool=60.0)
        deadline = datetime.now(UTC) + timedelta(minutes=15)

        async with httpx.AsyncClient(timeout=status_timeout, verify=False, follow_redirects=True) as client:
            while datetime.now(UTC) < deadline:
                try:
                    response = await client.get(status_url, headers=self._openwebui_headers(secret.api_key))
                except httpx.HTTPError as exc:
                    raise RuntimeError(
                        f"Open WebUI knowledge processing check failed: {self._openwebui_http_error_message(exc)}"
                    ) from exc
                if response.status_code >= 400:
                    raise RuntimeError(
                        f"Open WebUI knowledge processing check failed: {response.text or response.reason_phrase}"
                    )
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise RuntimeError("Open WebUI did not return JSON while checking knowledge processing status.") from exc

                status_value = str((payload or {}).get("status") or "").strip().lower()
                if status_value == "completed":
                    return
                if status_value == "failed":
                    error_text = str((payload or {}).get("error") or "").strip()
                    raise RuntimeError(
                        f"Open WebUI knowledge processing failed{': ' + error_text if error_text else '.'}"
                    )
                await asyncio.sleep(2)

        raise RuntimeError(
            "Open WebUI accepted the uploaded knowledge file, but processing did not finish within 15 minutes."
        )

    def _openwebui_assistant_message(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return json.dumps(payload, indent=2)
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        return content
                    if isinstance(content, list):
                        text_parts = []
                        for item in content:
                            if isinstance(item, dict) and isinstance(item.get("text"), str):
                                text_parts.append(item["text"])
                            elif isinstance(item, str):
                                text_parts.append(item)
                        if text_parts:
                            return "\n".join(text_parts)
                if isinstance(first.get("text"), str):
                    return str(first["text"])
        if isinstance(payload.get("response"), str):
            return str(payload["response"])
        return json.dumps(payload, indent=2)

    def _workbench_agent_system_prompt(self, session: SessionData, project_id: str, branch_id: str) -> str:
        manifest = self.cache_api_manifest(
            preferred_username=session.user.preferred_username,
            source="app-key",
            scopes=[CacheApiKeyScope.READ, CacheApiKeyScope.WRITE, CacheApiKeyScope.EDIT],
        )
        return (
            "You are the Workbench Agent inside TWC Workbench. "
            "Two processed files are attached to every request. Always retrieve from the persistent 'TWC Workbench Agent reference' file for Workbench usage, API automation, Cameo, MagicDraw, Teamwork Cloud, SysML, UML, plugin, or 3DS 2024x guidance. "
            "Use the branch model file as the primary source of truth for project-specific names, IDs, containment, native specifications, stereotypes, relationships, and diagrams. "
            "If Open WebUI native knowledge tools are available, call list_knowledge and query_knowledge_files before answering; prefer exact-file search for identifiers and semantic search for conceptual guidance. "
            "Never invent an endpoint, Java API, property, stereotype value, or model fact that the attached sources do not establish. "
            "When helping with automation, default to Python requests scripts against the Workbench API. "
            f"Current user: {session.user.preferred_username}. "
            f"Current project: {project_id}. Current branch: {branch_id}. "
            f"Available Workbench cache routes: {', '.join(manifest.available_routes)}. "
            "If the user asks for code, return complete scripts instead of snippets whenever practical."
        )

    def _workbench_agent_example_payload(self) -> dict[str, str]:
        examples_dir = Path(__file__).resolve().parents[3] / "examples"
        selected_files = [
            "22_workbench_cache_api_manifest.py",
            "23_workbench_cache_api_list_elements.py",
            "24_workbench_cache_api_edit_element.py",
            "26_workbench_cache_api_search_by_stereotype.py",
            "27_workbench_cache_api_tree.py",
            "28_workbench_cache_api_search_elements.py",
            "29_workbench_cache_api_element_graph.py",
            "30_workbench_cache_api_tree_children.py",
            "31_workbench_cache_api_native_specifications.py",
        ]
        payload: dict[str, str] = {}
        for name in selected_files:
            path = examples_dir / name
            if not path.exists():
                continue
            try:
                content = path.read_text(encoding="utf-8").strip()
            except Exception:
                continue
            if content:
                payload[name] = content
        return payload

    def _resolved_three_ds_kb_chunks_path(self) -> Path | None:
        candidates: list[Path] = []
        if self.settings.three_ds_kb_path is not None:
            candidates.append(self.settings.three_ds_kb_path.expanduser())
        repository_root = Path(__file__).resolve().parents[3]
        candidates.extend(
            [
                repository_root / "knowledge" / "3ds" / "2024x",
                Path("C:/sand/TWC_Data_Sheets/TWC2024x/output/nomagic_owui_kb"),
            ]
        )
        for candidate in candidates:
            resolved = candidate.resolve()
            chunks_path = resolved / "datasheet_chunks.jsonl" if resolved.is_dir() else resolved
            if chunks_path.is_file():
                return chunks_path
        return None

    def _three_ds_kb_status(self) -> dict[str, Any]:
        chunks_path = self._resolved_three_ds_kb_chunks_path()
        if chunks_path is None or self.settings.three_ds_kb_max_chunks <= 0:
            return {
                "three_ds_kb_available": False,
                "three_ds_kb_page_count": 0,
                "three_ds_kb_chunk_count": 0,
            }
        page_count = 0
        chunk_count = 0
        manifest_path = chunks_path.with_name("manifest.json")
        try:
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                page_count = int(manifest.get("page_count") or 0)
                chunk_count = int(manifest.get("chunk_count") or 0)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            page_count = 0
            chunk_count = 0
        if chunk_count <= 0:
            try:
                with chunks_path.open("r", encoding="utf-8") as handle:
                    chunk_count = sum(1 for line in handle if line.strip())
            except OSError:
                return {
                    "three_ds_kb_available": False,
                    "three_ds_kb_page_count": 0,
                    "three_ds_kb_chunk_count": 0,
                }
        return {
            "three_ds_kb_available": True,
            "three_ds_kb_page_count": page_count,
            "three_ds_kb_chunk_count": min(chunk_count, self.settings.three_ds_kb_max_chunks),
        }

    def _three_ds_kb_chunks(self) -> tuple[list[dict[str, Any]], dict[str, int]]:
        status = self._three_ds_kb_status()
        chunks_path = self._resolved_three_ds_kb_chunks_path()
        if not status["three_ds_kb_available"] or chunks_path is None:
            return [], {
                "three_ds_kb_page_count": 0,
                "three_ds_kb_chunk_count": 0,
            }
        chunks: list[dict[str, Any]] = []
        try:
            with chunks_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if len(chunks) >= self.settings.three_ds_kb_max_chunks:
                        break
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload, dict) and str(payload.get("content") or "").strip():
                        chunks.append(payload)
        except OSError as exc:
            raise RuntimeError(f"Configured 3DS knowledge file could not be read: {exc}") from exc
        return chunks, {
            "three_ds_kb_page_count": int(status["three_ds_kb_page_count"]),
            "three_ds_kb_chunk_count": len(chunks),
        }

    def _build_workbench_reference_document(self) -> tuple[str, bytes, dict[str, int], str]:
        chunks, stats = self._three_ds_kb_chunks()
        if not chunks:
            raise RuntimeError(
                "The 3DS 2024x knowledge base is not available. Configure THREE_DS_KB_PATH before using Workbench Agent."
            )
        lines = [
            "# TWC Workbench Agent reference",
            "",
            "This is the persistent operating reference for every model used through Workbench Agent.",
            "",
            "## Required response behavior",
            "",
            "1. For questions about Workbench operation, use the Workbench API routes and complete Python examples in this file.",
            "2. For Cameo, MagicDraw, Teamwork Cloud, SysML, UML, plugin, or 3DS 2024x questions, retrieve the relevant source-attributed 3DS section before answering.",
            "3. Treat the separately attached branch model file as authoritative for project-specific names, IDs, structure, properties, stereotypes, and relationships.",
            "4. Never invent an endpoint, Java API, metaclass property, stereotype value, or model fact. Say when the attached sources do not prove it.",
            "5. When returning automation, prefer a complete runnable Python script against the scoped Workbench API unless the user explicitly asks for Cameo Java plugin code.",
            "6. Keep 3DS product guidance separate from branch-specific model facts and include the source URL when it materially supports the answer.",
            "",
            "## Workbench knowledge surfaces",
            "",
            "- Model Browser: complete accessible Cameo containment tree in published order.",
            "- Specification workspace: native metamodel properties plus ordered applied-stereotype properties, defaults, derived values, multiplicity, type, and state metadata.",
            "- Developer API: scoped cache reads, search, graph, tree, child, and edit workflows.",
            "- Agent: this persistent reference file plus the current user's selected branch model file.",
            "",
            "## Complete Workbench Python examples",
            "",
        ]
        for name, content in self._workbench_agent_example_payload().items():
            lines.extend([f"### {name}", "", "```python", content, "```", ""])
        lines.extend(
            [
                "## Official 3DS / No Magic 2024x knowledge",
                "",
                f"This section contains {len(chunks)} source-attributed chunks from the configured 3DS KB.",
                "",
            ]
        )
        for chunk in chunks:
            title = str(chunk.get("title") or chunk.get("section_path") or chunk.get("chunk_id") or "3DS reference").strip()
            url = str(chunk.get("url") or "").strip()
            content = str(chunk.get("content") or "").strip()
            lines.extend([f"### {title}", ""])
            if url:
                lines.extend([f"Source: {url}", ""])
            lines.extend([content, ""])
        content = "\n".join(lines).encode("utf-8")
        fingerprint = hashlib.sha256(content).hexdigest()
        return "twc-workbench-3ds-2024x-reference.md", content, stats, fingerprint

    async def _ensure_workbench_reference_knowledge(
        self,
        secret: WorkbenchAgentSecret,
    ) -> tuple[str, str, dict[str, int], str]:
        file_name, content, stats, fingerprint = self._build_workbench_reference_document()
        if secret.reference_file_id and secret.reference_fingerprint == fingerprint:
            return secret.reference_file_id, secret.reference_file_name or file_name, stats, fingerprint
        file_id = await self._upload_openwebui_markdown_file(secret, file_name, content)
        return file_id, file_name, stats, fingerprint

    def _tree_markdown_lines(self, nodes: list[TreeNode]) -> list[str]:
        lines: list[str] = []

        def visit(node: TreeNode, depth: int) -> None:
            metaclass = str(node.metadata.get("metaclass") or node.node_type or "element").strip()
            lines.append(f"{'  ' * depth}- {node.label} [{metaclass}] (`{node.id}`)")
            for child in node.children:
                visit(child, depth + 1)

        for node in nodes:
            visit(node, 0)
        return lines

    def _build_workbench_agent_knowledge_document(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
    ) -> tuple[str, bytes, dict[str, int]]:
        summary = self.get_branch_cache_summary_for_user(session.server.id, session.user.preferred_username, project_id, branch_id)
        if summary is None:
            raise ValueError("The selected stored project branch is not available to this Workbench user.")
        snapshot = self.get_branch_cache_snapshot_for_user(session.server.id, session.user.preferred_username, project_id, branch_id)
        elements = self.list_cached_branch_elements_for_user(
            session.server.id,
            session.user.preferred_username,
            project_id,
            branch_id,
            all_results=True,
        ).items
        manifest = self.cache_api_manifest(
            preferred_username=session.user.preferred_username,
            source="app-key",
            scopes=[CacheApiKeyScope.READ, CacheApiKeyScope.WRITE, CacheApiKeyScope.EDIT],
        )

        project_name = summary.project_name or project_id
        branch_name = summary.branch_name or branch_id
        tree_response = self.get_cached_branch_tree_for_user(
            session.server.id,
            session.user.preferred_username,
            project_id,
            branch_id,
            include_orphans=True,
        )
        model_count = len(snapshot.models) if snapshot is not None else 0
        lines = [
            f"# TWC Workbench knowledge: {project_name} / {branch_name}",
            "",
            "This bundle is generated from the current user's accessible stored branch snapshot. It is authoritative for project-specific facts. Product, API, and Workbench operating guidance lives in the separately attached persistent Workbench + 3DS reference file.",
            "",
            "## Context",
            "",
            f"- Workbench user: `{session.user.preferred_username}`",
            f"- Server: {session.server.name} (`{session.server.id}`)",
            f"- Project: {project_name} (`{project_id}`)",
            f"- Branch: {branch_name} (`{branch_id}`)",
            f"- Revision: `{summary.latest_revision or 'unknown'}`",
            f"- Models: {model_count}",
            f"- Elements: {len(elements)}",
            f"- Containment tree nodes: {tree_response.total_nodes}",
            "",
            "## Complete accessible model tree",
            "",
            *self._tree_markdown_lines(tree_response.nodes),
            "",
            "## Model records",
            "",
        ]
        if snapshot is not None:
            for model_view in snapshot.models:
                model = model_view.model
                lines.extend(
                    [
                        f"### {model.name or model.model_id}",
                        "",
                        f"- ID: `{model.model_id}`",
                        f"- Qualified name: {str(model.payload.get('qualified_name') or model.name or '').strip()}",
                        f"- Root IDs: {', '.join(f'`{root_id}`' for root_id in model.root_ids) or 'none'}",
                        f"- Element count: {model.element_count or 0}",
                        "",
                    ]
                )
        lines.extend(["## Element specifications", ""])
        for record in elements:
            payload = record.payload or {}
            lines.extend(
                [
                    f"### {record.name or record.element_id}",
                    "",
                    f"- ID: `{record.element_id}`",
                    f"- Model ID: `{record.model_id}`",
                    f"- Type: {str(payload.get('metaclass') or record.item_type or 'Element')}",
                    f"- Qualified path: {str(payload.get('qualified_name') or record.path or '').strip()}",
                    f"- Owner ID: `{str(payload.get('owner_id') or '').strip()}`",
                    f"- Child count: {record.child_count}",
                    f"- Applied stereotypes: {', '.join(str(value) for value in payload.get('applied_stereotype_ids') or []) or 'none'}",
                    "",
                    str(payload.get("documentation") or "").strip(),
                    "",
                    "```json",
                    json.dumps(
                        {
                            "attributes": payload.get("attributes") or {},
                            "references": payload.get("references") or {},
                            "spec_sections": payload.get("spec_sections") or {},
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    "```",
                    "",
                ]
            )
        lines.extend(["## Workbench cache API", "", manifest.message, ""])
        lines.extend(f"- `{route}`" for route in manifest.available_routes)

        safe_project = "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in project_name).strip("-") or project_id
        safe_branch = "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in branch_name).strip("-") or branch_id
        file_name = f"workbench-{safe_project}-{safe_branch}-knowledge.md"
        stats = {
            "model_count": model_count,
            "element_count": len(elements),
            "tree_node_count": tree_response.total_nodes,
        }
        return file_name, "\n".join(lines).encode("utf-8"), stats

    def _shared_oslc_secret_scope(self, server_id: str) -> str:
        return f"oslc-shared:{server_id}"

    def _shared_cache_ingest_scope(self) -> str:
        return "cache-ingest-shared"

    def _shared_cache_ingest_token(self) -> tuple[str | None, datetime | None]:
        stored = self.repo.get_app_secret(self._shared_cache_ingest_scope())
        if not stored:
            return None, None
        encrypted_payload, updated_at_raw = stored
        try:
            token = self.sessions.cipher.decrypt_raw(encrypted_payload).decode("utf-8").strip()
            updated_at = datetime.fromisoformat(updated_at_raw)
        except Exception:
            self.repo.delete_app_secret(self._shared_cache_ingest_scope())
            return None, None
        if not token:
            self.repo.delete_app_secret(self._shared_cache_ingest_scope())
            return None, None
        return token, updated_at

    def _token_hint(self, token: str) -> str:
        suffix = token[-6:] if len(token) > 6 else token
        return f"Ends with {suffix}"

    def _new_cache_api_token(self) -> str:
        return f"twcwbk_cache_{secrets.token_urlsafe(36)}"

    def _hash_cache_api_token(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def cache_ingest_token_status(self) -> CacheIngestTokenStatus:
        shared_token, updated_at = self._shared_cache_ingest_token()
        if shared_token:
            return CacheIngestTokenStatus(
                configured=True,
                source="shared",
                token_hint=self._token_hint(shared_token),
                updated_at=updated_at,
                message="Configured in encrypted Workbench app storage.",
            )
        if self.settings.cache_ingest_tokens:
            return CacheIngestTokenStatus(
                configured=True,
                source="config",
                token_hint=f"{len(self.settings.cache_ingest_tokens)} legacy token(s)",
                message="Using the legacy environment-configured fallback token list.",
            )
        return CacheIngestTokenStatus(
            configured=False,
            source="none",
            message="No plugin ingest token has been configured yet.",
        )

    def rotate_cache_ingest_token(self) -> CacheIngestTokenRotateResponse:
        token = secrets.token_urlsafe(48)
        updated_at = self._store_shared_cache_ingest_token(token)
        return CacheIngestTokenRotateResponse(
            configured=True,
            source="shared",
            token_hint=self._token_hint(token),
            updated_at=updated_at,
            message="The plugin ingest token was stored in encrypted Workbench app storage.",
            token=token,
        )

    def set_cache_ingest_token(self, token: str) -> CacheIngestTokenStatus:
        candidate = token.strip()
        if not candidate:
            raise ValueError("A plugin ingest token is required.")
        updated_at = self._store_shared_cache_ingest_token(candidate)
        return CacheIngestTokenStatus(
            configured=True,
            source="shared",
            token_hint=self._token_hint(candidate),
            updated_at=updated_at,
            message="The plugin ingest token was saved in encrypted Workbench app storage.",
        )

    def clear_cache_ingest_token(self) -> CacheIngestTokenStatus:
        self.repo.delete_app_secret(self._shared_cache_ingest_scope())
        return self.cache_ingest_token_status()

    def is_valid_cache_ingest_token(self, token: str) -> bool:
        candidate = token.strip()
        if not candidate:
            return False
        if any(secrets.compare_digest(candidate, configured) for configured in self.settings.cache_ingest_tokens):
            return True
        shared_token, _ = self._shared_cache_ingest_token()
        return bool(shared_token and secrets.compare_digest(candidate, shared_token))

    def list_cache_api_keys(self, session: SessionData) -> list[CacheApiKeySummary]:
        user_id = self._user_key(session.user.preferred_username)
        return [
            CacheApiKeySummary(
                key_id=record.key_id,
                label=record.label,
                token_hint=record.token_hint,
                scopes=record.scopes,
                created_at=record.created_at,
                updated_at=record.updated_at,
                last_used_at=record.last_used_at,
            )
            for record in self.repo.list_cache_api_keys(user_id)
        ]

    def create_cache_api_key(self, session: SessionData, label: str, scopes: list[CacheApiKeyScope]) -> CacheApiKeyCreateResponse:
        clean_label = label.strip()
        if not clean_label:
            raise ValueError("API key label is required.")
        if len(clean_label) > 120:
            raise ValueError("API key label must be 120 characters or fewer.")
        normalized_scopes = list(dict.fromkeys(scopes))
        if not normalized_scopes:
            raise ValueError("At least one API key scope is required.")
        token = self._new_cache_api_token()
        now = utcnow()
        record = CacheApiKeyRecord(
            user_id=self._user_key(session.user.preferred_username),
            label=clean_label,
            token_hash=self._hash_cache_api_token(token),
            token_hint=self._token_hint(token),
            scopes=normalized_scopes,
            created_at=now,
            updated_at=now,
        )
        self.repo.upsert_cache_api_key(record)
        return CacheApiKeyCreateResponse(
            key_id=record.key_id,
            label=record.label,
            token_hint=record.token_hint,
            scopes=record.scopes,
            created_at=record.created_at,
            updated_at=record.updated_at,
            last_used_at=record.last_used_at,
            token=token,
        )

    def delete_cache_api_key(self, session: SessionData, key_id: str) -> bool:
        return self.repo.delete_cache_api_key(self._user_key(session.user.preferred_username), key_id)

    def authenticate_cache_api_token(self, token: str) -> CacheApiTokenIdentity | None:
        candidate = token.strip()
        if not candidate:
            return None
        configured_username = self.settings.cache_api_tokens.get(candidate)
        if configured_username and configured_username.strip():
            return CacheApiTokenIdentity(
                preferred_username=configured_username.strip(),
                source="config",
                scopes=[CacheApiKeyScope.READ, CacheApiKeyScope.WRITE, CacheApiKeyScope.EDIT],
            )

        record = self.repo.get_cache_api_key_by_hash(self._hash_cache_api_token(candidate))
        if not record:
            return None
        self.repo.touch_cache_api_key_last_used(record.key_id, utcnow())
        return CacheApiTokenIdentity(
            preferred_username=record.user_id,
            source="app-key",
            scopes=record.scopes,
        )

    def cache_api_manifest(self, preferred_username: str, source: str, scopes: list[CacheApiKeyScope]) -> CacheApiManifest:
        return CacheApiManifest(
            preferred_username=preferred_username,
            source="config" if source == "config" else "app-key",
            scopes=scopes,
            message="Use this bearer token against the cache API to read cached project, branch, model, and element data already available to this Workbench user. Write scope allows cache ingest, and edit scope allows cache edits on plugin-backed branches when your TWC visibility snapshot marks the model editable.",
            available_routes=[
                "GET /api/cache",
                "GET /api/cache/servers",
                "GET /api/cache/servers/{server_id}/projects",
                "GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/summary",
                "GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/snapshot",
                "GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/tree",
                "GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/nodes/{parent_id}/children",
                "GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/models",
                "GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/models/{model_id}",
                "GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements",
                "GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/search",
                "GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/by-stereotype",
                "GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/{element_id}",
                "GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/{element_id}/details",
                "GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/{element_id}/graph",
                "PATCH /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/{element_id}",
                "POST /api/cache-ingest/branch-snapshots",
                "POST /api/cache-ingest/branch-deltas",
                "POST /api/cache-ingest/branch-tombstones",
                "POST /api/cache-ingest/project-tombstones",
            ],
        )

    def _store_shared_cache_ingest_token(self, token: str) -> datetime:
        encrypted_payload = self.sessions.cipher.encrypt_raw(token.encode("utf-8"))
        return datetime.fromisoformat(
            self.repo.upsert_app_secret(self._shared_cache_ingest_scope(), encrypted_payload)
        )

    def _shared_oslc_consumer_credentials(self, server_id: str) -> tuple[OSLCConsumerCredentials | None, datetime | None]:
        stored = self.repo.get_app_secret(self._shared_oslc_secret_scope(server_id))
        if not stored:
            return None, None
        encrypted_payload, updated_at_raw = stored
        try:
            raw = self.sessions.cipher.decrypt_raw(encrypted_payload)
            credentials = OSLCConsumerCredentials.model_validate_json(raw)
            updated_at = datetime.fromisoformat(updated_at_raw)
        except Exception:
            self.repo.delete_app_secret(self._shared_oslc_secret_scope(server_id))
            return None, None
        return credentials, updated_at

    def oslc_shared_consumer_status(self, session: SessionData) -> OSLCSharedConsumerStatus:
        server = self._require_server(session.server.id, include_disabled=False)
        shared_credentials, updated_at = self._shared_oslc_consumer_credentials(server.id)
        if shared_credentials:
            return OSLCSharedConsumerStatus(
                server_id=server.id,
                configured=True,
                consumer_key=shared_credentials.consumer_key,
                updated_at=updated_at,
                source="shared",
            )
        configured_credentials = self.oauth.configured_consumer_credentials(server)
        if configured_credentials:
            return OSLCSharedConsumerStatus(
                server_id=server.id,
                configured=True,
                consumer_key=configured_credentials.consumer_key,
                source="config",
            )
        return OSLCSharedConsumerStatus(server_id=server.id, configured=False, source="none")

    def set_shared_oslc_consumer(self, session: SessionData, *, consumer_key: str, consumer_secret: str) -> OSLCSharedConsumerStatus:
        consumer_key = consumer_key.strip()
        consumer_secret = consumer_secret.strip()
        if not consumer_key or not consumer_secret:
            raise ValueError("OSLC consumer key and secret are required.")
        encrypted_payload = self.sessions.cipher.encrypt_raw(
            OSLCConsumerCredentials(
                consumer_key=consumer_key,
                consumer_secret=consumer_secret,
                source="shared",
            ).model_dump_json().encode("utf-8")
        )
        updated_at = self.repo.upsert_app_secret(self._shared_oslc_secret_scope(session.server.id), encrypted_payload)
        return OSLCSharedConsumerStatus(
            server_id=session.server.id,
            configured=True,
            consumer_key=consumer_key,
            updated_at=datetime.fromisoformat(updated_at),
            source="shared",
        )

    def clear_shared_oslc_consumer(self, session: SessionData) -> None:
        self.repo.delete_app_secret(self._shared_oslc_secret_scope(session.server.id))
        self.sessions.clear_oslc_credentials(session)

    def _build_authorization_context(
        self,
        preferred_username: str,
        current_user_context,
        *,
        upstream_roles: list[str] | None,
        upstream_groups: list[str] | None,
    ) -> AuthorizationContext:
        roles = self._merge_claims(*(upstream_roles or []), *((current_user_context.roles) if current_user_context else []))
        groups = self._merge_claims(*(upstream_groups or []), *((current_user_context.groups) if current_user_context else []))
        permissions = list((current_user_context.permissions) if current_user_context else [])
        permissions_included = bool(current_user_context and current_user_context.permissions_included)
        role_ids = list((current_user_context.role_ids) if current_user_context else [])
        can_manage = self._claims_grant_admin(preferred_username, roles, groups)

        if roles or groups or permissions:
            return AuthorizationContext(
                roles=roles,
                role_ids=role_ids,
                groups=groups,
                permissions=permissions,
                permissions_included=permissions_included,
                source="upstream-authorization-claims",
                can_manage_server_presets=can_manage,
            )

        return AuthorizationContext(
            roles=[],
            role_ids=role_ids,
            groups=[],
            permissions=permissions,
            permissions_included=permissions_included,
            source="authenticated-user-default",
            can_manage_server_presets=can_manage,
        )

    def _claims_grant_admin(self, preferred_username: str, roles: list[str], groups: list[str]) -> bool:
        if self._user_key(preferred_username) in {self._user_key(value) for value in self.settings.admin_users if value.strip()}:
            return True
        normalized_roles = {
            re.sub(r"[^a-z0-9]+", " ", role.lower()).strip()
            for role in roles
            if role.strip()
        }
        return bool(normalized_roles & SERVER_ADMIN_ROLE_NAMES)

    def _is_twc_server_administrator(self, session: SessionData) -> bool:
        normalized_roles = {
            re.sub(r"[^a-z0-9]+", " ", role.lower()).strip()
            for role in session.authorization_context.roles
            if role.strip()
        }
        if TWC_SERVER_ADMIN_ROLE_NAME in normalized_roles:
            return True
        for claim in session.authorization_context.permissions:
            terms = " ".join(
                value
                for value in (claim.name, claim.operation_name, claim.display_name)
                if value
            )
            normalized = re.sub(r"[^a-z0-9]+", " ", terms.lower()).strip()
            if "configure server" in normalized:
                return True
        return False

    def _merge_claims(self, *values: str) -> list[str]:
        merged: list[str] = []
        for value in values:
            candidate = value.strip()
            if candidate and candidate not in merged:
                merged.append(candidate)
        return merged

    def _has_remote_access(self, capabilities) -> bool:
        return bool(capabilities.reachable_endpoints.get("projects"))

    def _user_key(self, preferred_username: str) -> str:
        return preferred_username.strip().lower()

    def _update_user_server_state(self, preferred_username: str, server_id: str, updated_at) -> UserServerState:
        user_id = self._user_key(preferred_username)
        current = self.repo.get_user_server_state(user_id) or UserServerState(user_id=user_id)
        current.selected_server_id = server_id
        current.last_used_server_id = server_id
        current.favorite_server_ids = [favorite_id for favorite_id in current.favorite_server_ids if self.repo.get_server(favorite_id)]
        current.updated_at = updated_at
        return self.repo.upsert_user_server_state(current)

    def _require_server(self, server_id: str, *, include_disabled: bool = True) -> ServerProfile:
        server = self.get_server(server_id, include_disabled=include_disabled)
        if not server:
            raise KeyError(server_id)
        return server


class ApplicationContainer:
    def __init__(self, settings: Settings) -> None:
        from app.auth.oauth import OAuthService

        self.settings = settings
        self.repo = SqliteRepository(settings.resolved_database_path)
        self.repo.sync_servers(settings.twc_preset_servers)
        self.sessions = SessionManager(settings)
        self.oauth = OAuthService(settings)
        self.jobs = JobCoordinator(self.repo)
        self.publisher = build_publisher(settings)
        self.platform = PlatformService(
            settings=settings,
            oauth=self.oauth,
            repo=self.repo,
            sessions=self.sessions,
            jobs=self.jobs,
            publisher=self.publisher,
        )
        self._permission_refresh_task: asyncio.Task[None] | None = None
        self._permission_refresh_wakeup = asyncio.Event()
        self._permission_refresh_loop_handle: asyncio.AbstractEventLoop | None = None
        self._last_job_cleanup_at: datetime | None = None

    async def start(self) -> None:
        if self._permission_refresh_task is None:
            self._permission_refresh_loop_handle = asyncio.get_running_loop()
            self.platform._permission_inventory_dirty_notifier = self.notify_permission_inventory_dirty
            # REST model/element crawling is no longer part of Workbench.
            # Cancel persisted work before any worker can resume it.
            for job in self.repo.list_jobs():
                if (
                    job.job_type in {JobType.FALLBACK_CACHE_REFRESH, JobType.MODEL_CACHE}
                    and job.status in {JobStatus.PENDING, JobStatus.RUNNING}
                ):
                    job.cancel_requested = True
                    job.status = JobStatus.CANCELLED
                    job.message = "Cancelled: TWC REST model and element synchronization is disabled."
                    job.updated_at = utcnow()
                    job.finished_at = job.updated_at
                    self.repo.upsert_job(job)
            # Do not interfere with jobs owned by another live backend worker.
            # Only jobs stale beyond two lease windows are treated as abandoned.
            recovered = self.jobs.recover_interrupted_jobs(
                stale_before=utcnow() - timedelta(seconds=self.settings.permission_refresh_lease_seconds * 2)
            )
            for job in recovered:
                if job.job_type == JobType.PERMISSION_INVENTORY_REFRESH:
                    self.repo.mark_server_permission_inventory_dirty(job.server_id)
            self._cleanup_old_jobs()
            self._permission_refresh_task = asyncio.create_task(
                self._permission_refresh_loop(),
                name="twc-permission-snapshot-refresh",
            )

    def notify_permission_inventory_dirty(self) -> None:
        loop = self._permission_refresh_loop_handle
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._permission_refresh_wakeup.set)

    def _cleanup_old_jobs(self) -> None:
        now = utcnow()
        if self._last_job_cleanup_at and self._last_job_cleanup_at + timedelta(hours=24) > now:
            return
        deleted = self.repo.delete_completed_jobs_before(now - timedelta(days=self.settings.job_retention_days))
        self._last_job_cleanup_at = now
        if deleted:
            logger.info("twc-job-retention-cleanup", deleted_count=deleted, retention_days=self.settings.job_retention_days)

    async def _permission_refresh_loop(self) -> None:
        while True:
            try:
                await self.platform.refresh_due_server_permission_inventories()
                await self.platform.refresh_due_permission_snapshots()
                self._cleanup_old_jobs()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("twc-permission-refresh-loop-failed", detail=str(exc))
            try:
                await asyncio.wait_for(self._permission_refresh_wakeup.wait(), timeout=60)
                self._permission_refresh_wakeup.clear()
            except TimeoutError:
                pass

    async def close(self) -> None:
        if self._permission_refresh_task is None:
            return
        self._permission_refresh_task.cancel()
        with suppress(asyncio.CancelledError):
            await self._permission_refresh_task
        self._permission_refresh_task = None
        self.platform._permission_inventory_dirty_notifier = None
        self._permission_refresh_loop_handle = None
