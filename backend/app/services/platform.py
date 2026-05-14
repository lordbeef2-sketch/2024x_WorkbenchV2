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
from typing import Any

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
    CacheElementEditRequest,
    CacheApiManifest,
    CacheApiTokenIdentity,
    CacheIngestTokenRotateResponse,
    CacheIngestTokenStatus,
    CacheServerEntry,
    CacheProjectBranchEntry,
    CacheProjectEntry,
    CapabilityState,
    CachedElementQueryResponse,
    CachedElementRecord,
    CachedModelRecord,
    CachedModelView,
    CommentEntry,
    CompareDifference,
    CompareResult,
    DashboardPayload,
    ElementDiscoveryEntry,
    ElementDiscoveryResult,
    ExportRequest,
    ItemDetails,
    JobRecord,
    JobStatus,
    JobType,
    MaterializedCacheStatus,
    ModelPermissionSnapshot,
    OSLCAuthorizationStatus,
    OSLCConsumerCredentials,
    OSLCExecuteRequest,
    OSLCExecuteResponse,
    OSLCGenerateConsumerResponse,
    OSLCSharedConsumerStatus,
    ProjectSummary,
    PublishRequest,
    SavedSearch,
    SearchResponse,
    ServerHealth,
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
    WebhookRegistrationStatus,
    utcnow,
)
from app.security.session import SessionManager
from app.services.swagger_contract import SwaggerContract
from app.settings.config import Settings

logger = structlog.get_logger(__name__)


ADMIN_CLAIM_MARKERS = ("admin", "administrator")
PROJECT_LIST_CACHE_KEY = "projects"
BRANCH_REVISION_PROBE_TTL_SECONDS = 20
FAILED_BRANCH_CACHE_RETRY_SECONDS = 300
PLUGIN_PERMISSION_PROBE_TTL_SECONDS = 60
PLUGIN_CACHE_SOURCE_KIND = "cameo-plugin"


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

    async def refresh_capabilities(self, session: SessionData):
        adapter = self._adapter_for_session(session)
        capabilities = await adapter.discover_capabilities()
        return self.sessions.update_capabilities(session, capabilities).capabilities

    def update_preferences(self, session: SessionData, preferences: SessionPreferences) -> SessionPreferences:
        return self.sessions.update_preferences(session, preferences).preferences

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
        projects = self._project_summaries_from_cache_for_user(session)
        self.repo.delete_user_cache(
            self._user_key(session.user.preferred_username),
            session.server.id,
            PROJECT_LIST_CACHE_KEY,
        )
        logger.info("twc-project-list-ui", user=session.user.preferred_username, server_id=session.server.id, delivered_count=len(projects))
        return projects

    async def list_project_branches(self, session: SessionData, project_id: str, workspace_id: str | None = None, refresh: bool = False):
        cache_key = self._branch_cache_key(project_id)
        if not refresh:
            cached_branches = self._cached_model_list(session, cache_key, BranchSummary)
            if cached_branches is not None:
                return cached_branches

        branches = self._branch_summaries_from_cache_for_user(session, project_id)
        self.repo.upsert_user_cache(
            self._user_key(session.user.preferred_username),
            session.server.id,
            cache_key,
            [json.loads(branch.model_dump_json()) for branch in branches],
        )
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
        return [
            ProjectSummary(
                id=project.project_id,
                name=project.project_name,
                description="Plugin-backed Workbench project cache",
                favorite=False,
                branches=[
                    BranchSummary(
                        id=branch.branch_id,
                        name=branch.branch_name,
                        description=f"Cached branch ({branch.status.value})",
                    )
                    for branch in sorted(project.branches, key=lambda item: ((item.branch_name or item.branch_id).lower(), item.branch_id))
                ],
                workspace_id=project.workspace_id,
                resource_id=project.project_id,
            )
            for project in cached_projects
        ]

    def _branch_summaries_from_cache_for_user(self, session: SessionData, project_id: str) -> list[BranchSummary]:
        cached_projects = self.list_cached_projects_for_user(session.server.id, session.user.preferred_username)
        for project in cached_projects:
            if project.project_id != project_id:
                continue
            return [
                BranchSummary(
                    id=branch.branch_id,
                    name=branch.branch_name,
                    description=f"Cached branch ({branch.status.value})",
                )
                for branch in sorted(project.branches, key=lambda item: ((item.branch_name or item.branch_id).lower(), item.branch_id))
            ]
        return []

    async def get_model_tree(
        self,
        session: SessionData,
        project_id: str | None,
        branch_id: str | None,
        workspace_id: str | None = None,
        refresh: bool = False,
    ):
        cache_key = self._tree_cache_key(project_id, branch_id)
        use_branch_materialized_cache = bool(project_id and branch_id)
        if cache_key and not refresh and not use_branch_materialized_cache:
            cached_tree = self._cached_model_list(session, cache_key, TreeNode)
            if cached_tree is not None:
                return cached_tree

        if project_id and branch_id:
            summary = self.repo.get_branch_cache_summary(session.server.id, project_id, branch_id)
            if self._is_plugin_managed_summary(summary):
                await self._ensure_plugin_branch_permissions(
                    session,
                    project_id,
                    branch_id,
                    workspace_id=workspace_id,
                    summary=summary,
                    force=refresh,
                )
                materialized_tree = self._materialized_model_tree(session, project_id, branch_id)
                return materialized_tree or []
            if self._is_plugin_only_target(session.server.id, project_id, branch_id):
                raise RuntimeError(self._plugin_only_cache_message(project_id, branch_id))
            await self._schedule_branch_cache_refresh_if_stale(
                session,
                project_id,
                branch_id,
                workspace_id=workspace_id,
                refresh=refresh,
            )
            materialized_tree = self._materialized_model_tree(session, project_id, branch_id)
            if materialized_tree is not None:
                return materialized_tree

        tree = await self._adapter_for_session(session).get_model_tree(project_id, branch_id)
        if cache_key and not use_branch_materialized_cache:
            self.repo.upsert_user_cache(
                self._user_key(session.user.preferred_username),
                session.server.id,
                cache_key,
                [json.loads(node.model_dump_json()) for node in tree],
            )
        return tree

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
        if self._is_plugin_managed_summary(summary):
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
                    "This branch is served from the Cameo plugin cache.",
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

        if self._is_plugin_only_target(session.server.id, project_id, branch_id):
            raise RuntimeError(self._plugin_only_cache_message(project_id, branch_id))

        materialized = self._materialized_element_discovery(session, project_id, branch_id, summary)

        sync_job = await self._schedule_branch_cache_refresh_if_stale(
            session,
            project_id,
            branch_id,
            workspace_id=resolved_workspace_id,
            refresh=refresh,
            summary=summary,
        )

        if materialized is not None and sync_job is None:
            self.repo.upsert_user_cache(
                self._user_key(session.user.preferred_username),
                session.server.id,
                cache_key,
                json.loads(materialized.model_dump_json()),
            )
            return materialized

        if materialized is not None:
            sync_note = (
                "Syncs run one at a time per server."
                if MODEL_CACHE_SYNC_MIN_REQUEST_INTERVAL_SECONDS <= 0
                else f"Syncs run one at a time per server and keep at least {MODEL_CACHE_SYNC_MIN_REQUEST_INTERVAL_SECONDS:g}s between upstream requests."
            )
            refreshed = materialized.model_copy(
                update={
                    "warnings": [
                        *materialized.warnings,
                        (
                            f"Background model cache sync started as job {sync_job.id}; cached results remain available while the branch refreshes. "
                            f"{sync_note}"
                        ),
                    ][-50:],
                    "cache_status": "cache-hit",
                }
            )
            self.repo.upsert_user_cache(
                self._user_key(session.user.preferred_username),
                session.server.id,
                cache_key,
                json.loads(refreshed.model_dump_json()),
            )
            return refreshed

        result = ElementDiscoveryResult(
            project_id=project_id,
            branch_id=branch_id,
            workspace_id=resolved_workspace_id,
            latest_revision=summary.latest_revision if summary is not None else None,
            seed_source="materialized-model-cache",
            seed_ids=[],
            ids=[],
            entries=[],
            total_ids=0,
            traversed_elements=0,
            hydrated_elements=0,
            batch_count=0,
            batch_size=0,
            cache_status="full-refresh",
            warnings=[
                (
                    f"Branch cache warm-up started as job {sync_job.id}. Track it with the jobs API and retry when the sync completes. "
                    + (
                        "Syncs run one at a time per server."
                        if MODEL_CACHE_SYNC_MIN_REQUEST_INTERVAL_SECONDS <= 0
                        else f"Syncs run one at a time per server and keep at least {MODEL_CACHE_SYNC_MIN_REQUEST_INTERVAL_SECONDS:g}s between upstream requests."
                    )
                ),
                "Element discovery now serves from the local materialized cache instead of walking Teamwork Cloud live.",
            ],
        )
        self.repo.upsert_user_cache(
            self._user_key(session.user.preferred_username),
            session.server.id,
            cache_key,
            json.loads(result.model_dump_json()),
        )
        return result

    async def submit_branch_cache_sync(self, session: SessionData, request: BranchCacheSyncRequest) -> JobRecord:
        resolved_workspace_id = request.workspace_id or await self._workspace_id_for_project(session, request.project_id)
        active_job = self._active_branch_cache_job(session, request.project_id, request.branch_id)
        if active_job is not None:
            return active_job

        existing_summary = self.repo.get_branch_cache_summary(session.server.id, request.project_id, request.branch_id)
        job = self.jobs.create_job(
            job_type=JobType.MODEL_CACHE,
            title=f"Model cache: {request.project_id}/{request.branch_id}",
            owner=session.user.preferred_username,
            server_id=session.server.id,
            payload={
                "project_id": request.project_id,
                "branch_id": request.branch_id,
                "workspace_id": resolved_workspace_id,
                "force_full_refresh": request.force_full_refresh,
            },
        )
        self.repo.upsert_branch_cache_summary(
            self._branch_cache_summary(
                session,
                request.project_id,
                request.branch_id,
                workspace_id=resolved_workspace_id,
                latest_revision=existing_summary.latest_revision if existing_summary else None,
                status=MaterializedCacheStatus.SYNCING,
                message="Queued materialized branch cache sync for the actively viewed project branch. Model cache jobs are serialized per server.",
                model_count=existing_summary.model_count if existing_summary else 0,
                element_count=existing_summary.element_count if existing_summary else 0,
                last_job_id=job.id,
            )
        )
        adapter = self._adapter_for_session(session)

        async def handler(context):
            server_lock = self._model_cache_server_lock(session.server.id)
            if server_lock.locked():
                await context.report(
                    1,
                    "Waiting for another model cache sync on this server to finish before starting.",
                )
            async with server_lock:
                start_message = (
                    "Starting model cache sync."
                    if MODEL_CACHE_SYNC_MIN_REQUEST_INTERVAL_SECONDS <= 0
                    else f"Starting paced model cache sync with a minimum {MODEL_CACHE_SYNC_MIN_REQUEST_INTERVAL_SECONDS:g}s gap between upstream requests."
                )
                await context.report(
                    max(2, self.jobs.get_job(job.id).progress if self.jobs.get_job(job.id) else 2),
                    start_message,
                )
                return await self._run_branch_cache_sync(
                    session,
                    adapter,
                    request.project_id,
                    request.branch_id,
                    resolved_workspace_id,
                    context.report,
                    context.cancel_requested,
                    job.id,
                )

        return self.jobs.submit(job, handler)

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
        permissions = {
            item.model_id: item
            for item in self.repo.list_model_permissions(
                self._user_key(session.user.preferred_username),
                session.server.id,
                project_id,
                branch_id,
            )
        }
        models = [
            CachedModelView(model=model, permissions=permissions.get(model.model_id))
            for model in self.repo.list_cached_models(session.server.id, project_id, branch_id)
            if (permission := permissions.get(model.model_id)) is not None and permission.accessible and not permission.restricted
        ]
        return BranchCacheSnapshot(summary=summary, models=models)

    def get_cached_branch_model(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
        model_id: str,
    ) -> CachedModelView | None:
        model = self.repo.get_cached_model(session.server.id, project_id, branch_id, model_id)
        if model is None:
            return None
        permission = self.repo.get_model_permission(
            self._user_key(session.user.preferred_username),
            session.server.id,
            project_id,
            branch_id,
            model_id,
        )
        if permission is None or not permission.accessible or permission.restricted:
            return None
        return CachedModelView(model=model, permissions=permission)

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
    ) -> CachedElementQueryResponse:
        permissions = {
            item.model_id: item
            for item in self.repo.list_model_permissions(
                self._user_key(session.user.preferred_username),
                session.server.id,
                project_id,
                branch_id,
            )
        }
        visible_models = [
            model
            for model in self.repo.list_cached_models(session.server.id, project_id, branch_id)
            if (permission := permissions.get(model.model_id)) is not None and permission.accessible and not permission.restricted
        ]
        visible_model_ids = {
            permission.model_id for permission in permissions.values() if permission.accessible and not permission.restricted
        }
        if model_id is not None and model_id not in visible_model_ids:
            return CachedElementQueryResponse(total=0, items=[])

        raw = self.repo.list_cached_elements(
            session.server.id,
            project_id,
            branch_id,
            model_id=model_id,
            search=search,
            limit=limit if model_id is not None else max(limit + offset, sum(model.element_count for model in visible_models), 1),
            offset=offset if model_id is not None else 0,
        )
        if model_id is not None:
            return raw

        filtered_items = [item for item in raw.items if item.model_id in visible_model_ids]
        return CachedElementQueryResponse(
            total=len(filtered_items),
            items=filtered_items[offset : offset + limit],
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
        permissions = {
            item.model_id: item
            for item in self.repo.list_model_permissions(
                self._user_key(session.user.preferred_username),
                session.server.id,
                project_id,
                branch_id,
            )
        }
        visible_model_ids = [
            permission.model_id for permission in permissions.values() if permission.accessible and not permission.restricted
        ]
        if model_id is not None:
            if model_id not in visible_model_ids:
                return None
            return self.repo.get_cached_element(
                session.server.id,
                project_id,
                branch_id,
                element_id,
                model_id=model_id,
            )
        for visible_model_id in visible_model_ids:
            match = self.repo.get_cached_element(
                session.server.id,
                project_id,
                branch_id,
                element_id,
                model_id=visible_model_id,
            )
            if match is not None:
                return match
        return None

    def ingest_branch_snapshot(self, payload: BranchSnapshotIngestRequest) -> BranchCacheSummary:
        server = self._require_server(payload.server_id, include_disabled=True)
        source_user = self._user_key(payload.source_user)
        ingested_at = utcnow()

        resolved_models = self._resolve_snapshot_model_records(server.id, payload, source_user, ingested_at)
        resolved_elements = self._resolve_snapshot_element_records(server.id, payload, resolved_models, source_user, ingested_at)
        element_counts_by_model: dict[str, int] = {}
        for record in resolved_elements:
            element_counts_by_model[record.model_id] = element_counts_by_model.get(record.model_id, 0) + 1

        finalized_models = [
            model.model_copy(update={"element_count": element_counts_by_model.get(model.model_id, 0)})
            for model in resolved_models
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

        self.repo.delete_branch_models_except(
            server.id,
            payload.project_id,
            payload.branch_id,
            [model.model_id for model in finalized_models],
        )
        self.repo.upsert_cached_models(finalized_models)
        self.repo.replace_model_permissions_for_user_branch(
            source_user,
            server.id,
            payload.project_id,
            payload.branch_id,
            permissions,
        )
        for model in finalized_models:
            model_elements = [item for item in resolved_elements if item.model_id == model.model_id]
            self.repo.replace_cached_elements(server.id, payload.project_id, payload.branch_id, model.model_id, model_elements)

        summary = BranchCacheSummary(
            server_id=server.id,
            project_id=payload.project_id,
            branch_id=payload.branch_id,
            workspace_id=payload.workspace_id,
            project_name=payload.project_name or payload.project_id,
            branch_name=payload.branch_name or payload.branch_id,
            latest_revision=payload.revision_id,
            status=MaterializedCacheStatus.READY,
            message="Materialized from Cameo plugin snapshot.",
            model_count=len(finalized_models),
            element_count=len(resolved_elements),
            source_kind=payload.source,
            source_user=payload.source_user,
            updated_at=ingested_at,
        )
        self.repo.upsert_branch_cache_summary(summary)
        self._invalidate_ingested_branch_caches(source_user, server.id, payload.project_id, payload.branch_id)
        return summary

    def ingest_branch_delta(self, payload: BranchDeltaIngestRequest) -> BranchCacheSummary:
        server = self._require_server(payload.server_id, include_disabled=True)
        existing_summary = self.repo.get_branch_cache_summary(server.id, payload.project_id, payload.branch_id)
        if existing_summary is None:
            raise ValueError("A branch snapshot must be ingested before deltas can be applied.")

        source_user = self._user_key(payload.source_user)
        ingested_at = utcnow()

        added_models = self._resolve_delta_model_records(server.id, payload, payload.added_models, source_user, ingested_at)
        updated_models = self._resolve_delta_model_records(server.id, payload, payload.updated_models, source_user, ingested_at)
        if payload.removed_model_ids:
            self.repo.delete_cached_models_by_ids(server.id, payload.project_id, payload.branch_id, payload.removed_model_ids)

        if added_models or updated_models:
            self.repo.upsert_cached_models([*added_models, *updated_models])

        existing_models = {model.model_id: model for model in self.repo.list_cached_models(server.id, payload.project_id, payload.branch_id)}
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
            self.repo.delete_cached_elements_by_ids(server.id, payload.project_id, payload.branch_id, payload.removed_element_ids)
        self.repo.upsert_cached_elements([*resolved_added_elements, *resolved_updated_elements])

        current_models = self.repo.list_cached_models(server.id, payload.project_id, payload.branch_id)
        refreshed_models: list[CachedModelRecord] = []
        for model in current_models:
            refreshed_models.append(
                model.model_copy(
                    update={
                        "latest_revision": payload.to_revision_id or existing_summary.latest_revision,
                        "element_count": self.repo.count_cached_elements_for_model(server.id, payload.project_id, payload.branch_id, model.model_id),
                        "synced_at": ingested_at,
                        "source_user": payload.source_user,
                    }
                )
            )
        if refreshed_models:
            self.repo.upsert_cached_models(refreshed_models)

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
        )

        summary = BranchCacheSummary(
            server_id=server.id,
            project_id=payload.project_id,
            branch_id=payload.branch_id,
            workspace_id=payload.workspace_id or existing_summary.workspace_id,
            project_name=payload.project_name or existing_summary.project_name or payload.project_id,
            branch_name=payload.branch_name or existing_summary.branch_name or payload.branch_id,
            latest_revision=payload.to_revision_id or existing_summary.latest_revision,
            status=MaterializedCacheStatus.READY,
            message="Applied Cameo plugin delta.",
            model_count=len(refreshed_models),
            element_count=self.repo.count_cached_elements_for_branch(server.id, payload.project_id, payload.branch_id),
            last_job_id=existing_summary.last_job_id,
            source_kind=payload.source,
            source_user=payload.source_user,
            updated_at=ingested_at,
        )
        self.repo.upsert_branch_cache_summary(summary)
        self._invalidate_ingested_branch_caches(source_user, server.id, payload.project_id, payload.branch_id)
        return summary

    def list_cached_projects_for_user(self, server_id: str, preferred_username: str) -> list[CacheProjectEntry]:
        self._require_server(server_id, include_disabled=True)
        user_id = self._user_key(preferred_username)
        projects: dict[str, CacheProjectEntry] = {}
        for summary in self.repo.list_branch_cache_summaries(server_id):
            visible_models = self._visible_cached_models_for_user(user_id, server_id, summary.project_id, summary.branch_id)
            if not visible_models:
                continue
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
                    model_count=len(visible_models),
                    element_count=sum(model.element_count for model in visible_models),
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

    def get_branch_cache_summary_for_user(
        self,
        server_id: str,
        preferred_username: str,
        project_id: str,
        branch_id: str,
    ) -> BranchCacheSummary | None:
        self._require_server(server_id, include_disabled=True)
        visible_models = self._visible_cached_models_for_user(self._user_key(preferred_username), server_id, project_id, branch_id)
        if not visible_models:
            return None
        summary = self.repo.get_branch_cache_summary(server_id, project_id, branch_id)
        if summary is None:
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
    ) -> CachedElementQueryResponse:
        self._require_server(server_id, include_disabled=True)
        user_id = self._user_key(preferred_username)
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

        permission = self.repo.get_model_permission(
            self._user_key(preferred_username),
            server_id,
            project_id,
            branch_id,
            record.model_id,
        )
        if permission is None or not permission.accessible or permission.restricted or not permission.editable:
            raise PermissionError("The active Workbench user does not have edit access to this cached model.")

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
    ) -> dict[str, Any]:
        summary = self.repo.get_branch_cache_summary(session.server.id, project_id, branch_id)
        synced_model_ids: list[str] = []
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
                failure_summary = self._branch_cache_summary(
                    session,
                    project_id,
                    branch_id,
                    workspace_id=workspace_id,
                    latest_revision=latest_revision,
                    status=MaterializedCacheStatus.FAILED,
                    message=warnings[-1],
                    last_job_id=job_id,
                )
                self.repo.upsert_branch_cache_summary(failure_summary)
                raise RuntimeError(warnings[-1])

            total_models = max(1, len(models))
            for index, (model_id, model_payload) in enumerate(models, start=1):
                if cancel_requested():
                    cancelled_summary = self._branch_cache_summary(
                        session,
                        project_id,
                        branch_id,
                        workspace_id=workspace_id,
                        latest_revision=latest_revision,
                        status=MaterializedCacheStatus.FAILED,
                        message="Materialized branch cache sync was cancelled before completion.",
                        model_count=len(synced_model_ids),
                        element_count=total_elements,
                        last_job_id=job_id,
                    )
                    self.repo.upsert_branch_cache_summary(cancelled_summary)
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
                total_elements += len(element_records)
                warnings.extend(model_warnings[-10:])
                self.repo.upsert_cached_models([model_record])
                self.repo.upsert_model_permissions([permission])
                self.repo.replace_cached_elements(
                    session.server.id,
                    project_id,
                    branch_id,
                    model_id,
                    element_records,
                )
                self.repo.upsert_branch_cache_summary(
                    self._branch_cache_summary(
                        session,
                        project_id,
                        branch_id,
                        workspace_id=workspace_id,
                        latest_revision=latest_revision,
                        status=MaterializedCacheStatus.SYNCING,
                        message=f"Synced model {index}/{len(models)}: {model_record.name or model_id}",
                        model_count=len(synced_model_ids),
                        element_count=total_elements,
                        last_job_id=job_id,
                    )
                )

            self.repo.delete_branch_models_except(session.server.id, project_id, branch_id, synced_model_ids)
            final_message = f"Materialized {len(synced_model_ids)} models and {total_elements} elements into the local branch cache."
            if warnings:
                final_message = f"{final_message} Last warning: {warnings[-1]}"
            self.repo.upsert_branch_cache_summary(
                self._branch_cache_summary(
                    session,
                    project_id,
                    branch_id,
                    workspace_id=workspace_id,
                    latest_revision=latest_revision,
                    status=MaterializedCacheStatus.READY,
                    message=final_message,
                    model_count=len(synced_model_ids),
                    element_count=total_elements,
                    last_job_id=job_id,
                )
            )
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
        except Exception as exc:
            self.repo.upsert_branch_cache_summary(
                self._branch_cache_summary(
                    session,
                    project_id,
                    branch_id,
                    workspace_id=workspace_id,
                    latest_revision=latest_revision,
                    status=MaterializedCacheStatus.FAILED,
                    message=str(exc),
                    model_count=len(synced_model_ids),
                    element_count=total_elements,
                    last_job_id=job_id,
                )
            )
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
        if cached_record is None:
            return None

        permission = self.repo.get_model_permission(
            self._user_key(session.user.preferred_username),
            session.server.id,
            project_id,
            branch_id,
            cached_record.model_id,
        )
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
            editable=bool(permission.editable) if permission else False,
            version=cached_record.latest_revision or cached_record.synced_at.isoformat(),
        )

    def _accessible_cached_models(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
    ) -> list[CachedModelRecord]:
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

    def _materialized_model_tree(self, session: SessionData, project_id: str, branch_id: str) -> list[TreeNode] | None:
        models = self._accessible_cached_models(session, project_id, branch_id)
        if not models:
            return None

        nodes: list[TreeNode] = []
        for model in models:
            model_name = model.name or model.model_id
            model_path = f"{project_id}/{branch_id}/{model_name}"
            children: list[TreeNode] = []
            for root_id in model.root_ids:
                root_record = self.get_cached_branch_element(session, project_id, branch_id, root_id, model_id=model.model_id)
                root_name = root_record.name if root_record is not None else root_id
                root_type = root_record.item_type if root_record is not None else "model_root"
                children.append(
                    TreeNode(
                        id=root_id,
                        label=root_name,
                        node_type=root_type,
                        path=f"{model_path}/{root_name}",
                        children=[],
                        metadata={
                            "project_id": project_id,
                            "branch_id": branch_id,
                            "model_id": model.model_id,
                        },
                    )
                )
            nodes.append(
                TreeNode(
                    id=model.model_id,
                    label=model_name,
                    node_type="model",
                    path=model_path,
                    children=children,
                    metadata={
                        "project_id": project_id,
                        "branch_id": branch_id,
                        "model_id": model.model_id,
                    },
                )
            )
        return nodes

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
            model for model in models if (permission := permissions.get(model.model_id)) is not None and permission.accessible and not permission.restricted
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
            if self._is_plugin_managed_summary(summary):
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
            if self._is_plugin_only_target(session.server.id, project_id, branch_id):
                raise RuntimeError(self._plugin_only_cache_message(project_id, branch_id))
            await self._schedule_branch_cache_refresh_if_stale(
                session,
                project_id,
                branch_id,
                workspace_id=workspace_id,
                refresh=refresh,
            )
            materialized_item = await self._materialized_item_details(session, item_id, project_id, branch_id)
            if materialized_item is not None:
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

        item = await self._adapter_for_session(session).get_item(item_id, project_id, branch_id)
        if cache_key and not use_branch_materialized_cache:
            self.repo.upsert_user_cache(
                self._user_key(session.user.preferred_username),
                session.server.id,
                cache_key,
                json.loads(item.model_dump_json()),
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

    async def update_item(
        self,
        session: SessionData,
        item_id: str,
        payload: dict[str, Any],
        project_id: str | None = None,
        branch_id: str | None = None,
    ) -> ItemDetails:
        item = await self._adapter_for_session(session).update_item(item_id, payload, project_id, branch_id)
        cache_key = self._item_cache_key(project_id, branch_id, item_id)
        if cache_key:
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
        )

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
        capabilities = await adapter.discover_capabilities()
        if not self._has_remote_access(capabilities):
            raise PermissionError(
                "The authenticated Teamwork Cloud user did not expose any repository endpoints. Ensure the TWC session or token belongs to a user with repository access."
            )

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
        self._update_user_server_state(user.preferred_username, server.id, session.created_at)
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

    def _is_plugin_only_target(self, server_id: str, project_id: str, branch_id: str) -> bool:
        rule = self.settings.plugin_only_cache_rule_for_server(server_id)
        if rule is None:
            return False
        if project_id in set(rule.project_ids):
            return True
        branch_ids = rule.branch_ids.get(project_id) or []
        return branch_id in set(branch_ids)

    def _plugin_only_cache_message(self, project_id: str, branch_id: str) -> str:
        return (
            f"Project {project_id} / branch {branch_id} is configured for plugin-only cache access. "
            "Publish a Cameo plugin snapshot to Workbench before opening this branch here."
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

    async def _ensure_plugin_branch_permissions(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
        *,
        workspace_id: str | None = None,
        summary: BranchCacheSummary | None = None,
        force: bool = False,
    ) -> None:
        resolved_summary = summary or self.repo.get_branch_cache_summary(session.server.id, project_id, branch_id)
        if not self._is_plugin_managed_summary(resolved_summary):
            return

        models = self.repo.list_cached_models(session.server.id, project_id, branch_id)
        if not models:
            return

        user_id = self._user_key(session.user.preferred_username)
        existing_permissions = {
            item.model_id: item
            for item in self.repo.list_model_permissions(
                user_id,
                session.server.id,
                project_id,
                branch_id,
            )
        }
        expected_revision = resolved_summary.latest_revision
        refresh_cutoff = utcnow() - timedelta(seconds=PLUGIN_PERMISSION_PROBE_TTL_SECONDS)
        model_ids = [model.model_id for model in models]
        needs_refresh = force
        if not needs_refresh:
            for model_id in model_ids:
                permission = existing_permissions.get(model_id)
                if permission is None:
                    needs_refresh = True
                    break
                if permission.source != "twc-session-probe":
                    needs_refresh = True
                    break
                if (permission.latest_revision or None) != (expected_revision or None):
                    needs_refresh = True
                    break
                if permission.updated_at <= refresh_cutoff:
                    needs_refresh = True
                    break

        if not needs_refresh:
            return

        try:
            permissions = await self._adapter_for_session(session).probe_model_permissions(
                user_id,
                project_id,
                branch_id,
                model_ids,
                latest_revision=expected_revision,
                workspace_id=workspace_id or resolved_summary.workspace_id,
            )
        except Exception as exc:
            logger.warning(
                "plugin-cache-permission-refresh-failed",
                server_id=session.server.id,
                project_id=project_id,
                branch_id=branch_id,
                user=session.user.preferred_username,
                detail=str(exc),
            )
            return

        self.repo.replace_model_permissions_for_user_branch(
            user_id,
            session.server.id,
            project_id,
            branch_id,
            permissions,
        )

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

    def _visible_cached_models_for_user(
        self,
        user_id: str,
        server_id: str,
        project_id: str,
        branch_id: str,
    ) -> list[CachedModelRecord]:
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
                "owned_element_ids": element.owned_element_ids,
                "applied_stereotype_ids": element.applied_stereotype_ids,
                "attributes": element.attributes,
                "references": element.references,
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
                "GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/models",
                "GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/models/{model_id}",
                "GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements",
                "GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/{element_id}",
                "PATCH /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/elements/{element_id}",
                "POST /api/cache-ingest/branch-snapshots",
                "POST /api/cache-ingest/branch-deltas",
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
        can_manage = self._claims_grant_admin(preferred_username, roles, groups)

        if roles or groups:
            return AuthorizationContext(
                roles=roles,
                groups=groups,
                source="upstream-authorization-claims",
                can_manage_server_presets=can_manage,
            )

        return AuthorizationContext(
            roles=[],
            groups=[],
            source="authenticated-user-default",
            can_manage_server_presets=can_manage,
        )

    def _claims_grant_admin(self, preferred_username: str, roles: list[str], groups: list[str]) -> bool:
        if self._user_key(preferred_username) in {self._user_key(value) for value in self.settings.admin_users if value.strip()}:
            return True
        claims = [*(role.lower() for role in roles), *(group.lower() for group in groups)]
        return any(marker in claim for claim in claims for marker in ADMIN_CLAIM_MARKERS)

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

    async def close(self) -> None:
        return None
