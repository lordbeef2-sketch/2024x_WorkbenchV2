# Created by: Raymond Reeves Engineering Tech 4 2026
from __future__ import annotations

import asyncio
import base64
import os
import csv
import hashlib
import html
import hmac
import json
import secrets
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any, Callable
from urllib.parse import urlencode, urlparse
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
    CacheIngestTokenRevealResponse,
    CacheIngestTokenStatus,
    CacheServerEntry,
    CacheProjectBranchEntry,
    CacheProjectEntry,
    Capability,
    CapabilitySummary,
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
    ServerPermissionInventoryDetails,
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
    SwaggerOperationSpec,
    SwaggerParameterSpec,
    SwaggerResponseSpec,
    TokenBundle,
    TokenLoginRequest,
    TreeNode,
    TWCVersion,
    UserServerState,
    UserContext,
    WorkbenchAuthAdminStatus,
    WorkbenchAuthSettings,
    WorkbenchAuthSettingsUpdate,
    WorkbenchAgentAdminSettings,
    WorkbenchAgentChatRequest,
    WorkbenchAgentChatResponse,
    WorkbenchAgentConfigRequest,
    WorkbenchAgentKnowledgeStatus,
    WorkbenchAgentSecret,
    WorkbenchAgentStatus,
    WorkbenchFirstAdminSetupRequest,
    WorkbenchGroupCreateRequest,
    WorkbenchGroupRecord,
    WorkbenchGroupSummary,
    WorkbenchGroupUpdateRequest,
    WorkbenchLocalLoginRequest,
    WorkbenchProjectAccessAssignmentRequest,
    WorkbenchProjectAccessAssignmentResponse,
    WorkbenchUserCreateRequest,
    WorkbenchUserRecord,
    WorkbenchUserRole,
    WorkbenchUserSummary,
    WorkbenchUserUpdateRequest,
    WebhookRegistrationStatus,
    CacheTreeResponse,
    StereotypeElementSearchResponse,
    utcnow,
)
from app.security.session import SessionManager
from app.services.swagger_contract import SwaggerContract
from app.services.three_ds_corpus import ThreeDsCorpus
from app.settings.config import Settings

logger = structlog.get_logger(__name__)
WORKBENCH_API_VARIABLE_CATALOG_OPERATION_KEY = "workbench_get_api_variable_catalog"
WORKBENCH_OWNED_ELEMENTS_OPERATION_KEY = "workbench_get_model_cache_owned_elements"
WORKBENCH_PROJECT_DUMP_OPERATION_KEY = "workbench_get_model_cache_project_dump"
WORKBENCH_SPEC_DIAGNOSTIC_OPERATION_KEY = "workbench_get_model_cache_spec_diagnostic"


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _truthy_query_value(value: Any, *, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
DEFAULT_THREE_DS_KB_ROOT = Path("C:/Users/Main1/Documents/NI KB base/3DS_KB").resolve()
BUNDLED_THREE_DS_KB_ROOT = Path(__file__).resolve().parents[3] / "3DS_KB"


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
        repo: SqliteRepository,
        sessions: SessionManager,
        jobs: JobCoordinator,
        publisher: PublisherAdapter,
    ) -> None:
        self.settings = settings
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
        self._three_ds_corpus: ThreeDsCorpus | None = None
        self._three_ds_corpus_root: Path | None = None
        self._three_ds_corpus_lock = threading.RLock()
        contract_path = Path(__file__).resolve().parents[3] / "contracts" / "RealSwagger.json"
        if not contract_path.exists():
            contract_path = Path.cwd() / "contracts" / "RealSwagger.json"
        self.contract = SwaggerContract(contract_path)

    def _server_profile_for_response(self, server: ServerProfile) -> ServerProfile:
        return server.model_copy(update={"auth_client_secret": None, "oslc_consumer_secret": None})

    def list_servers(self) -> list[ServerProfile]:
        return [self._server_profile_for_response(server) for server in self.repo.list_servers()]

    def list_servers_for_management(self) -> list[ServerProfile]:
        return [self._server_profile_for_response(server) for server in self.repo.list_servers(include_disabled=True)]

    def create_server(self, payload: ServerProfileCreate) -> ServerProfile:
        server = ServerProfile(**payload.model_dump(exclude_none=True))
        if self.repo.get_server(server.id):
            raise ValueError(f"Server profile already exists: {server.id}")
        if "display_order" not in payload.model_fields_set:
            server.display_order = self.repo.next_server_display_order()
        return self._server_profile_for_response(self.repo.upsert_server(server))

    def update_server(self, server_id: str, payload: ServerProfileUpdate) -> ServerProfile:
        current = self._require_server(server_id)
        updated = current.model_copy(update={key: value for key, value in payload.model_dump(exclude_none=True).items()})
        updated.updated_at = utcnow()
        return self._server_profile_for_response(self.repo.upsert_server(updated))

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

        return [self._server_profile_for_response(server) for server in self.repo.bulk_upsert_servers(ordered_servers)]

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

    def _has_workbench_admin_model_visibility(self, session: SessionData) -> bool:
        # Workbench admins need to see every cached/imported model so they can
        # assign Workbench-side access. This is catalog visibility only; edit
        # rights still come from the user's actual branch/model permissions.
        authorization_context = getattr(session, "authorization_context", None)
        return bool(getattr(authorization_context, "can_manage_server_presets", False))

    def can_manage_groups(self, session: SessionData) -> bool:
        return session.authorization_context.can_manage_server_presets or session.authorization_context.can_manage_groups

    def auth_admin_status(self, session: SessionData | None = None) -> WorkbenchAuthAdminStatus:
        users = self.repo.list_workbench_users()
        settings = self.get_auth_settings()
        return WorkbenchAuthAdminStatus(
            settings=settings,
            local_user_count=len(users),
            first_admin_setup_required=settings.user_management_mode == "local" and len(users) == 0,
            can_manage_users=bool(session and self.can_manage_groups(session)),
        )

    def get_auth_settings(self) -> WorkbenchAuthSettings:
        stored = self.repo.get_auth_settings()
        if not self.repo.has_auth_settings():
            stored = stored.model_copy(update={"user_management_mode": self.settings.workbench_user_management_mode})
        return self._normalize_auth_settings(stored)

    def _normalize_auth_settings(self, settings: WorkbenchAuthSettings) -> WorkbenchAuthSettings:
        if settings.user_management_mode == "local":
            return settings.model_copy(
                update={
                    "local_users_enabled": True,
                    "twc_redirect_enabled": False,
                    "twc_token_enabled": False,
                }
            )
        twc_redirect_enabled = settings.twc_redirect_enabled
        twc_token_enabled = settings.twc_token_enabled
        if not twc_redirect_enabled and not twc_token_enabled:
            twc_redirect_enabled = True
            twc_token_enabled = True
        return settings.model_copy(
            update={
                "local_users_enabled": False,
                "twc_redirect_enabled": twc_redirect_enabled,
                "twc_token_enabled": twc_token_enabled,
            }
        )

    def update_auth_settings(self, payload: WorkbenchAuthSettingsUpdate) -> WorkbenchAuthSettings:
        current = self.get_auth_settings()
        candidate = current.model_copy(update=payload.model_dump(exclude_none=True))
        if candidate.user_management_mode == "twc" and not (candidate.twc_redirect_enabled or candidate.twc_token_enabled):
            raise ValueError("At least one TWC sign-in method must remain enabled in TWC user management mode.")
        updated = self._normalize_auth_settings(candidate)
        return self.repo.set_auth_settings(updated)

    def _normalize_workbench_username(self, username: str) -> str:
        value = username.strip().lower()
        if not re.match(r"^[a-z0-9_.@-]{2,128}$", value):
            raise ValueError("Workbench usernames must be 2-128 characters and may contain letters, numbers, dot, underscore, dash, or @.")
        return value

    def _hash_workbench_password(self, password: str, *, allow_weak: bool = False) -> str:
        if not allow_weak and len(password) < 12:
            raise ValueError("Workbench passwords must be at least 12 characters.")
        salt = secrets.token_bytes(16)
        rounds = 390_000
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
        return f"pbkdf2_sha256${rounds}${base64.b64encode(salt).decode('ascii')}${base64.b64encode(digest).decode('ascii')}"

    def _verify_workbench_password(self, password: str, encoded_hash: str) -> bool:
        try:
            algorithm, rounds_raw, salt_raw, digest_raw = encoded_hash.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            salt = base64.b64decode(salt_raw.encode("ascii"))
            expected = base64.b64decode(digest_raw.encode("ascii"))
            digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(rounds_raw))
            return hmac.compare_digest(digest, expected)
        except Exception:
            return False

    def list_workbench_users(self, session: SessionData) -> list[WorkbenchUserSummary]:
        server_id = session.server.id
        summaries: list[WorkbenchUserSummary] = []
        for user in self.repo.list_workbench_users():
            branch_records = [
                record
                for record in self.repo.list_user_branch_access_records(user.username, server_id)
                if record.accessible
            ]
            summaries.append(
                WorkbenchUserSummary(
                    username=user.username,
                    role=user.role,
                    enabled=user.enabled,
                    display_name=user.display_name,
                    created_at=user.created_at,
                    updated_at=user.updated_at,
                    last_login_at=user.last_login_at,
                    accessible_project_count=len({record.project_id for record in branch_records}),
                    accessible_branch_count=len(branch_records),
                    password_change_required=user.password_change_required,
                )
            )
        return summaries

    def create_workbench_user(self, payload: WorkbenchUserCreateRequest) -> WorkbenchUserSummary:
        username = self._normalize_workbench_username(payload.username)
        if self.repo.get_workbench_user(username):
            raise ValueError("Workbench user already exists.")
        user = WorkbenchUserRecord(
            username=username,
            password_hash=self._hash_workbench_password(payload.password),
            role=payload.role,
            enabled=payload.enabled,
            display_name=payload.display_name,
            password_change_required=False,
        )
        stored = self.repo.upsert_workbench_user(user)
        return WorkbenchUserSummary(
            username=stored.username,
            role=stored.role,
            enabled=stored.enabled,
            display_name=stored.display_name,
            created_at=stored.created_at,
            updated_at=stored.updated_at,
            last_login_at=stored.last_login_at,
            password_change_required=stored.password_change_required,
        )

    def update_workbench_user(self, username: str, payload: WorkbenchUserUpdateRequest) -> WorkbenchUserSummary:
        normalized = self._normalize_workbench_username(username)
        user = self.repo.get_workbench_user(normalized)
        if not user:
            raise KeyError(normalized)
        updates: dict[str, Any] = {}
        if payload.password is not None:
            updates["password_hash"] = self._hash_workbench_password(payload.password)
            updates["password_change_required"] = False
        if payload.role is not None:
            updates["role"] = payload.role
        if payload.enabled is not None:
            updates["enabled"] = payload.enabled
        if payload.display_name is not None:
            updates["display_name"] = payload.display_name
        if user.enabled and user.role == WorkbenchUserRole.ADMIN and (
            updates.get("enabled") is False or updates.get("role") in {WorkbenchUserRole.USER, WorkbenchUserRole.GROUP_MANAGER}
        ):
            other_enabled_admins = [
                candidate
                for candidate in self.repo.list_workbench_users()
                if candidate.username != normalized and candidate.enabled and candidate.role == WorkbenchUserRole.ADMIN
            ]
            if not other_enabled_admins:
                raise ValueError("At least one enabled Workbench admin must remain.")
        stored = self.repo.upsert_workbench_user(user.model_copy(update=updates))
        return WorkbenchUserSummary(
            username=stored.username,
            role=stored.role,
            enabled=stored.enabled,
            display_name=stored.display_name,
            created_at=stored.created_at,
            updated_at=stored.updated_at,
            last_login_at=stored.last_login_at,
            password_change_required=stored.password_change_required,
        )

    def delete_workbench_user(self, username: str) -> bool:
        normalized = self._normalize_workbench_username(username)
        user = self.repo.get_workbench_user(normalized)
        if user and user.enabled and user.role == WorkbenchUserRole.ADMIN:
            other_enabled_admins = [
                candidate
                for candidate in self.repo.list_workbench_users()
                if candidate.username != normalized and candidate.enabled and candidate.role == WorkbenchUserRole.ADMIN
            ]
            if not other_enabled_admins:
                raise ValueError("At least one enabled Workbench admin must remain.")
        return self.repo.delete_workbench_user(normalized)

    def list_workbench_groups(self, session: SessionData) -> list[WorkbenchGroupSummary]:
        groups = self.repo.list_workbench_groups()
        if not session.authorization_context.can_manage_server_presets:
            username = self._normalize_workbench_username(session.user.preferred_username)
            groups = [group for group in groups if username in {self._normalize_workbench_username(user) for user in group.users}]
        return [self._workbench_group_summary(group) for group in groups]

    def create_workbench_group(self, payload: WorkbenchGroupCreateRequest) -> WorkbenchGroupSummary:
        name = self._normalize_workbench_group_name(payload.name)
        if not name:
            raise ValueError("Group name is required.")
        if self.repo.get_workbench_group(name):
            raise ValueError("Workbench group already exists.")
        users = self._normalize_workbench_group_users(payload.users)
        self._validate_workbench_group_users(users)
        group = WorkbenchGroupRecord(
            name=name,
            description=payload.description,
            users=users,
            enabled=payload.enabled,
        )
        return self._workbench_group_summary(self.repo.upsert_workbench_group(group))

    def update_workbench_group(self, session: SessionData, name: str, payload: WorkbenchGroupUpdateRequest) -> WorkbenchGroupSummary:
        normalized = self._normalize_workbench_group_name(name)
        group = self.repo.get_workbench_group(normalized)
        if not group:
            raise KeyError(normalized)
        self._require_workbench_group_write(session, group)
        updates: dict[str, Any] = {}
        if payload.description is not None:
            updates["description"] = payload.description
        if payload.enabled is not None:
            updates["enabled"] = payload.enabled
        if payload.users is not None:
            users = self._normalize_workbench_group_users(payload.users)
            self._validate_workbench_group_users(users)
            updates["users"] = users
        return self._workbench_group_summary(self.repo.upsert_workbench_group(group.model_copy(update=updates)))

    def delete_workbench_group(self, session: SessionData, name: str) -> bool:
        if not session.authorization_context.can_manage_server_presets:
            raise PermissionError("Only Workbench administrators can delete groups.")
        return self.repo.delete_workbench_group(self._normalize_workbench_group_name(name))

    def assign_workbench_project_access(
        self,
        session: SessionData,
        payload: WorkbenchProjectAccessAssignmentRequest,
    ) -> WorkbenchProjectAccessAssignmentResponse:
        project_id = payload.project_id.strip()
        if not project_id:
            raise ValueError("Project is required.")
        principal_name = payload.principal_name.strip()
        if not principal_name:
            raise ValueError("User or group is required.")
        actor_username = self._normalize_workbench_username(session.user.preferred_username)
        actor_key = self._user_key(actor_username)

        if payload.principal_type == "user":
            username = self._normalize_workbench_username(principal_name)
            user = self.repo.get_workbench_user(username)
            if user is None:
                raise ValueError(f"Workbench user not found: {username}")
            usernames = [username]
            normalized_principal = username
        else:
            group_name = self._normalize_workbench_group_name(principal_name)
            group = self.repo.get_workbench_group(group_name)
            if group is None:
                raise ValueError(f"Workbench group not found: {group_name}")
            if not group.enabled:
                raise ValueError(f"Workbench group is disabled: {group_name}")
            usernames = [user for user in group.users if self.repo.get_workbench_user(user)]
            if not usernames:
                raise ValueError(f"Workbench group has no valid users: {group_name}")
            normalized_principal = group_name
        if actor_key in {self._user_key(username) for username in usernames}:
            raise PermissionError("Project access administrators cannot assign or elevate their own project access.")

        summaries = [
            summary
            for summary in self.repo.list_branch_cache_summaries(session.server.id)
            if summary.project_id == project_id and self._is_plugin_managed_summary(summary)
        ]
        if payload.branch_id:
            branch_id = payload.branch_id.strip()
            summaries = [summary for summary in summaries if summary.branch_id == branch_id]
        if not summaries:
            raise ValueError("No plugin-imported Workbench branch matches this project/branch selection.")
        if not session.authorization_context.can_manage_server_presets:
            unauthorized_summaries = [
                summary
                for summary in summaries
                if not self._access_admin_access(
                    self._plugin_branch_access_or_source_fallback(
                        actor_key,
                        session.server.id,
                        summary.project_id,
                        summary.branch_id,
                        summary,
                    )
                )
            ]
            if unauthorized_summaries:
                if payload.branch_id:
                    raise PermissionError("The active Workbench user cannot manage access rights for this project branch.")
                raise PermissionError("The active Workbench user cannot manage access rights for every selected project branch.")

        now = utcnow()
        records: list[BranchAccessRecord] = []
        via_groups = [normalized_principal] if payload.principal_type == "group" else []
        for username in usernames:
            for summary in summaries:
                records.append(
                    BranchAccessRecord(
                        user_id=self._user_key(username),
                        server_id=session.server.id,
                        project_id=summary.project_id,
                        branch_id=summary.branch_id,
                        workspace_id=summary.workspace_id,
                        branch_name=summary.branch_name or summary.branch_id,
                        latest_revision=summary.latest_revision,
                        accessible=payload.accessible,
                        editable=bool(payload.accessible and payload.editable),
                        admin_access=bool(payload.accessible and payload.admin_access),
                        roles=["Workbench Project Access Assignment"],
                        via_groups=via_groups,
                        source="workbench-admin-assignment",
                        payload={
                            "assigned_by": session.user.preferred_username,
                            "principal_type": payload.principal_type,
                            "principal_name": normalized_principal,
                            "workbench_assignment": True,
                            "project_access_assignment": True,
                            "branch_admin_access": bool(payload.accessible and payload.admin_access),
                            "access_admin_access": bool(payload.accessible and payload.admin_access),
                        },
                        updated_at=now,
                    )
                )
        self.repo.upsert_branch_access_records(records)
        return WorkbenchProjectAccessAssignmentResponse(
            principal_type=payload.principal_type,
            principal_name=normalized_principal,
            project_id=project_id,
            branch_ids=sorted({record.branch_id for record in records}),
            assigned_usernames=sorted({record.user_id for record in records}),
            accessible=payload.accessible,
            editable=bool(payload.accessible and payload.editable),
            admin_access=bool(payload.accessible and payload.admin_access),
            message=f"Updated Workbench project access for {len(usernames)} user(s) across {len(summaries)} branch(es).",
        )

    def _require_workbench_group_write(self, session: SessionData, group: WorkbenchGroupRecord) -> None:
        if session.authorization_context.can_manage_server_presets:
            return
        username = self._normalize_workbench_username(session.user.preferred_username)
        if username not in {self._normalize_workbench_username(user) for user in group.users}:
            raise PermissionError("Group managers can only manage groups they are already assigned to.")

    def _workbench_group_summary(self, group: WorkbenchGroupRecord) -> WorkbenchGroupSummary:
        return WorkbenchGroupSummary(
            name=group.name,
            description=group.description,
            users=group.users,
            enabled=group.enabled,
            created_at=group.created_at,
            updated_at=group.updated_at,
        )

    def _normalize_workbench_group_name(self, value: str) -> str:
        return re.sub(r"\s+", " ", value.strip()).lower()

    def _normalize_workbench_group_users(self, users: list[str]) -> list[str]:
        return sorted({self._normalize_workbench_username(user) for user in users if user.strip()})

    def _validate_workbench_group_users(self, users: list[str]) -> None:
        missing = [user for user in users if not self.repo.get_workbench_user(user)]
        if missing:
            raise ValueError(f"Workbench group references unknown user(s): {', '.join(missing)}")

    def setup_first_workbench_admin(self, payload: WorkbenchFirstAdminSetupRequest) -> SessionData:
        if self.repo.list_workbench_users():
            raise PermissionError("First admin setup is already complete.")
        settings = self.get_auth_settings()
        if not settings.local_users_enabled:
            raise PermissionError("Local Workbench users are disabled.")
        self.create_workbench_user(
            WorkbenchUserCreateRequest(
                username=payload.username,
                password=payload.password,
                role=WorkbenchUserRole.ADMIN,
                enabled=True,
                display_name=payload.display_name or payload.username,
            )
        )
        return self.login_with_workbench_password(payload)

    def login_with_workbench_password(self, payload: WorkbenchLocalLoginRequest) -> SessionData:
        settings = self.get_auth_settings()
        if not settings.local_users_enabled:
            raise PermissionError("Workbench username/password sign-in is disabled.")
        username = self._normalize_workbench_username(payload.username)
        self._bootstrap_default_workbench_admin_if_needed(username, payload.password)
        server = self._server_for_workbench_local_login(payload.server_id)
        user_record = self.repo.get_workbench_user(username)
        if not user_record or not user_record.enabled or not self._verify_workbench_password(payload.password, user_record.password_hash):
            raise PermissionError("Invalid Workbench username or password.")
        user = UserContext(
            preferred_username=username,
            server_id=server.id,
            server_name=server.name,
            auth_source="workbench-local",
        )
        authorization_context = AuthorizationContext(
            roles=[user_record.role.value],
            source="workbench-local",
            can_manage_server_presets=user_record.role == WorkbenchUserRole.ADMIN,
            can_manage_groups=user_record.role in {WorkbenchUserRole.ADMIN, WorkbenchUserRole.GROUP_MANAGER},
        )
        session = self.sessions.create_session(
            server,
            user,
            authorization_context,
            TokenBundle(token_type="WorkbenchLocal", upstream_user=username),
            self._snapshot_capabilities(server),
        )
        self.repo.upsert_workbench_user(user_record.model_copy(update={"last_login_at": utcnow()}))
        self._update_user_server_state(user.preferred_username, server.id, session.created_at)
        logger.info("workbench-local-login-complete", user=username, server_id=server.id)
        return session

    def _server_for_workbench_local_login(self, server_id: str) -> ServerProfile:
        if server_id:
            return self._require_server(server_id, include_disabled=False)
        servers = self.repo.list_servers()
        if servers:
            return servers[0]
        return ServerProfile(
            id="workbench-setup",
            name="Workbench Setup",
            base_url="http://workbench.local",
            enabled=True,
        )

    def _bootstrap_default_workbench_admin_if_needed(self, username: str, password: str) -> None:
        if self.repo.list_workbench_users():
            return
        default_username = self._normalize_workbench_username(self.settings.workbench_default_admin_username or "admin")
        default_password = self.settings.workbench_default_admin_password or "admin"
        if username != default_username or password != default_password:
            return
        user = WorkbenchUserRecord(
            username=default_username,
            password_hash=self._hash_workbench_password(default_password, allow_weak=True),
            role=WorkbenchUserRole.ADMIN,
            enabled=True,
            display_name="Workbench Administrator",
            password_change_required=True,
        )
        self.repo.upsert_workbench_user(user)
        logger.warning("workbench-default-admin-bootstrapped", user=default_username)

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
        admin_settings = self.get_workbench_agent_admin_settings() if self.can_manage_server_presets(session) else None
        if secret is None:
            return WorkbenchAgentStatus(
                configured=False,
                admin_settings=admin_settings,
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
            reference_file_count=len(secret.reference_file_ids) or (1 if secret.reference_file_id else 0),
            reference_synced_at=secret.reference_synced_at,
            updated_at=secret.updated_at,
            knowledge_synced_at=secret.knowledge_synced_at,
            admin_settings=admin_settings,
            **kb_status,
            message="Open WebUI agent mapping is ready. Sync a branch knowledge bundle or start chatting.",
        )

    def get_workbench_agent_admin_settings(self) -> WorkbenchAgentAdminSettings:
        stored = self.repo.get_agent_admin_settings() if hasattr(self, "repo") else None
        if stored is not None:
            return self._normalize_workbench_agent_admin_settings(stored)
        return self._normalize_workbench_agent_admin_settings(
            WorkbenchAgentAdminSettings(
                openwebui_verify_tls=bool(getattr(self.settings, "openwebui_verify_tls", False)),
                openwebui_allow_insecure_http=bool(getattr(self.settings, "openwebui_allow_insecure_http", False)),
                openwebui_ca_bundle_path=str(getattr(self.settings, "openwebui_ca_bundle_path", "") or ""),
                openwebui_allowed_hosts=list(getattr(self.settings, "openwebui_allowed_hosts", [])),
                three_ds_kb_path=str(self._default_three_ds_kb_root()),
                three_ds_kb_retrieval_max_documents=int(getattr(self.settings, "three_ds_kb_retrieval_max_documents", 12)),
                three_ds_kb_retrieval_max_characters=int(getattr(self.settings, "three_ds_kb_retrieval_max_characters", 120_000)),
            )
        )

    def set_workbench_agent_admin_settings(self, payload: WorkbenchAgentAdminSettings) -> WorkbenchAgentAdminSettings:
        current_root = self._effective_three_ds_kb_root()
        updated = self.repo.set_agent_admin_settings(self._normalize_workbench_agent_admin_settings(payload))
        next_root = self._effective_three_ds_kb_root(updated)
        if current_root != next_root:
            with self._three_ds_corpus_lock:
                self._three_ds_corpus = None
                self._three_ds_corpus_root = None
        return updated

    def _normalize_workbench_agent_admin_settings(self, settings: WorkbenchAgentAdminSettings) -> WorkbenchAgentAdminSettings:
        ca_bundle_path = settings.openwebui_ca_bundle_path.strip()
        three_ds_kb_path = settings.three_ds_kb_path.strip() or str(self._default_three_ds_kb_root())
        allowed_hosts = list(dict.fromkeys(host.strip().lower() for host in settings.openwebui_allowed_hosts if host.strip()))
        return settings.model_copy(
            update={
                "openwebui_ca_bundle_path": ca_bundle_path,
                "three_ds_kb_path": three_ds_kb_path,
                "openwebui_allowed_hosts": allowed_hosts,
            }
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
            reference_file_ids=existing.reference_file_ids if existing and existing.base_url == base_url else [],
            reference_file_names=existing.reference_file_names if existing and existing.base_url == base_url else [],
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
            async with httpx.AsyncClient(timeout=30.0, verify=self._openwebui_verify(), follow_redirects=True) as client:
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
        report: Callable[[int, str], Awaitable[None]] | None = None,
    ) -> WorkbenchAgentKnowledgeStatus:
        secret = self._workbench_agent_secret(session)
        if secret is None:
            raise ValueError("Save an Open WebUI mapping before syncing knowledge.")
        if not secret.model_id:
            raise ValueError("Choose an Open WebUI agent or model before syncing knowledge.")

        summary = self.get_branch_cache_summary_for_user(session.server.id, session.user.preferred_username, project_id, branch_id)
        if summary is None:
            raise ValueError("The selected stored project branch is not available to this Workbench user.")

        if report is None:
            await asyncio.to_thread(self._validate_three_ds_corpus)
        if report is not None:
            await report(45, "Building persistent Workbench + 3DS reference documents.")
        reference_files, reference_stats, reference_fingerprint = await self._ensure_workbench_reference_knowledge(
            secret,
            session=session,
            report=report,
        )
        reference_file_id, reference_file_name = reference_files[0]
        if report is not None:
            await report(78, "Building selected branch model knowledge document.")
        file_name, file_content, bundle_stats = await asyncio.to_thread(
            self._build_workbench_agent_knowledge_document,
            session,
            project_id,
            branch_id,
        )
        if report is not None:
            await report(86, f"Uploading selected branch model knowledge file: {file_name}.")
        file_id = await self._upload_openwebui_markdown_file(secret, file_name, file_content)
        if report is not None:
            await report(94, f"Open WebUI processed selected branch model knowledge file: {file_name}.")

        updated_secret = secret.model_copy(
            update={
                "knowledge_file_id": file_id,
                "knowledge_file_name": file_name,
                "knowledge_project_id": project_id,
                "knowledge_branch_id": branch_id,
                "knowledge_synced_at": utcnow(),
                "reference_file_id": reference_file_id,
                "reference_file_name": reference_file_name,
                "reference_file_ids": [file_id for file_id, _ in reference_files],
                "reference_file_names": [name for _, name in reference_files],
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
            reference_file_count=len(reference_files),
            synced_at=updated_secret.knowledge_synced_at or utcnow(),
            **bundle_stats,
            **reference_stats,
            message=f"Open WebUI processed the branch model file and {len(reference_files)} persistent Workbench + authoritative 3DS_KB control files. Every chat receives query-routed evidence from that same validated corpus.",
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
            await context.report(5, "Validating the authoritative 3DS_KB and preparing its control rails plus the branch model file.")
            loop = asyncio.get_running_loop()
            last_progress = 5

            def report_three_ds_progress(done: int, total: int, relative_path: str) -> None:
                nonlocal last_progress
                progress = 5 + min(35, int(35 * done / max(1, total)))
                last_progress = max(last_progress, progress)
                message = f"Validated 3DS_KB evidence {done}/{total}: {relative_path}"
                asyncio.run_coroutine_threadsafe(context.report(last_progress, message), loop)

            validation_task = asyncio.create_task(asyncio.to_thread(self._validate_three_ds_corpus, report_three_ds_progress))
            heartbeat = 0
            while not validation_task.done():
                await asyncio.sleep(10)
                if validation_task.done():
                    break
                heartbeat += 1
                last_progress = max(last_progress, min(39, 5 + heartbeat))
                await context.report(
                    last_progress,
                    f"Still validating the authoritative 3DS_KB integrity gate ({heartbeat * 10}s elapsed).",
                )
            await validation_task
            await context.report(42, "3DS_KB integrity gate passed; preparing persistent Workbench reference files.")
            result = await self.sync_workbench_agent_knowledge(session, project_id, branch_id, report=context.report)
            await context.report(100, "Open WebUI finished processing the validated 3DS_KB controls and branch model file.")
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
            or not self._workbench_agent_branch_matches(session.server.id, payload.project_id, secret.knowledge_branch_id, payload.branch_id)
        ):
            await self.sync_workbench_agent_knowledge(session, payload.project_id, payload.branch_id)
            working_secret = self._workbench_agent_secret(session) or secret

        if not working_secret.knowledge_file_id:
            raise ValueError("Sync the current project branch knowledge before chatting with Workbench Agent.")

        reference_files, _, reference_fingerprint = await self._ensure_workbench_reference_knowledge(
            working_secret,
            session=session,
        )
        reference_file_id, reference_file_name = reference_files[0]
        if working_secret.reference_file_id != reference_file_id or working_secret.reference_fingerprint != reference_fingerprint:
            working_secret = working_secret.model_copy(
                update={
                    "reference_file_id": reference_file_id,
                    "reference_file_name": reference_file_name,
                    "reference_file_ids": [file_id for file_id, _ in reference_files],
                    "reference_file_names": [name for _, name in reference_files],
                    "reference_fingerprint": reference_fingerprint,
                    "reference_synced_at": utcnow(),
                    "updated_at": utcnow(),
                }
            )
            self._store_workbench_agent_secret(session, working_secret)

        retrieval_query = "\n".join(
            message.content for message in payload.messages if message.role == "user"
        )
        query_context = await asyncio.to_thread(self._three_ds_query_context, retrieval_query)
        request_messages = [
            {
                "role": "system",
                "content": self._workbench_agent_system_prompt(
                    session,
                    payload.project_id,
                    payload.branch_id,
                    query_context=query_context,
                ),
            },
            *[message.model_dump() for message in payload.messages],
        ]
        request_body = {
            "model": working_secret.model_id,
            "messages": request_messages,
            "files": [
                *[
                    {"type": "file", "id": file_id, "status": "processed"}
                    for file_id, _ in reference_files
                ],
                {"type": "file", "id": working_secret.knowledge_file_id, "status": "processed"},
            ],
        }
        chat_timeout = httpx.Timeout(connect=30.0, read=300.0, write=120.0, pool=60.0)
        try:
            async with httpx.AsyncClient(timeout=chat_timeout, verify=self._openwebui_verify(), follow_redirects=True) as client:
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
            message="Workbench Agent used the mapped Open WebUI model with validated, query-routed evidence from the single authoritative 3DS_KB and the accessible branch model.",
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
        if session.user.auth_source != "workbench-local":
            await self._ensure_plugin_listing_permissions(session, force=refresh)
        projects = self._project_summaries_from_cache_for_user(session)
        self.repo.delete_user_cache(
            self._user_key(session.user.preferred_username),
            session.server.id,
            PROJECT_LIST_CACHE_KEY,
        )
        logger.debug("twc-project-list-ui", user=session.user.preferred_username, server_id=session.server.id, delivered_count=len(projects))
        return projects

    async def list_project_branches(self, session: SessionData, project_id: str, workspace_id: str | None = None, refresh: bool = False):
        # Always filter branch names from the current stored permission
        # snapshot; a pre-refresh UI cache must not survive a revocation.
        branches = self._branch_summaries_from_cache_for_user(session, project_id)
        logger.debug(
            "twc-branch-list-ui",
            user=session.user.preferred_username,
            server_id=session.server.id,
            project_id=project_id,
            workspace_id=workspace_id,
            delivered_count=len(branches),
        )
        return branches

    def _project_summaries_from_cache_for_user(self, session: SessionData) -> list[ProjectSummary]:
        if self._has_workbench_admin_model_visibility(session):
            cached_projects = self.list_cached_projects_for_user(
                session.server.id,
                session.user.preferred_username,
                include_all_workbench_admin=True,
            )
        else:
            cached_projects = self.list_cached_projects_for_user(session.server.id, session.user.preferred_username)
        projects: list[ProjectSummary] = []
        for project in cached_projects:
            plugin_branches = self._plugin_cache_project_branches(
                session.server.id,
                project.project_id,
                project.branches,
            )
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
        if self._has_workbench_admin_model_visibility(session):
            cached_projects = self.list_cached_projects_for_user(
                session.server.id,
                session.user.preferred_username,
                include_all_workbench_admin=True,
            )
        else:
            cached_projects = self.list_cached_projects_for_user(session.server.id, session.user.preferred_username)
        for project in cached_projects:
            if project.project_id != project_id:
                continue
            plugin_branches = self._plugin_cache_project_branches(
                session.server.id,
                project.project_id,
                project.branches,
            )
            return [
                BranchSummary(
                    id=branch.branch_id,
                    name=branch.branch_name,
                    description=f"Stored branch model cache ({branch.status.value})",
                )
                for branch in sorted(
                    plugin_branches,
                    key=lambda item: ((item.branch_name or item.branch_id).lower(), item.branch_id),
                )
            ]
        return []

    def _plugin_cache_project_branches(
        self,
        server_id: str,
        project_id: str,
        branches: list[CacheProjectBranchEntry],
    ) -> list[CacheProjectBranchEntry]:
        return [
            branch
            for branch in branches
            if self._is_plugin_managed_summary(
                self.repo.get_branch_cache_summary(server_id, project_id, branch.branch_id)
            )
        ]

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
            include_all_workbench_admin=self._has_workbench_admin_model_visibility(session),
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
                include_all_workbench_admin=self._has_workbench_admin_model_visibility(session),
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
            if self._has_workbench_admin_model_visibility(session):
                return summary
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
        if self._has_workbench_admin_model_visibility(session):
            models = [
                CachedModelView(model=model, permissions=None)
                for model in self.repo.list_cached_models(session.server.id, project_id, branch_id)
            ]
            return BranchCacheSnapshot(summary=summary, models=models)
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
        if self._has_workbench_admin_model_visibility(session):
            model = self.repo.get_cached_model(session.server.id, project_id, branch_id, model_id)
            return CachedModelView(model=model, permissions=None) if model is not None else None
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
            include_all_workbench_admin=self._has_workbench_admin_model_visibility(session),
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
            include_all_workbench_admin=self._has_workbench_admin_model_visibility(session),
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
            include_all_workbench_admin=self._has_workbench_admin_model_visibility(session),
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
            include_all_workbench_admin=self._has_workbench_admin_model_visibility(session),
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

    def list_cached_projects_for_user(
        self,
        server_id: str,
        preferred_username: str,
        *,
        include_all_workbench_admin: bool = False,
    ) -> list[CacheProjectEntry]:
        self._require_server(server_id, include_disabled=True)
        user_id = self._user_key(preferred_username)
        projects: dict[str, CacheProjectEntry] = {}
        for summary in self.repo.list_branch_cache_summaries(server_id):
            if include_all_workbench_admin:
                # Admin catalog mode intentionally bypasses per-user branch
                # access filtering so admins can discover projects that need
                # permission setup. It does not mint branch access records.
                visible_model_count = summary.model_count
                visible_element_count = summary.element_count
            elif self._is_plugin_managed_summary(summary):
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

    def get_cached_project_branch_dump_for_user(
        self,
        server_id: str,
        preferred_username: str,
        project_id: str,
        branch_id: str = "trunk",
        *,
        include_tree: bool = True,
        include_elements: bool = True,
        include_details: bool = True,
        include_raw_payload: bool = True,
        include_permissions: bool = True,
        include_all_workbench_admin: bool = False,
    ) -> dict[str, Any]:
        """Return a single-file Workbench dump for one cached project branch.

        This is intentionally a Workbench cache export. It never tries to build
        model content from live TWC REST; the plugin snapshot remains the source
        for model structure and element/specification data.
        """
        self._require_server(server_id, include_disabled=True)
        resolved_branch_id = self._resolve_cached_branch_id(server_id, project_id, branch_id or "trunk")
        summary = self.repo.get_branch_cache_summary(server_id, project_id, resolved_branch_id)
        if summary is None:
            raise ValueError("No cached branch snapshot exists for this project and branch.")

        user_id = self._user_key(preferred_username)
        visible_models = self._visible_cached_models_for_user(
            user_id,
            server_id,
            project_id,
            resolved_branch_id,
            include_all_workbench_admin=include_all_workbench_admin,
        )
        if not visible_models:
            raise PermissionError("The active Workbench user cannot read that cached project branch.")

        visible_model_ids = {model.model_id for model in visible_models}
        total_branch_elements = self.repo.count_cached_elements_for_branch(server_id, project_id, resolved_branch_id)
        all_visible_elements = self._visible_cached_elements_for_user(
            user_id,
            server_id,
            project_id,
            resolved_branch_id,
            include_all_workbench_admin=include_all_workbench_admin,
        )
        if not include_all_workbench_admin:
            all_visible_elements = [element for element in all_visible_elements if element.model_id in visible_model_ids]

        tree = (
            self.get_cached_branch_tree_for_user(
                server_id,
                preferred_username,
                project_id,
                resolved_branch_id,
                depth=None,
                include_orphans=True,
                include_all_workbench_admin=include_all_workbench_admin,
            ).model_dump(mode="json")
            if include_tree
            else None
        )
        explicitly_primary = [model for model in visible_models if bool(model.payload.get("primary"))]
        primary = explicitly_primary[0] if explicitly_primary else visible_models[0]
        project_usages = ProjectUsageResponse(
            project_id=project_id,
            branch_id=resolved_branch_id,
            primary_model_id=primary.model_id,
            primary_model_name=primary.name,
            total=max(len(visible_models) - 1, 0),
            source="snapshot" if explicitly_primary else "legacy-snapshot-inferred",
            items=[
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
                for model in visible_models
                if model.model_id != primary.model_id
            ],
        )

        detail_worker_count = self._project_dump_detail_worker_count(len(all_visible_elements), include_details=include_details)
        elements_payload: list[dict[str, Any]] = []
        if include_elements:
            if detail_worker_count > 1:
                with ThreadPoolExecutor(max_workers=detail_worker_count, thread_name_prefix="workbench-dump-detail") as executor:
                    elements_payload = list(
                        executor.map(
                            lambda element: self._project_dump_element_payload(
                                element,
                                server_id,
                                preferred_username,
                                project_id,
                                resolved_branch_id,
                                include_raw_payload=include_raw_payload,
                                include_details=include_details,
                                include_all_workbench_admin=include_all_workbench_admin,
                            ),
                            all_visible_elements,
                        )
                    )
            else:
                elements_payload = [
                    self._project_dump_element_payload(
                        element,
                        server_id,
                        preferred_username,
                        project_id,
                        resolved_branch_id,
                        include_raw_payload=include_raw_payload,
                        include_details=include_details,
                        include_all_workbench_admin=include_all_workbench_admin,
                    )
                    for element in all_visible_elements
                ]

        permission_attachment = self.repo.get_branch_permission_attachment(server_id, project_id, resolved_branch_id)
        branch_access_records = self.repo.list_branch_access_records(server_id, project_id, resolved_branch_id)
        current_branch_access = self._plugin_branch_access_or_source_fallback(
            user_id,
            server_id,
            project_id,
            resolved_branch_id,
            summary,
        )
        if current_branch_access is None and include_all_workbench_admin:
            current_branch_access = BranchAccessRecord(
                user_id=user_id,
                server_id=server_id,
                project_id=project_id,
                branch_id=resolved_branch_id,
                workspace_id=summary.workspace_id,
                branch_name=summary.branch_name or resolved_branch_id,
                latest_revision=summary.latest_revision,
                accessible=True,
                editable=True,
                admin_access=True,
                roles=["Workbench Administrator"],
                source="workbench-admin-full-cache-view",
            )

        return {
            "schema_version": "workbench-project-branch-dump.v1",
            "purpose": "One-call Workbench cache export for a stored project branch. Model content comes from the Cameo plugin snapshot; TWC REST is not used to construct model data.",
            "exported_at": utcnow().isoformat(),
            "requested": {
                "server_id": server_id,
                "project_id": project_id,
                "branch_id": branch_id or "trunk",
            },
            "resolved": {
                "server_id": server_id,
                "project_id": project_id,
                "branch_id": resolved_branch_id,
                "branch_name": summary.branch_name or resolved_branch_id,
                "workspace_id": summary.workspace_id,
                "latest_revision": summary.latest_revision,
            },
            "selection": {
                "include_tree": include_tree,
                "include_elements": include_elements,
                "include_details": include_details,
                "include_raw_payload": include_raw_payload,
                "include_permissions": include_permissions,
                "admin_full_cache_view": include_all_workbench_admin,
                "detail_worker_count": detail_worker_count,
                "visible_model_count": len(visible_models),
                "visible_element_count": len(all_visible_elements),
                "total_cached_branch_elements": total_branch_elements,
            },
            "branch_summary": summary.model_dump(mode="json"),
            "models": [model.model_dump(mode="json") for model in visible_models],
            "project_usages": project_usages.model_dump(mode="json"),
            "tree": tree,
            "elements": elements_payload,
            "permissions": {
                "current_user_branch_access": current_branch_access.model_dump(mode="json") if current_branch_access is not None else None,
                "branch_access_records": [record.model_dump(mode="json") for record in branch_access_records] if include_permissions else [],
                "permission_attachment": permission_attachment.model_dump(mode="json") if include_permissions and permission_attachment is not None else None,
            },
        }

    def _project_dump_detail_worker_count(self, element_count: int, *, include_details: bool) -> int:
        if not include_details or element_count < 50:
            return 1
        cpu_count = os.cpu_count() or 2
        # Detail derivation walks payload references and serializes derived
        # ItemDetails. Use more CPU on real model dumps, but keep a ceiling so
        # one export does not starve the server.
        by_size = max(2, min(8, element_count // 250 + 1))
        return max(1, min(cpu_count, by_size))

    def export_cached_project_branch_tableau_db_for_user(
        self,
        server_id: str,
        preferred_username: str,
        project_id: str,
        branch_id: str = "trunk",
        *,
        include_all_workbench_admin: bool = False,
    ) -> Path:
        """Build a Tableau-readable SQLite reporting copy for one cached branch.

        The generated file is intentionally separate from the operational
        Workbench database. It contains model/tree/specification/reporting facts
        from the plugin-backed cache and excludes application secrets, sessions,
        API keys, ingest tokens, and raw authentication state.
        """
        payload = self.get_cached_project_branch_dump_for_user(
            server_id,
            preferred_username,
            project_id,
            branch_id,
            include_tree=True,
            include_elements=True,
            include_details=True,
            include_raw_payload=False,
            include_permissions=True,
            include_all_workbench_admin=include_all_workbench_admin,
        )
        if not include_all_workbench_admin:
            current_access = (payload.get("permissions") or {}).get("current_user_branch_access") or {}
            current_payload = current_access.get("payload") if isinstance(current_access, dict) else {}
            current_payload = current_payload if isinstance(current_payload, dict) else {}
            has_project_admin_access = bool(
                current_access.get("admin_access")
                or current_payload.get("branch_admin_access")
                or current_payload.get("access_admin_access")
            )
            if not has_project_admin_access:
                raise PermissionError("Only Workbench administrators or project administrators can export a Tableau project database.")

        resolved = payload.get("resolved") or {}
        branch_summary = payload.get("branch_summary") or {}
        project_name = str(branch_summary.get("project_name") or resolved.get("project_id") or project_id)
        branch_name = str(resolved.get("branch_name") or resolved.get("branch_id") or branch_id or "trunk")
        safe_project = self._tableau_export_slug(project_name, fallback="project")
        safe_branch = self._tableau_export_slug(branch_name, fallback="trunk")
        exported_at = utcnow().strftime("%Y%m%dT%H%M%SZ")
        export_dir = self.settings.resolved_export_dir / "tableau"
        export_dir.mkdir(parents=True, exist_ok=True)
        db_path = export_dir / f"workbench-tableau_{safe_project}_{safe_branch}_{exported_at}.sqlite3"
        tmp_path = db_path.with_name(f"{db_path.stem}.tmp{db_path.suffix}")
        if tmp_path.exists():
            tmp_path.unlink()

        try:
            conn = sqlite3.connect(tmp_path)
            try:
                conn.execute("PRAGMA journal_mode=OFF")
                conn.execute("PRAGMA synchronous=OFF")
                self._write_tableau_export_schema(conn)
                self._write_tableau_export_rows(conn, payload)
                conn.execute("PRAGMA optimize")
                conn.commit()
            finally:
                conn.close()
            tmp_path.replace(db_path)
        finally:
            if tmp_path.exists():
                with suppress(OSError):
                    tmp_path.unlink()
        return db_path

    def _tableau_export_slug(self, value: str, *, fallback: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "")).strip("-")
        return slug[:120] or fallback

    def _tableau_json(self, value: Any) -> str:
        if value is None:
            return ""
        return json.dumps(value, default=str, ensure_ascii=False, sort_keys=True)

    def _tableau_text_list(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return ", ".join(str(item) for item in value if item is not None)
        return str(value)

    def _write_tableau_export_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE export_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE tableau_readme (
                section TEXT PRIMARY KEY,
                body TEXT NOT NULL
            );
            CREATE TABLE project_branch (
                server_id TEXT,
                project_id TEXT,
                project_name TEXT,
                branch_id TEXT,
                branch_name TEXT,
                workspace_id TEXT,
                latest_revision TEXT,
                snapshot_hash TEXT,
                source_kind TEXT,
                source_user TEXT,
                model_count INTEGER,
                element_count INTEGER,
                visible_model_count INTEGER,
                visible_element_count INTEGER,
                total_cached_branch_elements INTEGER,
                exported_at TEXT
            );
            CREATE TABLE models (
                model_id TEXT PRIMARY KEY,
                server_id TEXT,
                project_id TEXT,
                branch_id TEXT,
                workspace_id TEXT,
                latest_revision TEXT,
                name TEXT,
                qualified_name TEXT,
                usage_type TEXT,
                root_ids_json TEXT,
                element_count INTEGER,
                source_user TEXT,
                synced_at TEXT,
                metadata_json TEXT
            );
            CREATE TABLE project_usages (
                usage_id TEXT PRIMARY KEY,
                model_id TEXT,
                name TEXT,
                qualified_name TEXT,
                usage_type TEXT,
                version TEXT,
                uri TEXT,
                automatic INTEGER
            );
            CREATE TABLE tree_nodes (
                row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT,
                parent_id TEXT,
                depth INTEGER,
                ordinal INTEGER,
                label TEXT,
                node_type TEXT,
                path TEXT,
                metadata_json TEXT
            );
            CREATE TABLE elements (
                element_id TEXT PRIMARY KEY,
                model_id TEXT,
                server_id TEXT,
                project_id TEXT,
                branch_id TEXT,
                workspace_id TEXT,
                latest_revision TEXT,
                name TEXT,
                item_type TEXT,
                path TEXT,
                owner_id TEXT,
                owner_name TEXT,
                description TEXT,
                documentation_markdown TEXT,
                raw_types_csv TEXT,
                stereotypes_csv TEXT,
                editable INTEGER,
                child_count INTEGER,
                source_user TEXT,
                synced_at TEXT,
                metadata_json TEXT
            );
            CREATE TABLE element_stereotypes (
                element_id TEXT,
                stereotype TEXT
            );
            CREATE TABLE element_references (
                element_id TEXT,
                reference_group TEXT,
                target_id TEXT,
                target_name TEXT,
                target_type TEXT,
                relationship_type TEXT,
                path TEXT,
                metadata_json TEXT
            );
            CREATE TABLE element_relationships (
                element_id TEXT,
                target_id TEXT,
                target_name TEXT,
                target_type TEXT,
                relationship_type TEXT,
                direction TEXT,
                label TEXT,
                metadata_json TEXT
            );
            CREATE TABLE specification_sections (
                element_id TEXT,
                section_name TEXT,
                section_order INTEGER,
                section_json TEXT
            );
            CREATE TABLE specification_fields (
                element_id TEXT,
                section_name TEXT,
                field_name TEXT,
                field_order INTEGER,
                value_text TEXT,
                target_id TEXT,
                target_name TEXT,
                value_json TEXT
            );
            CREATE TABLE permissions (
                scope_id TEXT,
                scope_type TEXT,
                principal_id TEXT,
                principal_name TEXT,
                principal_type TEXT,
                role_name TEXT,
                action TEXT,
                application TEXT,
                inherited INTEGER,
                accessible INTEGER,
                editable INTEGER,
                branch_admin_access INTEGER,
                access_admin_access INTEGER,
                via_groups_json TEXT,
                readonly_branch_ids_json TEXT
            );
            CREATE TABLE branch_access (
                user_id TEXT,
                accessible INTEGER,
                editable INTEGER,
                admin_access INTEGER,
                roles_json TEXT,
                via_groups_json TEXT,
                source TEXT,
                updated_at TEXT,
                payload_json TEXT
            );
            CREATE INDEX idx_tree_nodes_parent ON tree_nodes(parent_id);
            CREATE INDEX idx_tree_nodes_id ON tree_nodes(node_id);
            CREATE INDEX idx_elements_model ON elements(model_id);
            CREATE INDEX idx_elements_type ON elements(item_type);
            CREATE INDEX idx_references_target ON element_references(target_id);
            CREATE INDEX idx_relationships_target ON element_relationships(target_id);
            CREATE INDEX idx_permissions_principal ON permissions(principal_id);
            """
        )

    def _write_tableau_export_rows(self, conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
        exported_at = str(payload.get("exported_at") or utcnow().isoformat())
        requested = payload.get("requested") or {}
        resolved = payload.get("resolved") or {}
        selection = payload.get("selection") or {}
        branch_summary = payload.get("branch_summary") or {}
        conn.executemany(
            "INSERT INTO export_metadata(key, value) VALUES (?, ?)",
            [
                ("schema_version", "workbench-tableau-project-branch.v1"),
                ("created_by", "Created by: Raymond Reeves Engineering Tech 4 2026"),
                ("exported_at", exported_at),
                ("purpose", "Tableau-safe reporting copy for one Workbench cached project branch."),
                ("source", "Workbench plugin-backed cache. This export excludes operational secrets, tokens, sessions, and raw authentication state."),
                ("requested_json", self._tableau_json(requested)),
                ("resolved_json", self._tableau_json(resolved)),
            ],
        )
        conn.executemany(
            "INSERT INTO tableau_readme(section, body) VALUES (?, ?)",
            [
                ("start_here", "Connect Tableau to this SQLite file. Use project_branch as the one-row context table, elements as the main fact table, tree_nodes for containment, and element_references/element_relationships for traceability."),
                ("security", "This is a derived reporting copy only. Workbench application secrets, ingest tokens, API keys, sessions, passwords, and raw auth state are intentionally not exported."),
                ("joins", "Join elements.element_id to tree_nodes.node_id, element_references.element_id, element_relationships.element_id, specification_fields.element_id, and element_stereotypes.element_id."),
            ],
        )
        conn.execute(
            """
            INSERT INTO project_branch(
                server_id, project_id, project_name, branch_id, branch_name,
                workspace_id, latest_revision, snapshot_hash, source_kind,
                source_user, model_count, element_count, visible_model_count,
                visible_element_count, total_cached_branch_elements, exported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolved.get("server_id"),
                resolved.get("project_id"),
                branch_summary.get("project_name") or resolved.get("project_id"),
                resolved.get("branch_id"),
                resolved.get("branch_name") or resolved.get("branch_id"),
                resolved.get("workspace_id"),
                resolved.get("latest_revision"),
                branch_summary.get("snapshot_hash"),
                branch_summary.get("source_kind"),
                branch_summary.get("source_user"),
                int(branch_summary.get("model_count") or 0),
                int(branch_summary.get("element_count") or 0),
                int(selection.get("visible_model_count") or 0),
                int(selection.get("visible_element_count") or 0),
                int(selection.get("total_cached_branch_elements") or 0),
                exported_at,
            ),
        )

        models = payload.get("models") if isinstance(payload.get("models"), list) else []
        conn.executemany(
            """
            INSERT OR REPLACE INTO models(
                model_id, server_id, project_id, branch_id, workspace_id,
                latest_revision, name, qualified_name, usage_type, root_ids_json,
                element_count, source_user, synced_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    model.get("model_id"),
                    model.get("server_id"),
                    model.get("project_id"),
                    model.get("branch_id"),
                    model.get("workspace_id"),
                    model.get("latest_revision"),
                    model.get("name"),
                    (model.get("payload") or {}).get("qualified_name") if isinstance(model.get("payload"), dict) else "",
                    (model.get("payload") or {}).get("usage_type") if isinstance(model.get("payload"), dict) else "",
                    self._tableau_json(model.get("root_ids") or []),
                    int(model.get("element_count") or 0),
                    model.get("source_user"),
                    model.get("synced_at"),
                    self._tableau_json({key: value for key, value in (model.get("payload") or {}).items() if key not in {"raw", "source_payload"}}),
                )
                for model in models
                if isinstance(model, dict)
            ],
        )

        usages = ((payload.get("project_usages") or {}).get("items") if isinstance(payload.get("project_usages"), dict) else []) or []
        conn.executemany(
            """
            INSERT OR REPLACE INTO project_usages(
                usage_id, model_id, name, qualified_name, usage_type, version, uri, automatic
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    usage.get("id") or usage.get("model_id"),
                    usage.get("model_id"),
                    usage.get("name"),
                    usage.get("qualified_name"),
                    usage.get("usage_type"),
                    usage.get("version"),
                    usage.get("uri"),
                    1 if usage.get("automatic") else 0 if usage.get("automatic") is not None else None,
                )
                for usage in usages
                if isinstance(usage, dict)
            ],
        )

        tree = payload.get("tree") if isinstance(payload.get("tree"), dict) else {}
        tree_rows: list[tuple[Any, ...]] = []
        self._collect_tableau_tree_rows(tree.get("nodes") or [], tree_rows, parent_id=None, depth=0)
        conn.executemany(
            """
            INSERT INTO tree_nodes(node_id, parent_id, depth, ordinal, label, node_type, path, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tree_rows,
        )

        elements = payload.get("elements") if isinstance(payload.get("elements"), list) else []
        element_rows: list[tuple[Any, ...]] = []
        stereotype_rows: list[tuple[Any, ...]] = []
        reference_rows: list[tuple[Any, ...]] = []
        relationship_rows: list[tuple[Any, ...]] = []
        section_rows: list[tuple[Any, ...]] = []
        field_rows: list[tuple[Any, ...]] = []
        for element in elements:
            if not isinstance(element, dict):
                continue
            details = element.get("derived_item_details") if isinstance(element.get("derived_item_details"), dict) else {}
            metadata = details.get("metadata") if isinstance(details.get("metadata"), dict) else {}
            owner = details.get("owner") if isinstance(details.get("owner"), dict) else {}
            element_id = str(element.get("element_id") or details.get("id") or "")
            safe_metadata = dict(metadata)
            safe_metadata.pop("source_payload", None)
            element_rows.append(
                (
                    element_id,
                    element.get("model_id"),
                    element.get("server_id"),
                    element.get("project_id"),
                    element.get("branch_id"),
                    element.get("workspace_id"),
                    element.get("latest_revision"),
                    details.get("name") or element.get("name"),
                    details.get("item_type") or element.get("item_type"),
                    details.get("path") or element.get("path"),
                    owner.get("id") or metadata.get("owner_id"),
                    owner.get("name") or metadata.get("owner_name"),
                    details.get("description") or "",
                    details.get("documentation_markdown") or "",
                    self._tableau_text_list(details.get("raw_types")),
                    self._tableau_text_list(details.get("stereotypes")),
                    1 if details.get("editable") else 0,
                    int(element.get("child_count") or 0),
                    element.get("source_user"),
                    element.get("synced_at"),
                    self._tableau_json(safe_metadata),
                )
            )
            for stereotype in details.get("stereotypes") or []:
                stereotype_rows.append((element_id, str(stereotype)))
            for group_name, references in (
                ("type_references", details.get("type_references") or []),
                ("contained_elements", details.get("contained_elements") or []),
                ("related_items", details.get("related_items") or []),
            ):
                for reference in references:
                    if isinstance(reference, dict):
                        reference_rows.append(
                            (
                                element_id,
                                group_name,
                                reference.get("id"),
                                reference.get("name"),
                                reference.get("item_type"),
                                reference.get("relationship_type"),
                                reference.get("path"),
                                self._tableau_json({key: value for key, value in reference.items() if key not in {"id", "name", "item_type", "relationship_type", "path"}}),
                            )
                        )
            relationships = details.get("relationships") if isinstance(details.get("relationships"), list) else []
            for relationship in relationships:
                if not isinstance(relationship, dict):
                    continue
                target_id = relationship.get("target_id") or relationship.get("targetId") or relationship.get("to_id") or relationship.get("to") or relationship.get("id")
                target_name = relationship.get("target_name") or relationship.get("targetName") or relationship.get("to_name") or relationship.get("name")
                target_type = relationship.get("target_type") or relationship.get("targetType") or relationship.get("item_type")
                relationship_type = relationship.get("relationship_type") or relationship.get("relationshipType") or relationship.get("type") or relationship.get("kind")
                relationship_rows.append(
                    (
                        element_id,
                        target_id,
                        target_name,
                        target_type,
                        relationship_type,
                        relationship.get("direction") or relationship.get("role") or "",
                        relationship.get("label") or relationship.get("name") or relationship_type or "",
                        self._tableau_json(relationship),
                    )
                )
            self._collect_tableau_spec_rows(element_id, details, section_rows, field_rows)

        conn.executemany(
            """
            INSERT OR REPLACE INTO elements(
                element_id, model_id, server_id, project_id, branch_id, workspace_id,
                latest_revision, name, item_type, path, owner_id, owner_name,
                description, documentation_markdown, raw_types_csv, stereotypes_csv,
                editable, child_count, source_user, synced_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            element_rows,
        )
        conn.executemany("INSERT INTO element_stereotypes(element_id, stereotype) VALUES (?, ?)", stereotype_rows)
        conn.executemany(
            """
            INSERT INTO element_references(
                element_id, reference_group, target_id, target_name, target_type,
                relationship_type, path, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            reference_rows,
        )
        conn.executemany(
            """
            INSERT INTO element_relationships(
                element_id, target_id, target_name, target_type, relationship_type,
                direction, label, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            relationship_rows,
        )
        conn.executemany(
            "INSERT INTO specification_sections(element_id, section_name, section_order, section_json) VALUES (?, ?, ?, ?)",
            section_rows,
        )
        conn.executemany(
            """
            INSERT INTO specification_fields(
                element_id, section_name, field_name, field_order,
                value_text, target_id, target_name, value_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            field_rows,
        )

        permissions = payload.get("permissions") if isinstance(payload.get("permissions"), dict) else {}
        permission_attachment = permissions.get("permission_attachment") if isinstance(permissions.get("permission_attachment"), dict) else {}
        manifest = permission_attachment.get("manifest") if isinstance(permission_attachment.get("manifest"), dict) else {}
        manifest_entries = manifest.get("entries") if isinstance(manifest.get("entries"), list) else []
        conn.executemany(
            """
            INSERT INTO permissions(
                scope_id, scope_type, principal_id, principal_name, principal_type,
                role_name, action, application, inherited, accessible, editable,
                branch_admin_access, access_admin_access, via_groups_json,
                readonly_branch_ids_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    entry.get("scope_id") or entry.get("scopeId"),
                    entry.get("scope_type") or entry.get("scopeType"),
                    entry.get("principal_id") or entry.get("principalId"),
                    entry.get("principal_name") or entry.get("principalName"),
                    entry.get("principal_type") or entry.get("principalType"),
                    entry.get("role_name") or entry.get("roleName"),
                    entry.get("action"),
                    entry.get("application"),
                    1 if entry.get("inherited") else 0,
                    1 if entry.get("accessible") else 0,
                    1 if entry.get("editable") else 0,
                    1 if (entry.get("branch_admin_access") or entry.get("branchAdminAccess")) else 0,
                    1 if (entry.get("access_admin_access") or entry.get("accessAdminAccess")) else 0,
                    self._tableau_json(entry.get("via_groups") or entry.get("viaGroups") or []),
                    self._tableau_json(entry.get("readonly_branch_ids") or entry.get("readonlyBranchIds") or []),
                )
                for entry in manifest_entries
                if isinstance(entry, dict)
            ],
        )
        branch_access_records = permissions.get("branch_access_records") if isinstance(permissions.get("branch_access_records"), list) else []
        conn.executemany(
            """
            INSERT INTO branch_access(
                user_id, accessible, editable, admin_access, roles_json,
                via_groups_json, source, updated_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    record.get("user_id"),
                    1 if record.get("accessible") else 0,
                    1 if record.get("editable") else 0,
                    1 if record.get("admin_access") else 0,
                    self._tableau_json(record.get("roles") or []),
                    self._tableau_json(record.get("via_groups") or []),
                    record.get("source"),
                    record.get("updated_at"),
                    self._tableau_json(record.get("payload") or {}),
                )
                for record in branch_access_records
                if isinstance(record, dict)
            ],
        )

    def _collect_tableau_tree_rows(
        self,
        nodes: Any,
        rows: list[tuple[Any, ...]],
        *,
        parent_id: str | None,
        depth: int,
    ) -> None:
        if not isinstance(nodes, list):
            return
        for ordinal, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id") or "")
            rows.append(
                (
                    node_id,
                    parent_id,
                    depth,
                    ordinal,
                    node.get("label"),
                    node.get("node_type"),
                    node.get("path"),
                    self._tableau_json(node.get("metadata") or {}),
                )
            )
            self._collect_tableau_tree_rows(node.get("children") or [], rows, parent_id=node_id, depth=depth + 1)

    def _collect_tableau_spec_rows(
        self,
        element_id: str,
        details: dict[str, Any],
        section_rows: list[tuple[Any, ...]],
        field_rows: list[tuple[Any, ...]],
    ) -> None:
        metadata = details.get("metadata") if isinstance(details.get("metadata"), dict) else {}
        candidates = (
            metadata.get("specification_sections")
            or metadata.get("specificationSections")
            or metadata.get("sections")
            or details.get("specification_sections")
            or details.get("sections")
            or []
        )
        if isinstance(candidates, dict):
            candidates = [
                {"name": name, "fields": fields}
                for name, fields in candidates.items()
            ]
        if not isinstance(candidates, list):
            return
        for section_order, section in enumerate(candidates):
            if not isinstance(section, dict):
                section_rows.append((element_id, f"Section {section_order + 1}", section_order, self._tableau_json(section)))
                continue
            section_name = str(section.get("name") or section.get("label") or section.get("section") or f"Section {section_order + 1}")
            section_rows.append((element_id, section_name, section_order, self._tableau_json(section)))
            fields = section.get("fields") or section.get("properties") or section.get("rows") or []
            if isinstance(fields, dict):
                fields = [{"name": name, "value": value} for name, value in fields.items()]
            if not isinstance(fields, list):
                fields = [{"name": "Value", "value": fields}]
            for field_order, field in enumerate(fields):
                if isinstance(field, dict):
                    value = field.get("value")
                    target_id = field.get("target_id") or field.get("targetId") or field.get("id")
                    target_name = field.get("target_name") or field.get("targetName") or field.get("name")
                    field_name = field.get("name") or field.get("label") or field.get("property") or f"Field {field_order + 1}"
                else:
                    value = field
                    target_id = None
                    target_name = None
                    field_name = f"Field {field_order + 1}"
                field_rows.append(
                    (
                        element_id,
                        section_name,
                        str(field_name),
                        field_order,
                        self._tableau_field_value_text(value),
                        target_id,
                        target_name,
                        self._tableau_json(field),
                    )
                )

    def _tableau_field_value_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (str, int, float, bool)):
            return str(value)
        if isinstance(value, list):
            return ", ".join(self._tableau_field_value_text(item) for item in value)
        if isinstance(value, dict):
            for key in ("name", "label", "qualified_name", "qualifiedName", "id"):
                if value.get(key):
                    return str(value[key])
            return self._tableau_json(value)
        return str(value)

    def _project_dump_element_payload(
        self,
        element: CachedElementRecord,
        server_id: str,
        preferred_username: str,
        project_id: str,
        branch_id: str,
        *,
        include_raw_payload: bool,
        include_details: bool,
        include_all_workbench_admin: bool,
    ) -> dict[str, Any]:
        element_payload = element.model_dump(mode="json") if include_raw_payload else element.model_dump(mode="json", exclude={"payload"})
        if include_details:
            details = self._cached_item_details_for_user(
                server_id,
                preferred_username,
                project_id,
                branch_id,
                element.element_id,
                include_all_workbench_admin=include_all_workbench_admin,
            )
            element_payload["derived_item_details"] = details.model_dump(mode="json") if details is not None else None
        return element_payload

    def _resolve_cached_branch_id(self, server_id: str, project_id: str, branch_id_or_name: str) -> str:
        requested = (branch_id_or_name or "trunk").strip() or "trunk"
        if self.repo.get_branch_cache_summary(server_id, project_id, requested) is not None:
            return requested
        requested_key = normalize_lookup_key(requested)
        for summary in self.repo.list_branch_cache_summaries(server_id):
            if summary.project_id != project_id:
                continue
            branch_names = {
                normalize_lookup_key(summary.branch_id),
                normalize_lookup_key(summary.branch_name or ""),
            }
            if requested_key in branch_names:
                return summary.branch_id
        return requested

    @staticmethod
    def _workbench_agent_branch_key(value: str | None) -> str:
        key = normalize_lookup_key(value or "")
        return "trunk" if key == "master" else key

    def _workbench_agent_branch_matches(
        self,
        server_id: str,
        project_id: str,
        stored_branch_id: str | None,
        requested_branch_id: str,
    ) -> bool:
        if not stored_branch_id:
            return False
        stored_keys = {self._workbench_agent_branch_key(stored_branch_id)}
        requested_keys = {self._workbench_agent_branch_key(requested_branch_id)}
        for candidate in (stored_branch_id, requested_branch_id):
            resolved = self._resolve_cached_branch_id(server_id, project_id, candidate)
            requested_keys.add(self._workbench_agent_branch_key(resolved))
            stored_keys.add(self._workbench_agent_branch_key(resolved))
            summary = self.repo.get_branch_cache_summary(server_id, project_id, resolved)
            if summary is not None:
                stored_keys.add(self._workbench_agent_branch_key(summary.branch_id))
                stored_keys.add(self._workbench_agent_branch_key(summary.branch_name))
                requested_keys.add(self._workbench_agent_branch_key(summary.branch_id))
                requested_keys.add(self._workbench_agent_branch_key(summary.branch_name))
        return bool((stored_keys - {""}) & (requested_keys - {""}))

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
        include_all_workbench_admin: bool = False,
    ) -> CachedElementQueryResponse:
        self._require_server(server_id, include_disabled=True)
        user_id = self._user_key(preferred_username)
        if all_results:
            limit = max(self.repo.count_cached_elements_for_branch(server_id, project_id, branch_id), 1)
            offset = 0
        summary = self.repo.get_branch_cache_summary(server_id, project_id, branch_id)
        if include_all_workbench_admin:
            return self.repo.list_cached_elements(
                server_id,
                project_id,
                branch_id,
                model_id=model_id,
                search=search,
                limit=limit,
                offset=offset,
            )
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
        include_all_workbench_admin: bool = False,
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
            include_all_workbench_admin=include_all_workbench_admin,
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
                if (
                    detail := self._cached_item_details_for_user(
                        server_id,
                        preferred_username,
                        project_id,
                        branch_id,
                        element.element_id,
                        include_all_workbench_admin=include_all_workbench_admin,
                    )
                )
                is not None
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
        include_all_workbench_admin: bool = False,
    ) -> list[CachedElementRecord]:
        summary = self.repo.get_branch_cache_summary(server_id, project_id, branch_id)
        branch_total = max(self.repo.count_cached_elements_for_branch(server_id, project_id, branch_id), 1)
        if include_all_workbench_admin:
            # Read-only admin catalog path: return the full cached branch
            # contents for browsing/searching permission targets.
            return self.repo.list_cached_elements(
                server_id,
                project_id,
                branch_id,
                model_id=model_id,
                limit=branch_total,
                offset=0,
            ).items
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
        include_all_workbench_admin: bool = False,
    ) -> CacheTreeResponse:
        self._require_server(server_id, include_disabled=True)
        user_id = self._user_key(preferred_username)
        visible_models = self._visible_cached_models_for_user(
            user_id,
            server_id,
            project_id,
            branch_id,
            include_all_workbench_admin=include_all_workbench_admin,
        )
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
                        include_all_workbench_admin=include_all_workbench_admin,
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
        include_all_workbench_admin: bool = False,
    ) -> CacheChildrenResponse:
        self._require_server(server_id, include_disabled=True)
        user_id = self._user_key(preferred_username)
        if model_id:
            visible_models = [
                model
                for model in self._visible_cached_models_for_user(
                    user_id,
                    server_id,
                    project_id,
                    branch_id,
                    include_all_workbench_admin=include_all_workbench_admin,
                )
                if model.model_id == model_id
            ]
        else:
            visible_models = self._visible_cached_models_for_user(
                user_id,
                server_id,
                project_id,
                branch_id,
                include_all_workbench_admin=include_all_workbench_admin,
            )

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
        *,
        include_all_workbench_admin: bool = False,
    ) -> ItemDetails | None:
        self._require_server(server_id, include_disabled=True)
        return self._cached_item_details_for_user(
            server_id,
            preferred_username,
            project_id,
            branch_id,
            element_id,
            include_all_workbench_admin=include_all_workbench_admin,
        )

    def get_cached_branch_spec_diagnostic_for_user(
        self,
        server_id: str,
        preferred_username: str,
        project_id: str,
        branch_id: str,
        *,
        model_id: str | None = None,
        element_ids: list[str] | None = None,
        limit: int = 25,
        include_raw_payload: bool = True,
        include_details: bool = True,
        include_all_workbench_admin: bool = False,
    ) -> dict[str, Any]:
        """Return the factual mapping surface for Cameo-specification parity work.

        This is intentionally read-only and diagnostic. It places the raw plugin
        snapshot payload next to Workbench's derived ItemDetails so we can map
        Cameo specification pages from evidence instead of guessing in the UI.
        """
        self._require_server(server_id, include_disabled=True)
        user_id = self._user_key(preferred_username)
        summary = self.repo.get_branch_cache_summary(server_id, project_id, branch_id)
        if summary is None:
            raise ValueError("No cached branch snapshot exists for this project and branch.")

        visible_models = self._visible_cached_models_for_user(
            user_id,
            server_id,
            project_id,
            branch_id,
            include_all_workbench_admin=include_all_workbench_admin,
        )
        if model_id is not None:
            visible_models = [model for model in visible_models if model.model_id == model_id]
        visible_model_ids = {model.model_id for model in visible_models}
        if model_id is not None and not visible_model_ids:
            raise PermissionError("The active Workbench user cannot read that cached model.")

        requested_ids = [value.strip() for value in (element_ids or []) if value and value.strip()]
        elements: list[CachedElementRecord] = []
        missing_element_ids: list[str] = []
        if requested_ids:
            for element_id in requested_ids[: max(limit, 1)]:
                record = self.get_cached_branch_element_for_user(
                    server_id,
                    preferred_username,
                    project_id,
                    branch_id,
                    element_id,
                    model_id=model_id,
                    include_all_workbench_admin=include_all_workbench_admin,
                )
                if record is None:
                    missing_element_ids.append(element_id)
                    continue
                if model_id is None or record.model_id == model_id:
                    elements.append(record)
        else:
            elements = self.list_cached_branch_elements_for_user(
                server_id,
                preferred_username,
                project_id,
                branch_id,
                model_id=model_id,
                limit=max(limit, 1),
                offset=0,
                include_all_workbench_admin=include_all_workbench_admin,
            ).items

        total_elements = self.repo.count_cached_elements_for_branch(server_id, project_id, branch_id)
        adapter = create_adapter(self._require_server(server_id, include_disabled=True), {}, self.settings.resolved_data_dir)
        reference_keys: set[str] = set()
        attribute_keys: set[str] = set()
        spec_section_keys: set[str] = set()
        metaclasses: dict[str, int] = {}
        human_types: dict[str, int] = {}
        for record in self.repo.list_cached_elements(
            server_id,
            project_id,
            branch_id,
            model_id=model_id,
            limit=max(total_elements, 1),
            offset=0,
        ).items:
            if model_id is None and record.model_id not in visible_model_ids:
                continue
            payload = record.payload if isinstance(record.payload, dict) else {}
            for key in (payload.get("references") or {}).keys() if isinstance(payload.get("references"), dict) else []:
                reference_keys.add(str(key))
            for key in (payload.get("attributes") or {}).keys() if isinstance(payload.get("attributes"), dict) else []:
                attribute_keys.add(str(key))
            for key in (payload.get("spec_sections") or payload.get("specSections") or {}).keys() if isinstance(payload.get("spec_sections") or payload.get("specSections"), dict) else []:
                spec_section_keys.add(str(key))
            metaclass = str(payload.get("metaclass") or record.item_type or "").strip()
            if metaclass:
                metaclasses[metaclass] = metaclasses.get(metaclass, 0) + 1
            human_type = str(payload.get("human_type") or payload.get("humanType") or record.item_type or "").strip()
            if human_type:
                human_types[human_type] = human_types.get(human_type, 0) + 1

        return {
            "schema_version": "workbench-spec-diagnostic.v1",
            "purpose": "Map Cameo Specification window pages from raw plugin snapshot payloads and derived Workbench item details.",
            "server_id": server_id,
            "project_id": project_id,
            "branch_id": branch_id,
            "model_id": model_id,
            "requested_element_ids": requested_ids,
            "missing_element_ids": missing_element_ids,
            "selection": {
                "limit": limit,
                "returned_count": len(elements),
                "total_cached_branch_elements": total_elements,
                "include_raw_payload": include_raw_payload,
                "include_details": include_details,
                "admin_full_cache_view": include_all_workbench_admin,
            },
            "branch_summary": summary.model_dump(mode="json"),
            "models": [model.model_dump(mode="json") for model in visible_models],
            "payload_inventory": {
                "attribute_keys": sorted(attribute_keys, key=str.lower),
                "reference_keys": sorted(reference_keys, key=str.lower),
                "spec_section_keys": sorted(spec_section_keys, key=str.lower),
                "metaclasses": dict(sorted(metaclasses.items(), key=lambda item: (-item[1], item[0].lower()))),
                "human_types": dict(sorted(human_types.items(), key=lambda item: (-item[1], item[0].lower()))),
            },
            "cameo_spec_page_inputs": {
                "root_selected_element": ["payload identity fields", "payload.spec_sections.metamodel", "derived ItemDetails.metadata"],
                "Navigation/Hyperlinks": ["payload.spec_sections.navigation", "payload.attributes/reference keys matching navigation, hyperlink, link, url, uri, target"],
                "Documentation/Comments": ["payload.spec_sections.documentation", "payload.documentation", "payload.attributes.comment/ownedComment"],
                "Usage in Diagrams": ["payload.spec_sections.usageDiagrams", "payload.diagram_element_ids", "payload.references keys matching diagram, symbol, usage"],
                "Traceability": ["payload.spec_sections.traceability", "payload.references/attributes keys matching trace, satisfy, verify, refine, realize, specify"],
                "Relations": ["payload.spec_sections.relations", "payload.owner_id", "payload.owned_element_ids", "payload.references"],
                "Tags": ["payload.spec_sections.tags", "payload.spec_sections.stereotypes", "payload.applied_stereotype_ids", "payload.attributes/reference keys matching tag, stereotype, profile"],
                "Constraints": ["payload.spec_sections.constraints", "payload.attributes/reference keys matching constraint, guard, condition, rule, expression"],
                "Inner Elements": ["payload.spec_sections.innerElements", "payload.owned_element_ids", "payload.diagram_element_ids"],
                "Allocations": ["payload.spec_sections.allocations", "payload.attributes/reference keys matching allocation"],
            },
            "elements": [
                self._spec_diagnostic_element(
                    adapter,
                    server_id,
                    preferred_username,
                    project_id,
                    branch_id,
                    record,
                    include_raw_payload=include_raw_payload,
                    include_details=include_details,
                    include_all_workbench_admin=include_all_workbench_admin,
                )
                for record in elements
            ],
        }

    def get_cached_branch_owned_elements_for_user(
        self,
        server_id: str,
        preferred_username: str,
        project_id: str,
        branch_id: str,
        element_id: str,
        *,
        model_id: str | None = None,
        include_details: bool = True,
        include_raw_payload: bool = False,
        include_all_workbench_admin: bool = False,
    ) -> dict[str, Any]:
        """Return the elements listed under a selected element's Cameo Owned Element property."""
        self._require_server(server_id, include_disabled=True)
        summary = self.repo.get_branch_cache_summary(server_id, project_id, branch_id)
        if summary is None:
            raise ValueError("No cached branch snapshot exists for this project and branch.")

        parent_record = self.get_cached_branch_element_for_user(
            server_id,
            preferred_username,
            project_id,
            branch_id,
            element_id,
            model_id=model_id,
            include_all_workbench_admin=include_all_workbench_admin,
        )
        if parent_record is None:
            raise ValueError("Cached element not found or not visible to this Workbench user.")

        parent_payload = self._cached_element_payload(parent_record.payload)
        parent_details = self._cached_item_details_for_user(
            server_id,
            preferred_username,
            project_id,
            branch_id,
            parent_record.element_id,
            include_all_workbench_admin=include_all_workbench_admin,
        )

        owned_ids = self._owned_element_ids_from_payload(parent_payload)
        if parent_details is not None:
            owned_ids.extend(reference.id for reference in parent_details.contained_elements if reference.id)
        owned_ids = list(dict.fromkeys(value for value in owned_ids if value and value != parent_record.element_id))

        items: list[dict[str, Any]] = []
        unresolved_ids: list[str] = []
        for owned_id in owned_ids:
            owned_record = self.get_cached_branch_element_for_user(
                server_id,
                preferred_username,
                project_id,
                branch_id,
                owned_id,
                model_id=parent_record.model_id,
                include_all_workbench_admin=include_all_workbench_admin,
            )
            if owned_record is None and parent_record.model_id != model_id:
                owned_record = self.get_cached_branch_element_for_user(
                    server_id,
                    preferred_username,
                    project_id,
                    branch_id,
                    owned_id,
                    model_id=model_id,
                    include_all_workbench_admin=include_all_workbench_admin,
                )
            if owned_record is None:
                unresolved_ids.append(owned_id)
                continue
            entry: dict[str, Any] = {
                "record": owned_record.model_dump(mode="json", exclude={"payload"}),
            }
            if include_details:
                details = self._cached_item_details_for_user(
                    server_id,
                    preferred_username,
                    project_id,
                    branch_id,
                    owned_record.element_id,
                    include_all_workbench_admin=include_all_workbench_admin,
                )
                if details is not None:
                    entry["derived_item_details"] = details.model_dump(mode="json")
            if include_raw_payload:
                entry["raw_payload"] = self._cached_element_payload(owned_record.payload)
            items.append(entry)

        return {
            "schema_version": "workbench-owned-elements.v1",
            "server_id": server_id,
            "project_id": project_id,
            "branch_id": branch_id,
            "model_id": parent_record.model_id,
            "element_id": parent_record.element_id,
            "property": "Owned Element",
            "source_fields": [
                "payload.owned_element_ids",
                "payload.ownedElementIds",
                "payload.references.ownedElement",
                "payload.spec_sections.metamodel.entries[name=Owned Element]",
                "derived ItemDetails.contained_elements",
            ],
            "parent": parent_record.model_dump(mode="json", exclude={"payload"}),
            "owned_element_ids": owned_ids,
            "unresolved_element_ids": unresolved_ids,
            "total_owned_elements": len(items),
            "include_details": include_details,
            "include_raw_payload": include_raw_payload,
            "items": items,
        }

    def _owned_element_ids_from_payload(self, payload: dict[str, Any]) -> list[str]:
        ids: list[str] = []

        def add_values(value: Any) -> None:
            for candidate in self._element_ids_from_value(value):
                if candidate and candidate not in ids:
                    ids.append(candidate)

        add_values(payload.get("owned_element_ids"))
        add_values(payload.get("ownedElementIds"))

        references = payload.get("references") if isinstance(payload.get("references"), dict) else {}
        for key, value in references.items():
            if self._is_owned_element_property_name(str(key)):
                add_values(value)

        spec_sections = payload.get("spec_sections") or payload.get("specSections")
        if isinstance(spec_sections, dict):
            metamodel = spec_sections.get("metamodel")
            if isinstance(metamodel, dict) and isinstance(metamodel.get("entries"), list):
                for entry in metamodel["entries"]:
                    if not isinstance(entry, dict):
                        continue
                    entry_name = str(entry.get("name") or entry.get("id") or "")
                    if self._is_owned_element_property_name(entry_name):
                        add_values(entry.get("value"))
                        add_values(entry.get("defaultValue"))

        return ids

    @staticmethod
    def _is_owned_element_property_name(value: str) -> bool:
        normalized = normalize_lookup_key(value)
        return normalized in {"owned element", "ownedelement", "owned elements", "ownedelements"}

    def _element_ids_from_value(self, value: Any) -> list[str]:
        ids: list[str] = []
        if value is None:
            return ids
        if isinstance(value, str):
            cleaned = value.strip()
            return [cleaned] if cleaned else []
        if isinstance(value, (int, float, bool)):
            return []
        if isinstance(value, list) or isinstance(value, tuple):
            for entry in value:
                ids.extend(self._element_ids_from_value(entry))
            return ids
        if isinstance(value, dict):
            for key in ("id", "elementId", "element_id", "@id", "target", "value"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    ids.append(candidate.strip())
                elif isinstance(candidate, (list, tuple, dict)):
                    ids.extend(self._element_ids_from_value(candidate))
            return list(dict.fromkeys(ids))
        return ids

    def _spec_diagnostic_element(
        self,
        adapter: TeamworkAdapter,
        server_id: str,
        preferred_username: str,
        project_id: str,
        branch_id: str,
        record: CachedElementRecord,
        *,
        include_raw_payload: bool,
        include_details: bool,
        include_all_workbench_admin: bool,
    ) -> dict[str, Any]:
        payload = record.payload if isinstance(record.payload, dict) else {}
        attributes = payload.get("attributes") if isinstance(payload.get("attributes"), dict) else {}
        references = payload.get("references") if isinstance(payload.get("references"), dict) else {}
        spec_sections = payload.get("spec_sections") or payload.get("specSections")
        if not isinstance(spec_sections, dict):
            spec_sections = {}
        item_details = (
            self._cached_item_details_for_user(
                server_id,
                preferred_username,
                project_id,
                branch_id,
                record.element_id,
                include_all_workbench_admin=include_all_workbench_admin,
            )
            if include_details
            else None
        )
        diagnostic: dict[str, Any] = {
            "record": record.model_dump(mode="json", exclude={"payload"}),
            "payload_shape": {
                "top_level_keys": sorted(payload.keys(), key=str.lower),
                "attribute_keys": sorted(attributes.keys(), key=str.lower),
                "reference_keys": sorted(references.keys(), key=str.lower),
                "spec_section_keys": sorted(spec_sections.keys(), key=str.lower),
                "reference_resolution_ids": adapter.reference_resolution_ids(payload),
            },
            "containment_fields": {
                "owner_id": payload.get("owner_id") or payload.get("ownerId"),
                "owned_element_ids": payload.get("owned_element_ids") or payload.get("ownedElementIds") or [],
                "diagram_element_ids": payload.get("diagram_element_ids") or payload.get("diagramElementIds") or [],
                "applied_stereotype_ids": payload.get("applied_stereotype_ids") or payload.get("appliedStereotypeIds") or [],
            },
            "reference_counts": {
                key: len(value) if isinstance(value, list) else 1
                for key, value in sorted(references.items(), key=lambda item: str(item[0]).lower())
            },
            "spec_sections_summary": self._summarize_spec_sections(spec_sections),
        }
        if item_details is not None:
            diagnostic["derived_item_details"] = item_details.model_dump(mode="json")
        if include_raw_payload:
            diagnostic["raw_payload"] = payload
        return diagnostic

    def _summarize_spec_sections(self, spec_sections: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for section_name, section_payload in sorted(spec_sections.items(), key=lambda item: str(item[0]).lower()):
            if isinstance(section_payload, dict):
                entries = section_payload.get("entries")
                normalized_entries = entries if isinstance(entries, list) else []
                entry_keys: set[str] = set()
                for entry in normalized_entries:
                    if isinstance(entry, dict):
                        entry_keys.update(str(key) for key in entry.keys())
                summary[str(section_name)] = {
                    "kind": "object",
                    "keys": sorted(section_payload.keys(), key=str.lower),
                    "entry_count": len(normalized_entries),
                    "entry_keys": sorted(entry_keys, key=str.lower),
                }
            elif isinstance(section_payload, list):
                entry_keys: set[str] = set()
                nested_entry_count = 0
                for entry in section_payload:
                    if isinstance(entry, dict):
                        entry_keys.update(str(key) for key in entry.keys())
                        nested_entries = entry.get("entries")
                        if isinstance(nested_entries, list):
                            nested_entry_count += len(nested_entries)
                summary[str(section_name)] = {
                    "kind": "list",
                    "item_count": len(section_payload),
                    "nested_entry_count": nested_entry_count,
                    "item_keys": sorted(entry_keys, key=str.lower),
                }
            else:
                summary[str(section_name)] = {
                    "kind": type(section_payload).__name__,
                    "has_value": section_payload is not None,
                }
        return summary

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
        include_all_workbench_admin: bool = False,
    ) -> CacheElementSearchResponse:
        self._require_server(server_id, include_disabled=True)
        user_id = self._user_key(preferred_username)
        visible_elements = self._visible_cached_elements_for_user(
            user_id,
            server_id,
            project_id,
            branch_id,
            include_all_workbench_admin=include_all_workbench_admin,
        )
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
                if (
                    detail := self._cached_item_details_for_user(
                        server_id,
                        preferred_username,
                        project_id,
                        branch_id,
                        element.element_id,
                        include_all_workbench_admin=include_all_workbench_admin,
                    )
                )
                is not None
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
        *,
        include_all_workbench_admin: bool = False,
    ) -> CacheElementGraphResponse | None:
        self._require_server(server_id, include_disabled=True)
        item = self._cached_item_details_for_user(
            server_id,
            preferred_username,
            project_id,
            branch_id,
            element_id,
            include_all_workbench_admin=include_all_workbench_admin,
        )
        if item is None:
            return None

        user_id = self._user_key(preferred_username)
        visible_elements = self._visible_cached_elements_for_user(
            user_id,
            server_id,
            project_id,
            branch_id,
            include_all_workbench_admin=include_all_workbench_admin,
        )
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
        include_all_workbench_admin: bool = False,
    ) -> CachedElementRecord | None:
        self._require_server(server_id, include_disabled=True)
        user_id = self._user_key(preferred_username)
        summary = self.repo.get_branch_cache_summary(server_id, project_id, branch_id)
        if include_all_workbench_admin:
            # Admin catalog mode may resolve any cached element by id, but the
            # caller must still treat resulting details as non-editable unless
            # normal permission checks later say otherwise.
            if model_id is not None:
                return self.repo.get_cached_element(server_id, project_id, branch_id, element_id, model_id=model_id)
            for model in self.repo.list_cached_models(server_id, project_id, branch_id):
                match = self.repo.get_cached_element(server_id, project_id, branch_id, element_id, model_id=model.model_id)
                if match is not None:
                    return match
            return None
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
        *,
        include_all_workbench_admin: bool = False,
    ) -> ItemDetails | None:
        record = self.get_cached_branch_element_for_user(
            server_id,
            preferred_username,
            project_id,
            branch_id,
            element_id,
            include_all_workbench_admin=include_all_workbench_admin,
        )
        if record is None:
            return None
        record = self._canonical_cameo_visible_details_record(
            server_id,
            project_id,
            branch_id,
            record,
        )

        branch_access = self._branch_access_for_user(self._user_key(preferred_username), server_id, project_id, branch_id)
        editable = False
        summary = self.repo.get_branch_cache_summary(server_id, project_id, branch_id)
        if include_all_workbench_admin:
            editable = False
        elif self._is_plugin_managed_summary(summary):
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
        payload = self._cached_element_payload(record.payload)
        resolved_payloads: dict[str, Any] = {}
        for reference_id in adapter.reference_resolution_ids(payload):
            referenced_record = self.get_cached_branch_element_for_user(
                server_id,
                preferred_username,
                project_id,
                branch_id,
                reference_id,
                include_all_workbench_admin=include_all_workbench_admin,
            )
            if referenced_record is not None and isinstance(referenced_record.payload, dict):
                resolved_payloads[reference_id] = self._cached_element_payload(referenced_record.payload)
        for reference_id in self._second_hop_cameo_reference_ids(adapter, resolved_payloads):
            if reference_id in resolved_payloads:
                continue
            referenced_record = self.get_cached_branch_element_for_user(
                server_id,
                preferred_username,
                project_id,
                branch_id,
                reference_id,
                include_all_workbench_admin=include_all_workbench_admin,
            )
            if referenced_record is not None and isinstance(referenced_record.payload, dict):
                resolved_payloads[reference_id] = self._cached_element_payload(referenced_record.payload)
        item_details = adapter.build_item_details_from_payload(
            payload,
            record.element_id,
            project_id,
            branch_id,
            resolved_payloads=resolved_payloads,
            editable=editable,
            version=record.latest_revision or record.synced_at.isoformat(),
        )
        item_details = self._enrich_cameo_reference_labels(item_details, payload, resolved_payloads)
        return self._enrich_cameo_property_item_details(item_details, payload, resolved_payloads)

    @staticmethod
    def _cached_element_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        nested = payload.get("payload")
        if isinstance(nested, dict):
            return nested
        return payload

    def _second_hop_cameo_reference_ids(self, adapter: TeamworkAdapter, resolved_payloads: dict[str, Any]) -> list[str]:
        reference_ids: list[str] = []
        for payload in list(resolved_payloads.values())[:250]:
            if not isinstance(payload, dict):
                continue
            for reference_id in adapter.reference_resolution_ids(payload):
                if reference_id and reference_id not in resolved_payloads and reference_id not in reference_ids:
                    reference_ids.append(reference_id)
                if len(reference_ids) >= 250:
                    return reference_ids
        return reference_ids

    def _cameo_payload_display_name(self, payload: dict[str, Any] | None) -> str:
        if not isinstance(payload, dict):
            return ""
        attributes = payload.get("attributes") if isinstance(payload.get("attributes"), dict) else {}
        candidates = [
            attributes.get("name"),
            payload.get("human_name"),
            payload.get("humanName"),
            payload.get("name"),
            payload.get("qualified_name"),
            payload.get("qualifiedName"),
            payload.get("element_id"),
        ]
        return next((str(value).strip() for value in candidates if str(value or "").strip()), "")

    def _cameo_payload_path(self, payload: dict[str, Any] | None) -> str:
        if not isinstance(payload, dict):
            return ""
        return str(payload.get("qualified_name") or payload.get("qualifiedName") or payload.get("path") or "").replace("/", "::").strip()

    def _cameo_reference_values_from_payload(self, payload: dict[str, Any], resolved_payloads: dict[str, Any]) -> list[str]:
        values: list[str] = []
        attributes = payload.get("attributes") if isinstance(payload.get("attributes"), dict) else {}
        raw_attribute_value = attributes.get("value")
        raw_values = raw_attribute_value if isinstance(raw_attribute_value, list) else [raw_attribute_value] if raw_attribute_value is not None else []
        for value in raw_values:
            text = str(value).strip()
            if text:
                values.append(text)
        references = payload.get("references") if isinstance(payload.get("references"), dict) else {}
        reference_values = references.get("value")
        if not isinstance(reference_values, list):
            reference_values = [reference_values] if reference_values is not None else []
        for reference_id in reference_values:
            reference_key = str(reference_id or "").strip()
            if not reference_key:
                continue
            reference_payload = resolved_payloads.get(reference_key)
            value = self._cameo_payload_display_name(reference_payload) or self._cameo_payload_path(reference_payload) or reference_key
            if value:
                values.append(value)
        return list(dict.fromkeys(values))

    def _enrich_cameo_reference_labels(
        self,
        item: ItemDetails,
        payload: dict[str, Any],
        resolved_payloads: dict[str, Any],
    ) -> ItemDetails:
        labels: dict[str, str] = {}
        item_path = self._cameo_payload_path(payload) or item.path
        for reference_id, reference_payload in resolved_payloads.items():
            if not isinstance(reference_payload, dict):
                continue
            metaclass = normalize_lookup_key(str(reference_payload.get("metaclass") or reference_payload.get("human_type") or ""))
            if "taggedvalue" not in metaclass:
                continue
            references = reference_payload.get("references") if isinstance(reference_payload.get("references"), dict) else {}
            tag_definition_ids = references.get("tagDefinition") or references.get("tag_definition") or []
            if not isinstance(tag_definition_ids, list):
                tag_definition_ids = [tag_definition_ids]
            tag_definition_payload = next(
                (
                    resolved_payloads.get(str(tag_definition_id).strip())
                    for tag_definition_id in tag_definition_ids
                    if str(tag_definition_id or "").strip() in resolved_payloads
                ),
                None,
            )
            tag_name = self._cameo_payload_display_name(tag_definition_payload) or self._cameo_payload_display_name(reference_payload)
            tag_values = self._cameo_reference_values_from_payload(reference_payload, resolved_payloads)
            if not tag_name or not tag_values:
                continue
            value_text = ", ".join(tag_values)
            context = item_path or self._cameo_payload_path(reference_payload)
            label = f"{tag_name} = {value_text}"
            if context:
                label = f"{label} [{context}]"
            labels[reference_id] = label
        if not labels:
            return item
        return item.model_copy(update={"metadata": {**item.metadata, "cameo_reference_labels": labels}})

    def _resolved_payload_attribute_value(self, resolved_payloads: dict[str, Any], element_id: str, key: str) -> str:
        payload = resolved_payloads.get(element_id)
        if not isinstance(payload, dict):
            return ""
        attributes = payload.get("attributes")
        if not isinstance(attributes, dict):
            return ""
        value = attributes.get(key)
        return "" if value is None else str(value).strip()

    def _cameo_type_path_from_reference(self, reference: ItemReference | None) -> str:
        if reference is None:
            return ""
        return (reference.path or reference.name or "").replace("/", "::").strip()

    def _enrich_cameo_property_item_details(
        self,
        item: ItemDetails,
        payload: dict[str, Any],
        resolved_payloads: dict[str, Any],
    ) -> ItemDetails:
        metaclass = normalize_lookup_key(str(payload.get("metaclass") or item.item_type or ""))
        if metaclass not in {"property", "port"}:
            return item
        attributes = payload.get("attributes") if isinstance(payload.get("attributes"), dict) else {}
        references = payload.get("references") if isinstance(payload.get("references"), dict) else {}
        raw_name = str(attributes.get("name") or payload.get("name") or item.name).strip()
        display_name = raw_name or item.name
        type_reference = item.type_references[0] if item.type_references else None
        type_path = self._cameo_type_path_from_reference(type_reference)
        lower_id = next((str(value).strip() for value in references.get("lowerValue") or [] if str(value).strip()), "")
        upper_id = next((str(value).strip() for value in references.get("upperValue") or [] if str(value).strip()), "")
        lower_value = self._resolved_payload_attribute_value(resolved_payloads, lower_id, "value")
        upper_value = self._resolved_payload_attribute_value(resolved_payloads, upper_id, "value")
        multiplicity = ""
        if lower_value or upper_value:
            multiplicity = f"[{lower_value or '0'}]" if lower_value == upper_value or not upper_value else f"[{lower_value or '0'}..{upper_value}]"
        signature = display_name
        if type_path:
            signature = f"{signature} : {type_path}"
        if multiplicity:
            signature = f"{signature} {multiplicity}"
        next_metadata = {
            **item.metadata,
            "cameo_name": display_name,
            "cameo_signature": signature,
        }
        if type_path:
            next_metadata["cameo_type"] = type_path
        if multiplicity:
            next_metadata["multiplicity"] = multiplicity
        visibility = str(attributes.get("visibility") or "").strip()
        if visibility:
            next_metadata["visibility"] = visibility
        return item.model_copy(update={"metadata": next_metadata})

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
        *,
        model_id: str | None = None,
    ) -> ItemDetails | None:
        cached_record = self.get_cached_branch_element(session, project_id, branch_id, item_id, model_id=model_id)
        summary = self.repo.get_branch_cache_summary(session.server.id, project_id, branch_id)
        branch_access = self._branch_access_for_session(session, project_id, branch_id) if self._is_plugin_managed_summary(summary) else None
        admin_model_visibility = self._has_workbench_admin_model_visibility(session)
        editable = False
        if cached_record is None:
            cached_model = self.repo.get_cached_model(session.server.id, project_id, branch_id, item_id)
            if cached_model is None:
                return None
            if admin_model_visibility:
                # A Workbench admin can inspect catalog details for setup, but
                # catalog visibility alone must not enable branch/model edits.
                editable = False
            elif self._is_plugin_managed_summary(summary):
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

        if admin_model_visibility:
            editable = False
        elif self._is_plugin_managed_summary(summary):
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
        adapter = self._cache_payload_adapter(session.server.id)
        payload = self._cached_element_payload(cached_record.payload)
        resolved_payloads: dict[str, Any] = {}
        for reference_id in adapter.reference_resolution_ids(payload):
            referenced_record = self.get_cached_branch_element(session, project_id, branch_id, reference_id)
            if referenced_record is not None and isinstance(referenced_record.payload, dict):
                resolved_payloads[reference_id] = self._cached_element_payload(referenced_record.payload)
        for reference_id in self._second_hop_cameo_reference_ids(adapter, resolved_payloads):
            if reference_id in resolved_payloads:
                continue
            referenced_record = self.get_cached_branch_element(session, project_id, branch_id, reference_id)
            if referenced_record is not None and isinstance(referenced_record.payload, dict):
                resolved_payloads[reference_id] = self._cached_element_payload(referenced_record.payload)

        canonical_record = self._canonical_cameo_visible_details_record(
            session.server.id,
            project_id,
            branch_id,
            cached_record,
        )
        if canonical_record.element_id != cached_record.element_id:
            resolved_payloads = {}
            cached_record = canonical_record
            payload = self._cached_element_payload(cached_record.payload)
            for reference_id in adapter.reference_resolution_ids(payload):
                referenced_record = self.get_cached_branch_element(session, project_id, branch_id, reference_id)
                if referenced_record is not None and isinstance(referenced_record.payload, dict):
                    resolved_payloads[reference_id] = self._cached_element_payload(referenced_record.payload)
            for reference_id in self._second_hop_cameo_reference_ids(adapter, resolved_payloads):
                if reference_id in resolved_payloads:
                    continue
                referenced_record = self.get_cached_branch_element(session, project_id, branch_id, reference_id)
                if referenced_record is not None and isinstance(referenced_record.payload, dict):
                    resolved_payloads[reference_id] = self._cached_element_payload(referenced_record.payload)

        item_details = adapter.build_item_details_from_payload(
            payload,
            cached_record.element_id,
            project_id,
            branch_id,
            resolved_payloads=resolved_payloads,
            editable=editable,
            version=cached_record.latest_revision or cached_record.synced_at.isoformat(),
        )
        item_details = self._enrich_cameo_reference_labels(item_details, payload, resolved_payloads)
        return self._enrich_cameo_property_item_details(item_details, payload, resolved_payloads)

    def _materialized_model_item_details(
        self,
        session: SessionData,
        model: CachedModelRecord,
        project_id: str,
        branch_id: str,
        *,
        editable: bool,
    ) -> ItemDetails:
        adapter = self._cache_payload_adapter(session.server.id)
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

    def _cache_payload_adapter(self, server_id: str) -> TeamworkAdapter:
        adapter = object.__new__(TeamworkAdapter)
        adapter.context = SimpleNamespace(server=SimpleNamespace(id=server_id))
        return adapter

    def _accessible_cached_models(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
    ) -> list[CachedModelRecord]:
        summary = self.repo.get_branch_cache_summary(session.server.id, project_id, branch_id)
        if self._has_workbench_admin_model_visibility(session):
            return self.repo.list_cached_models(session.server.id, project_id, branch_id)
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
                    include_all_workbench_admin=self._has_workbench_admin_model_visibility(session),
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
            if field == "body":
                attributes = record.payload.get("attributes") if isinstance(record.payload.get("attributes"), dict) else {}
                return attributes.get("body") or record.payload.get("body") or default
            return record.payload.get(field, default)
        return record.get(field, default)

    def _cached_element_sort_key(self, record: CachedElementRecord | dict[str, Any] | None, fallback_id: str = "") -> tuple[int, int, str]:
        if record is None:
            return (99, 0, fallback_id.lower())
        item_type = str(self._tree_record_field(record, "item_type") or self._tree_record_field(record, "metaclass") or "element").strip().lower()
        raw_display_name = str(
            self._tree_record_field(record, "name")
            or self._tree_record_field(record, "element_id")
            or fallback_id
        ).strip()
        display_name = self._presentable_name_from_path(
            raw_display_name,
            qualified_name=str(self._tree_record_field(record, "qualified_name") or "").strip(),
            fallback_path=str(self._tree_record_field(record, "path") or "").strip(),
        ).strip().lower()
        if item_type == "comment":
            display_name = self._comment_tree_label_from_record(record).strip().lower() or display_name
        cameo_root_rank = {
            "auxiliary": 0,
            "imported packages": 1,
            "virtual dependencies": 2,
        }.get(display_name)
        if cameo_root_rank is not None and item_type == "package":
            rank = 0
            secondary_rank = cameo_root_rank
        elif item_type in {"package", "model"}:
            rank = 1
            secondary_rank = 0
        elif "diagram" in item_type or item_type in {"table", "matrix", "chart"}:
            rank = 2
            secondary_rank = 0 if display_name == "index" else 1 if display_name == "start" else 2
        elif item_type in {"block", "class", "requirement", "use case", "activity"}:
            rank = 3
            secondary_rank = 0
        else:
            rank = 4
            secondary_rank = 0
        element_id = str(self._tree_record_field(record, "element_id") or fallback_id).lower()
        return (rank, secondary_rank, display_name or element_id)

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
        normalized_path = path.replace("::", "/")
        return next((segment.strip() for segment in reversed(normalized_path.split("/")) if segment.strip()), "")

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
        raw_final_segment = self._final_named_segment(clean_label)
        if raw_final_segment and not self._looks_like_opaque_identifier(raw_final_segment):
            return raw_final_segment
        return clean_label

    def _plain_text_from_markup(self, value: str) -> str:
        text = value.strip()
        if not text:
            return ""
        text = re.sub(r"(?is)<(br|/p|/div|/li|/h[1-6])\b[^>]*>", "\n", text)
        text = re.sub(r"(?is)<style\b.*?</style>", " ", text)
        text = re.sub(r"(?is)<script\b.*?</script>", " ", text)
        text = re.sub(r"(?is)<[^>]+>", " ", text)
        text = html.unescape(text).replace("\xa0", " ")
        return re.sub(r"\s+", " ", text).strip()

    def _comment_tree_label_from_record(self, record: CachedElementRecord | dict[str, Any]) -> str:
        documentation = str(self._tree_record_field(record, "documentation") or "").strip()
        for candidate in (documentation, str(self._tree_record_field(record, "body") or "").strip()):
            text = self._plain_text_from_markup(candidate)
            if not text:
                continue
            for line in text.splitlines():
                cleaned = line.strip()
                if cleaned:
                    return cleaned[:96]
            return text[:96]
        return ""

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
        visible_child_ids = [
            child_id
            for child_id in child_ids
            if not self._is_property_multiplicity_value_child(
                server_id,
                project_id,
                branch_id,
                model_id,
                record,
                child_id,
            )
        ]
        child_count = len(visible_child_ids)
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
            comment_label = self._comment_tree_label_from_record(record)
            if comment_label:
                return comment_label
        normalized_metaclass = normalize_lookup_key(str(self._tree_record_field(record, "metaclass") or ""))
        if normalized_metaclass == "dependency":
            dependency_record = record
            if isinstance(record, dict) and "references" not in record:
                full_record = self.repo.get_cached_element(
                    server_id,
                    project_id,
                    branch_id,
                    str(record.get("element_id") or ""),
                    model_id=str(record.get("model_id") or "") or None,
                )
                if full_record is not None:
                    dependency_record = full_record
            dependency_signature = self._dependency_tree_signature(server_id, project_id, branch_id, dependency_record)
            if dependency_signature:
                return dependency_signature
        if normalized_metaclass in {"property", "port"}:
            property_signature = self._property_tree_signature(server_id, project_id, branch_id, record, raw_label)
            if property_signature:
                return property_signature
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

    def _tree_record_reference_values(self, record: CachedElementRecord | dict[str, Any], key: str) -> list[str]:
        references = self._tree_record_field(record, "references", {}) or {}
        if not isinstance(references, dict):
            return []
        return [str(value).strip() for value in references.get(key) or [] if str(value).strip()]

    def _tree_record_attribute_value(self, record: CachedElementRecord | dict[str, Any], key: str) -> str:
        attributes = self._tree_record_field(record, "attributes", {}) or {}
        if not isinstance(attributes, dict):
            return ""
        value = attributes.get(key)
        return "" if value is None else str(value).strip()

    def _tree_record_model_id(self, record: CachedElementRecord | dict[str, Any]) -> str:
        return str(self._tree_record_field(record, "model_id") or "").strip()

    def _is_value_spec_tree_record(self, record: CachedElementRecord | dict[str, Any] | None) -> bool:
        if record is None:
            return False
        metaclass = normalize_lookup_key(str(self._tree_record_field(record, "metaclass") or self._tree_record_field(record, "item_type") or ""))
        return metaclass in {
            "literalinteger",
            "literalunlimitednatural",
            "literalboolean",
            "literalstring",
            "literalreal",
            "literalnull",
        }

    def _is_property_multiplicity_value_child(
        self,
        server_id: str,
        project_id: str,
        branch_id: str,
        model_id: str,
        parent_record: CachedElementRecord | dict[str, Any],
        child_id: str,
        child_record: CachedElementRecord | dict[str, Any] | None = None,
    ) -> bool:
        parent_metaclass = normalize_lookup_key(str(self._tree_record_field(parent_record, "metaclass") or self._tree_record_field(parent_record, "item_type") or ""))
        if parent_metaclass != "property":
            return False
        multiplicity_ids = {
            *self._tree_record_reference_values(parent_record, "lowerValue"),
            *self._tree_record_reference_values(parent_record, "upperValue"),
            *self._tree_record_reference_values(parent_record, "defaultValue"),
        }
        if child_id not in multiplicity_ids:
            return False
        if child_record is None:
            child_record = self.repo.get_cached_element_tree_summary(
                server_id,
                project_id,
                branch_id,
                child_id,
                model_id=model_id or self._tree_record_model_id(parent_record) or None,
            )
        return self._is_value_spec_tree_record(child_record)

    def _tree_reference_record(
        self,
        server_id: str,
        project_id: str,
        branch_id: str,
        model_id: str,
        reference_id: str,
    ) -> CachedElementRecord | dict[str, Any] | None:
        if not reference_id:
            return None
        return self.repo.get_cached_element(
            server_id,
            project_id,
            branch_id,
            reference_id,
            model_id=model_id or None,
        ) or self.repo.get_cached_element_tree_summary(
            server_id,
            project_id,
            branch_id,
            reference_id,
            model_id=model_id or None,
        )

    def _canonical_cameo_visible_details_record(
        self,
        server_id: str,
        project_id: str,
        branch_id: str,
        record: CachedElementRecord,
    ) -> CachedElementRecord:
        if not self._is_value_spec_tree_record(record):
            return record
        owner_candidates = [
            *self._tree_record_reference_values(record, "owningLower"),
            *self._tree_record_reference_values(record, "owningUpper"),
            str(record.payload.get("owner_id") or "").strip(),
        ]
        for owner_id in owner_candidates:
            if not owner_id:
                continue
            owner_record = self.repo.get_cached_element(
                server_id,
                project_id,
                branch_id,
                owner_id,
                model_id=record.model_id,
            )
            if owner_record is None:
                continue
            owner_metaclass = normalize_lookup_key(str(owner_record.payload.get("metaclass") or owner_record.item_type or ""))
            if owner_metaclass == "property":
                references = owner_record.payload.get("references") if isinstance(owner_record.payload.get("references"), dict) else {}
                multiplicity_ids = {
                    *[str(value).strip() for value in references.get("lowerValue") or [] if str(value).strip()],
                    *[str(value).strip() for value in references.get("upperValue") or [] if str(value).strip()],
                    *[str(value).strip() for value in references.get("defaultValue") or [] if str(value).strip()],
                }
                if record.element_id in multiplicity_ids:
                    return owner_record
        return record

    def _tree_record_cameo_qualified_name(self, record: CachedElementRecord | dict[str, Any] | None) -> str:
        if record is None:
            return ""
        qualified_name = str(self._tree_record_field(record, "qualified_name") or self._tree_record_field(record, "path") or "").strip()
        if qualified_name:
            return qualified_name.replace("/", "::")
        return str(self._tree_record_field(record, "name") or "").strip()

    def _dependency_tree_signature(
        self,
        server_id: str,
        project_id: str,
        branch_id: str,
        record: CachedElementRecord | dict[str, Any],
    ) -> str:
        model_id = self._tree_record_model_id(record)

        def reference_names(reference_key: str) -> list[str]:
            names: list[str] = []
            for reference_id in self._tree_record_reference_values(record, reference_key):
                reference_record = self._tree_reference_record(server_id, project_id, branch_id, model_id, reference_id)
                names.append(self._tree_record_cameo_qualified_name(reference_record) or reference_id)
            return [name for name in names if name]

        clients = reference_names("client")
        suppliers = reference_names("supplier")
        if not clients and not suppliers:
            return ""
        return f"Dependency[{', '.join(clients) or 'client'} -> {', '.join(suppliers) or 'supplier'}]"

    def _property_tree_signature(
        self,
        server_id: str,
        project_id: str,
        branch_id: str,
        record: CachedElementRecord | dict[str, Any],
        raw_label: str,
    ) -> str:
        property_name = self._presentable_name_from_path(
            raw_label,
            qualified_name=str(self._tree_record_field(record, "qualified_name") or "").strip(),
            fallback_path=str(self._tree_record_field(record, "path") or "").strip(),
        ) or raw_label
        model_id = self._tree_record_model_id(record)
        type_id = next(iter(self._tree_record_reference_values(record, "type")), "")
        type_record = self._tree_reference_record(server_id, project_id, branch_id, model_id, type_id)
        type_name = self._tree_record_cameo_qualified_name(type_record)
        lower_id = next(iter(self._tree_record_reference_values(record, "lowerValue")), "")
        upper_id = next(iter(self._tree_record_reference_values(record, "upperValue")), "")
        lower_record = self._tree_reference_record(server_id, project_id, branch_id, model_id, lower_id)
        upper_record = self._tree_reference_record(server_id, project_id, branch_id, model_id, upper_id)
        lower_value = self._tree_record_attribute_value(lower_record, "value") if lower_record is not None else ""
        upper_value = self._tree_record_attribute_value(upper_record, "value") if upper_record is not None else ""
        multiplicity = ""
        if lower_value or upper_value:
            multiplicity = f"[{lower_value or '0'}]" if lower_value == upper_value or not upper_value else f"[{lower_value or '0'}..{upper_value}]"
        signature = property_name
        if type_name:
            signature = f"{signature} : {type_name}"
        if multiplicity:
            signature = f"{signature} {multiplicity}"
        return signature

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
        ordered_records = sorted(
            [records_by_id[root_id] for root_id in root_ids if root_id in records_by_id],
            key=lambda record: self._cached_element_sort_key(record, str(record.get("element_id") or "")),
        )
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

        ordered_records = [
            child_records[child_id]
            for child_id in owned_child_ids
            if child_id in child_records
            and not self._is_property_multiplicity_value_child(
                server_id,
                project_id,
                branch_id,
                model_id,
                parent_record,
                child_id,
                child_records.get(child_id),
            )
        ]
        extra_records = sorted(
            [
                record
                for child_id, record in child_records.items()
                if child_id not in owned_child_ids
                and not self._is_property_multiplicity_value_child(
                    server_id,
                    project_id,
                    branch_id,
                    model_id,
                    parent_record,
                    child_id,
                    record,
                )
            ],
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

        root_ids = sorted(
            self._sanitize_model_root_ids(model, model_records),
            key=lambda element_id: self._cached_element_sort_key(model_records.get(element_id), element_id),
        )

        detached_root_ids = [
            element_id
            for element_id, record in model_records.items()
            if element_id != model.model_id
            and element_id not in root_ids
            and str(record.payload.get("owner_id") or "").strip() not in model_records
            and not (
                self._is_modelish_record(record)
                and normalize_lookup_key(str(record.name or record.payload.get("human_name") or "")) == normalize_lookup_key(str(model.name or model.payload.get("human_name") or ""))
            )
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
        child_ids = [
            child_id
            for child_id in parent_to_children.get(record.element_id, [])
            if not self._is_property_multiplicity_value_child(
                server_id,
                project_id,
                branch_id,
                model_id,
                record,
                child_id,
                model_records.get(child_id),
            )
        ]
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
        child_nodes = self._group_cameo_relation_children(
            parent_id=record.element_id,
            parent_path=node_path,
            project_id=project_id,
            branch_id=branch_id,
            model_id=model_id,
            children=child_nodes,
        )
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
                "child_count": len(child_nodes),
                "qualified_name": qualified_name,
                "metaclass": metaclass,
                "stereotypes": stereotypes,
                "subtitle": subtitle,
            },
        )

    def _is_cameo_relation_tree_node(self, node: TreeNode) -> bool:
        node_type = normalize_lookup_key(node.node_type)
        metaclass = normalize_lookup_key(str(node.metadata.get("metaclass") or ""))
        return node_type in {"association", "associationclass", "dependency", "relationship"} or metaclass in {
            "association",
            "associationclass",
            "dependency",
            "relationship",
        }

    def _group_cameo_relation_children(
        self,
        *,
        parent_id: str,
        parent_path: str,
        project_id: str,
        branch_id: str,
        model_id: str,
        children: list[TreeNode],
        ) -> list[TreeNode]:
        relation_nodes = [child for child in children if self._is_cameo_relation_tree_node(child)]
        if not relation_nodes:
            return children
        normal_nodes = sorted(
            [child for child in children if not self._is_cameo_relation_tree_node(child)],
            key=self._cameo_tree_node_sort_key,
        )
        relations = TreeNode(
            id=f"{parent_id}::relations",
            label="Relations",
            node_type="group",
            path=f"{parent_path}/Relations",
            children=relation_nodes,
            metadata={
                "project_id": project_id,
                "branch_id": branch_id,
                "model_id": model_id,
                "child_count": len(relation_nodes),
                "synthetic": True,
                "cameo_virtual_folder": "relations",
                "subtitle": f"{len(relation_nodes)} relationships",
            },
        )
        return [relations, *normal_nodes]

    def _cameo_tree_node_sort_key(self, node: TreeNode) -> tuple[int, str, str]:
        node_type = normalize_lookup_key(node.node_type)
        metaclass = normalize_lookup_key(str(node.metadata.get("metaclass") or ""))
        short_label = str(node.label or "").split("::")[-1].strip().lower()
        if "diagram" in node_type or "diagram" in metaclass:
            rank = 0
        elif node_type in {"package", "model"} or metaclass in {"package", "model"}:
            rank = 1
        else:
            rank = 2
        return (rank, short_label, node.id.lower())

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
        covered: set[str] = {model.model_id}

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
                [element_id for element_id in model_records if element_id != model.model_id and element_id not in covered],
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
        if self._has_workbench_admin_model_visibility(session):
            accessible_models = models
        elif self._is_plugin_managed_summary(summary):
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
        model_id: str | None = None,
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
                materialized_item = await self._materialized_item_details(session, item_id, project_id, branch_id, model_id=model_id)
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

    def workbench_api_variable_catalog(self) -> dict[str, Any]:
        """Return the shared Workbench API variable cheat sheet used by docs, API Explorer, and agents."""
        return {
            "schema_version": "workbench-api-variable-catalog.v1",
            "base_url": {
                "name": "WORKBENCH_BASE_URL",
                "example": "http://localhost:8000",
                "description": "Root URL for the Workbench web/API process. API paths below are relative to this base URL.",
            },
            "authentication": [
                {
                    "name": "SESSION_COOKIE",
                    "where": "Cookie",
                    "required_for": "Browser/session-authenticated Workbench routes.",
                    "how_to_get": "Returned by /api/auth/local, /api/auth/token, or the TWC SSO callback and stored by the browser/client.",
                    "notes": "Read-only GET routes require a valid session. Mutating routes also require CSRF.",
                },
                {
                    "name": "X-CSRF-Token",
                    "where": "Header",
                    "required_for": "Session-authenticated POST, PUT, PATCH, and DELETE routes.",
                    "how_to_get": "Use csrf_token from /api/auth/session or the login response.",
                    "example": "X-CSRF-Token: <csrf_token>",
                },
                {
                    "name": "CACHE_API_BEARER_TOKEN",
                    "where": "Authorization header",
                    "required_for": "Scoped /api/cache/... automation routes.",
                    "how_to_get": "Workbench admin creates/reveals API keys in Settings.",
                    "example": "Authorization: Bearer <cache_api_key>",
                    "notes": "Cache API keys are not TWC passwords and should be scoped read/write/edit as narrowly as possible.",
                },
            ],
            "selectors": [
                {
                    "name": "serverId",
                    "aliases": ["server_id"],
                    "example": "localhost",
                    "source": "Settings > Servers, /api/servers, or /api/cache/servers.",
                    "description": "Workbench server profile id. Required by /api/cache/... paths; session routes infer it from the logged-in session.",
                },
                {
                    "name": "projectId",
                    "aliases": ["project_id", "resourceId"],
                    "example": "Property Based Requirements.mdzip",
                    "source": "/api/workspace/projects or /api/cache/servers/{serverId}/projects.",
                    "description": "Stored Workbench project id. For plugin snapshots this matches the project/resource key supplied by Cameo.",
                },
                {
                    "name": "branchId",
                    "aliases": ["branch_id"],
                    "example": "master",
                    "default": "trunk on dump/cache examples when omitted",
                    "source": "/api/workspace/projects/{projectId}/branches or cache branch lists.",
                    "description": "Stored branch id/name for the selected project. UI may display trunk even when the stored branch id is master; use the API value returned by branches.",
                },
                {
                    "name": "workspaceId",
                    "aliases": ["workspace_id"],
                    "example": "optional TWC workspace id",
                    "source": "Project/branch responses when the live TWC workspace context is available.",
                    "description": "Optional Teamwork Cloud workspace id. Cached/plugin-only reads usually do not need it.",
                },
                {
                    "name": "modelId",
                    "aliases": ["model_id"],
                    "example": "eee_1045467100313_135436_1",
                    "source": "Project dump, model cache model list, item source_payload.model_id.",
                    "description": "Cached model identifier. Use it to disambiguate duplicate element ids across models.",
                },
                {
                    "name": "itemId",
                    "aliases": ["elementId", "element_id"],
                    "example": "_19_0beta_8c4028a_1491999715291_646132_44227",
                    "source": "Containment tree node id, item details id, cache elements, or Cameo plugin snapshot.",
                    "description": "Model element id used by /api/workspace/items/{itemId} and element diagnostics.",
                },
            ],
            "common_query_flags": [
                {"name": "refresh", "type": "boolean", "default": False, "description": "Ask Workbench to refresh allowed live/cached state when supported. Avoid using repeatedly in tight loops."},
                {"name": "depth", "type": "integer", "default": None, "description": "Optional containment-tree depth limit. Omit for full accessible tree where supported."},
                {"name": "limit", "type": "integer", "default": 25, "description": "Maximum rows/elements to return for search or diagnostic endpoints."},
                {"name": "offset", "type": "integer", "default": 0, "description": "Pagination offset for list/search endpoints that support it."},
                {"name": "includeTree", "type": "boolean", "default": True, "description": "Project dump flag: include containment tree."},
                {"name": "includeElements", "type": "boolean", "default": True, "description": "Project dump flag: include cached element records."},
                {"name": "includeDetails", "type": "boolean", "default": True, "description": "Project dump/spec diagnostic flag: include derived Workbench ItemDetails."},
                {"name": "includeRawPayload", "type": "boolean", "default": True, "description": "Project dump/spec diagnostic flag: include raw Cameo/plugin payloads."},
                {"name": "includePermissions", "type": "boolean", "default": True, "description": "Project dump flag: include attached permission/access records visible to the caller."},
                {"name": "download", "type": "boolean", "default": False, "description": "Project dump flag: return JSON as an attachment with a generated filename."},
            ],
            "permission_terms": [
                {"name": "viewer", "description": "Can see a stored project/branch in Workbench."},
                {"name": "editor", "description": "Can update editable Workbench item fields where edit routes permit it."},
                {"name": "project_admin", "description": "Can manage Workbench-local access assignments for assigned project branches."},
                {"name": "workbench_admin", "description": "Can manage Workbench system settings. Has catalog visibility for stored models but does not automatically grant TWC project authority."},
                {"name": "group_manager", "description": "Can manage assigned Workbench groups only."},
            ],
            "common_endpoints": [
                {"method": "GET", "path": "/api/auth/session", "needs": ["SESSION_COOKIE"], "returns": ["csrf_token", "user", "server"]},
                {"method": "GET", "path": "/api/workspace/projects", "needs": ["SESSION_COOKIE"], "returns": ["projectId", "workspaceId"]},
                {"method": "GET", "path": "/api/workspace/projects/{projectId}/branches", "needs": ["SESSION_COOKIE", "projectId"], "returns": ["branchId"]},
                {"method": "GET", "path": "/api/workspace/tree?projectId={projectId}&branchId={branchId}", "needs": ["SESSION_COOKIE", "projectId", "branchId"], "returns": ["itemId", "modelId"]},
                {"method": "GET", "path": "/api/workspace/tree/children?projectId={projectId}&branchId={branchId}&parentId={itemId}", "needs": ["SESSION_COOKIE", "projectId", "branchId", "itemId"], "returns": ["child itemId values"]},
                {"method": "GET", "path": "/api/workspace/items/{itemId}?projectId={projectId}&branchId={branchId}", "needs": ["SESSION_COOKIE", "projectId", "branchId", "itemId"], "returns": ["ItemDetails"]},
                {"method": "GET", "path": "/api/workspace/model-cache/project-dump?projectId={projectId}&branchId={branchId}", "needs": ["SESSION_COOKIE", "projectId", "branchId"], "returns": ["full cached branch digest"]},
                {"method": "GET", "path": "/api/workspace/model-cache/owned-elements?projectId={projectId}&branchId={branchId}&elementId={itemId}", "needs": ["SESSION_COOKIE", "projectId", "branchId", "itemId"], "returns": ["Owned Element property expansion"]},
                {"method": "GET", "path": "/api/workspace/model-cache/spec-diagnostic?projectId={projectId}&branchId={branchId}&elementId={itemId}", "needs": ["SESSION_COOKIE", "projectId", "branchId"], "returns": ["raw payload and derived spec mapping facts"]},
                {"method": "GET", "path": "/api/workspace/api-variable-catalog", "needs": ["SESSION_COOKIE"], "returns": ["this catalog"]},
            ],
            "naming_rules": [
                "Workbench route query parameters use camelCase, for example projectId and branchId.",
                "Python/backend internal names usually use snake_case, for example project_id and branch_id.",
                "Teamwork Cloud RealSwagger often uses resourceId where Workbench UI/API examples say projectId.",
                "Cameo/plugin payloads may use element_id, local_id, @id, or id; Workbench item routes use the resolved itemId/elementId value.",
                "Never send passwords to Workbench API automation routes. Use sessions, CSRF, or scoped cache API bearer keys.",
            ],
        }

    def swagger_contract_manifest(self) -> SwaggerContractManifest:
        manifest = self.contract.manifest()
        workbench_operations = self._workbench_api_explorer_operations()
        if not workbench_operations:
            return manifest
        operations = [*manifest.operations, *workbench_operations]
        operation_counts = dict(manifest.operation_counts)
        tag_counts = dict(manifest.tag_counts)
        for operation in workbench_operations:
            operation_counts[operation.method] = operation_counts.get(operation.method, 0) + 1
            tag_counts[operation.tag] = tag_counts.get(operation.tag, 0) + 1
        return manifest.model_copy(
            update={
                "operations": operations,
                "operation_counts": dict(sorted(operation_counts.items())),
                "tag_counts": dict(sorted(tag_counts.items())),
                "warnings": [
                    *manifest.warnings,
                    "Workbench API operations are local Workbench endpoints, not Teamwork Cloud RealSwagger operations.",
                ],
            }
        )

    def _workbench_api_explorer_operations(self) -> list[SwaggerOperationSpec]:
        return [
            SwaggerOperationSpec(
                key=WORKBENCH_API_VARIABLE_CATALOG_OPERATION_KEY,
                method="GET",
                path="/api/workspace/api-variable-catalog",
                tag="Workbench API",
                tags=["Workbench API", "Developer Help"],
                operation_id=WORKBENCH_API_VARIABLE_CATALOG_OPERATION_KEY,
                summary="List Workbench API variables and calling conventions",
                description=(
                    "Workbench-only developer helper endpoint. Returns the common variables, selectors, headers, "
                    "query flags, permission terms, and endpoint patterns needed to script against Workbench."
                ),
                responses=[
                    SwaggerResponseSpec(status_code="200", description="Workbench API variable catalog.", content_types=["application/json"]),
                    SwaggerResponseSpec(status_code="401", description="Authentication is required.", content_types=["application/json"]),
                ],
                destructive=False,
            ),
            SwaggerOperationSpec(
                key=WORKBENCH_PROJECT_DUMP_OPERATION_KEY,
                method="GET",
                path="/api/workspace/model-cache/project-dump",
                tag="Workbench API",
                tags=["Workbench API", "Model Cache"],
                operation_id=WORKBENCH_PROJECT_DUMP_OPERATION_KEY,
                summary="Dump a full Workbench cached project branch",
                description=(
                    "Workbench-only one-call export for a stored project branch. Defaults branchId to trunk and returns "
                    "branch metadata, visible models, project usages, full containment tree, all visible cached elements, "
                    "optional derived ItemDetails, and attached permission records. Model content comes from Cameo plugin "
                    "snapshots; this does not call Teamwork Cloud REST."
                ),
                query_parameters=[
                    SwaggerParameterSpec(name="projectId", location="query", required=True, schema_type="string", description="Workbench cached project id."),
                    SwaggerParameterSpec(name="branchId", location="query", required=False, schema_type="string", default="trunk", description="Workbench cached branch id or branch name. Defaults to trunk."),
                    SwaggerParameterSpec(name="includeTree", location="query", required=False, schema_type="boolean", default=True, description="Include the full containment tree."),
                    SwaggerParameterSpec(name="includeElements", location="query", required=False, schema_type="boolean", default=True, description="Include every visible cached element record."),
                    SwaggerParameterSpec(name="includeDetails", location="query", required=False, schema_type="boolean", default=True, description="Include derived Workbench ItemDetails for each returned element."),
                    SwaggerParameterSpec(name="includeRawPayload", location="query", required=False, schema_type="boolean", default=True, description="Include raw plugin snapshot payloads on model and element records."),
                    SwaggerParameterSpec(name="includePermissions", location="query", required=False, schema_type="boolean", default=True, description="Include current user access, branch access records, and attached permission manifest when available."),
                ],
                responses=[
                    SwaggerResponseSpec(status_code="200", description="Full Workbench cached project branch dump.", content_types=["application/json"]),
                    SwaggerResponseSpec(status_code="403", description="The active Workbench user cannot read the requested cached branch.", content_types=["application/json"]),
                    SwaggerResponseSpec(status_code="404", description="No cached branch snapshot exists for the requested project and branch.", content_types=["application/json"]),
                ],
                destructive=False,
            ),
            SwaggerOperationSpec(
                key=WORKBENCH_OWNED_ELEMENTS_OPERATION_KEY,
                method="GET",
                path="/api/workspace/model-cache/owned-elements",
                tag="Workbench API",
                tags=["Workbench API", "Model Cache"],
                operation_id=WORKBENCH_OWNED_ELEMENTS_OPERATION_KEY,
                summary="Return elements under a selected element's Owned Element property",
                description=(
                    "Workbench-only cached model endpoint. Given a project, branch, and element id, returns the elements "
                    "listed under that element's Cameo Specification-window Owned Element property. This reads stored "
                    "plugin snapshot data and does not call Teamwork Cloud REST."
                ),
                query_parameters=[
                    SwaggerParameterSpec(name="projectId", location="query", required=True, schema_type="string", description="Workbench cached project id."),
                    SwaggerParameterSpec(name="branchId", location="query", required=True, schema_type="string", description="Workbench cached branch id."),
                    SwaggerParameterSpec(name="elementId", location="query", required=True, schema_type="string", description="Parent element id whose Owned Element property should be resolved."),
                    SwaggerParameterSpec(name="modelId", location="query", required=False, schema_type="string", description="Optional cached model id filter/disambiguator."),
                    SwaggerParameterSpec(name="includeDetails", location="query", required=False, schema_type="boolean", default=True, description="Include derived Workbench ItemDetails for each owned element."),
                    SwaggerParameterSpec(name="includeRawPayload", location="query", required=False, schema_type="boolean", default=False, description="Include raw plugin snapshot payloads for each owned element."),
                ],
                responses=[
                    SwaggerResponseSpec(status_code="200", description="Owned Element property expansion.", content_types=["application/json"]),
                    SwaggerResponseSpec(status_code="403", description="The active Workbench user cannot read the requested cached branch/model.", content_types=["application/json"]),
                    SwaggerResponseSpec(status_code="404", description="No cached branch snapshot or visible parent element exists for the request.", content_types=["application/json"]),
                ],
                destructive=False,
            ),
            SwaggerOperationSpec(
                key=WORKBENCH_SPEC_DIAGNOSTIC_OPERATION_KEY,
                method="GET",
                path="/api/workspace/model-cache/spec-diagnostic",
                tag="Workbench API",
                tags=["Workbench API", "Model Cache"],
                operation_id=WORKBENCH_SPEC_DIAGNOSTIC_OPERATION_KEY,
                summary="Export Workbench spec diagnostic mapping payload",
                description=(
                    "Workbench-only diagnostic endpoint. Reads the stored/plugin model cache and returns branch summary, "
                    "model inventory, raw snapshot payloads, spec_sections summaries, and derived ItemDetails so Cameo "
                    "Specification-window pages can be mapped from facts. This does not call Teamwork Cloud."
                ),
                query_parameters=[
                    SwaggerParameterSpec(name="projectId", location="query", required=True, schema_type="string", description="Workbench cached project id."),
                    SwaggerParameterSpec(name="branchId", location="query", required=True, schema_type="string", description="Workbench cached branch id."),
                    SwaggerParameterSpec(name="modelId", location="query", required=False, schema_type="string", description="Optional cached model id filter."),
                    SwaggerParameterSpec(name="elementId", location="query", required=False, schema_type="array", description="Optional element id. Repeat this query parameter for multiple exact elements."),
                    SwaggerParameterSpec(name="limit", location="query", required=False, schema_type="integer", default=25, description="Maximum elements returned when elementId is omitted. Range: 1-1000."),
                    SwaggerParameterSpec(name="includeRawPayload", location="query", required=False, schema_type="boolean", default=True, description="Include raw plugin snapshot payloads."),
                    SwaggerParameterSpec(name="includeDetails", location="query", required=False, schema_type="boolean", default=True, description="Include Workbench derived ItemDetails beside raw payloads."),
                ],
                responses=[
                    SwaggerResponseSpec(status_code="200", description="Workbench spec diagnostic mapping payload.", content_types=["application/json"]),
                    SwaggerResponseSpec(status_code="403", description="The active Workbench user cannot read the requested cached branch/model.", content_types=["application/json"]),
                    SwaggerResponseSpec(status_code="404", description="No cached branch snapshot exists for the requested project and branch.", content_types=["application/json"]),
                ],
                destructive=False,
            )
        ]

    async def execute_swagger_operation(self, session: SessionData, payload: SwaggerExecuteRequest) -> SwaggerExecuteResponse:
        if payload.operation_key == WORKBENCH_API_VARIABLE_CATALOG_OPERATION_KEY:
            return self._execute_workbench_api_variable_catalog_operation(payload)
        if payload.operation_key == WORKBENCH_PROJECT_DUMP_OPERATION_KEY:
            return self._execute_workbench_project_dump_operation(session, payload)
        if payload.operation_key == WORKBENCH_OWNED_ELEMENTS_OPERATION_KEY:
            return self._execute_workbench_owned_elements_operation(session, payload)
        if payload.operation_key == WORKBENCH_SPEC_DIAGNOSTIC_OPERATION_KEY:
            return self._execute_workbench_spec_diagnostic_operation(session, payload)
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

    def _execute_workbench_api_variable_catalog_operation(self, payload: SwaggerExecuteRequest) -> SwaggerExecuteResponse:
        catalog = self.workbench_api_variable_catalog()
        content = json.dumps(catalog, default=str).encode("utf-8")
        return SwaggerExecuteResponse(
            operation_key=payload.operation_key,
            method="GET",
            path="/api/workspace/api-variable-catalog",
            requested_path="/api/workspace/api-variable-catalog",
            status_code=200,
            ok=True,
            content_type="application/json",
            headers={"content-type": "application/json"},
            body=catalog,
            text=None,
            body_base64=None,
            is_binary=False,
            size_bytes=len(content),
        )

    def _execute_workbench_project_dump_operation(self, session: SessionData, payload: SwaggerExecuteRequest) -> SwaggerExecuteResponse:
        query_params = payload.query_params or {}
        project_id = str(query_params.get("projectId") or "").strip()
        if not project_id:
            raise ValueError("Missing required query parameter: projectId")
        project_dump = self.get_cached_project_branch_dump_for_user(
            session.server.id,
            session.user.preferred_username,
            project_id,
            str(query_params.get("branchId") or "trunk").strip() or "trunk",
            include_tree=_truthy_query_value(query_params.get("includeTree"), default=True),
            include_elements=_truthy_query_value(query_params.get("includeElements"), default=True),
            include_details=_truthy_query_value(query_params.get("includeDetails"), default=True),
            include_raw_payload=_truthy_query_value(query_params.get("includeRawPayload"), default=True),
            include_permissions=_truthy_query_value(query_params.get("includePermissions"), default=True),
            include_all_workbench_admin=self.can_manage_server_presets(session),
        )
        requested_path = self._workbench_project_dump_requested_path(query_params)
        content = json.dumps(project_dump, default=str).encode("utf-8")
        return SwaggerExecuteResponse(
            operation_key=payload.operation_key,
            method="GET",
            path="/api/workspace/model-cache/project-dump",
            requested_path=requested_path,
            status_code=200,
            ok=True,
            content_type="application/json",
            headers={"content-type": "application/json"},
            body=project_dump,
            text=None,
            body_base64=None,
            is_binary=False,
            size_bytes=len(content),
        )

    def _workbench_project_dump_requested_path(self, query_params: dict[str, Any]) -> str:
        query_items: list[tuple[str, str]] = []
        for key in ("projectId", "branchId", "includeTree", "includeElements", "includeDetails", "includeRawPayload", "includePermissions"):
            value = query_params.get(key)
            if value in (None, "", [], {}):
                continue
            if isinstance(value, list):
                query_items.extend((key, str(item)) for item in value if item not in (None, ""))
            else:
                query_items.append((key, str(value)))
        suffix = f"?{urlencode(query_items, doseq=True)}" if query_items else ""
        return f"/api/workspace/model-cache/project-dump{suffix}"

    def _execute_workbench_owned_elements_operation(self, session: SessionData, payload: SwaggerExecuteRequest) -> SwaggerExecuteResponse:
        query_params = payload.query_params or {}
        project_id = str(query_params.get("projectId") or "").strip()
        branch_id = str(query_params.get("branchId") or "").strip()
        element_id = str(query_params.get("elementId") or "").strip()
        if not project_id:
            raise ValueError("Missing required query parameter: projectId")
        if not branch_id:
            raise ValueError("Missing required query parameter: branchId")
        if not element_id:
            raise ValueError("Missing required query parameter: elementId")
        owned_elements = self.get_cached_branch_owned_elements_for_user(
            session.server.id,
            session.user.preferred_username,
            project_id,
            branch_id,
            element_id,
            model_id=str(query_params.get("modelId") or "").strip() or None,
            include_details=_truthy_query_value(query_params.get("includeDetails"), default=True),
            include_raw_payload=_truthy_query_value(query_params.get("includeRawPayload"), default=False),
            include_all_workbench_admin=self.can_manage_server_presets(session),
        )
        requested_path = self._workbench_owned_elements_requested_path(query_params)
        content = json.dumps(owned_elements, default=str).encode("utf-8")
        return SwaggerExecuteResponse(
            operation_key=payload.operation_key,
            method="GET",
            path="/api/workspace/model-cache/owned-elements",
            requested_path=requested_path,
            status_code=200,
            ok=True,
            content_type="application/json",
            headers={"content-type": "application/json"},
            body=owned_elements,
            text=None,
            body_base64=None,
            is_binary=False,
            size_bytes=len(content),
        )

    def _workbench_owned_elements_requested_path(self, query_params: dict[str, Any]) -> str:
        query_items: list[tuple[str, str]] = []
        for key in ("projectId", "branchId", "elementId", "modelId", "includeDetails", "includeRawPayload"):
            value = query_params.get(key)
            if value in (None, "", [], {}):
                continue
            query_items.append((key, str(value)))
        suffix = f"?{urlencode(query_items)}" if query_items else ""
        return f"/api/workspace/model-cache/owned-elements{suffix}"

    def _execute_workbench_spec_diagnostic_operation(self, session: SessionData, payload: SwaggerExecuteRequest) -> SwaggerExecuteResponse:
        query_params = payload.query_params or {}
        project_id = str(query_params.get("projectId") or "").strip()
        branch_id = str(query_params.get("branchId") or "").strip()
        if not project_id:
            raise ValueError("Missing required query parameter: projectId")
        if not branch_id:
            raise ValueError("Missing required query parameter: branchId")
        raw_element_ids = query_params.get("elementId")
        element_ids = [str(value).strip() for value in _as_list(raw_element_ids) if str(value).strip()]
        limit = int(query_params.get("limit") or 25)
        include_raw_payload = _truthy_query_value(query_params.get("includeRawPayload"), default=True)
        include_details = _truthy_query_value(query_params.get("includeDetails"), default=True)
        diagnostic = self.get_cached_branch_spec_diagnostic_for_user(
            session.server.id,
            session.user.preferred_username,
            project_id,
            branch_id,
            model_id=str(query_params.get("modelId") or "").strip() or None,
            element_ids=element_ids,
            limit=limit,
            include_raw_payload=include_raw_payload,
            include_details=include_details,
            include_all_workbench_admin=self.can_manage_server_presets(session),
        )
        requested_path = self._workbench_spec_diagnostic_requested_path(query_params)
        content = json.dumps(diagnostic, default=str).encode("utf-8")
        return SwaggerExecuteResponse(
            operation_key=payload.operation_key,
            method="GET",
            path="/api/workspace/model-cache/spec-diagnostic",
            requested_path=requested_path,
            status_code=200,
            ok=True,
            content_type="application/json",
            headers={"content-type": "application/json"},
            body=diagnostic,
            text=None,
            body_base64=None,
            is_binary=False,
            size_bytes=len(content),
        )

    def _workbench_spec_diagnostic_requested_path(self, query_params: dict[str, Any]) -> str:
        query_items: list[tuple[str, str]] = []
        for key in ("projectId", "branchId", "modelId", "elementId", "limit", "includeRawPayload", "includeDetails"):
            value = query_params.get(key)
            if value in (None, "", [], {}):
                continue
            if isinstance(value, list):
                query_items.extend((key, str(item)) for item in value if item not in (None, ""))
            else:
                query_items.append((key, str(value)))
        suffix = f"?{urlencode(query_items, doseq=True)}" if query_items else ""
        return f"/api/workspace/model-cache/spec-diagnostic{suffix}"

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

    def server_permission_inventory_details(self, session: SessionData) -> ServerPermissionInventoryDetails:
        inventory = self.repo.get_server_permission_inventory(session.server.id)
        if not inventory:
            return ServerPermissionInventoryDetails(server_id=session.server.id)
        return ServerPermissionInventoryDetails(
            server_id=inventory.server_id,
            roles=inventory.roles,
            groups=inventory.groups,
            captured_at=inventory.captured_at,
            dirty=inventory.dirty,
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
                await context.report(45, "Resolving every role and group against imported projects")
                attachment_counts = await self._refresh_plugin_permission_attachments(
                    live_session,
                    self._adapter_for_session(live_session),
                    inventory,
                    report=context.report,
                )
                self.sessions.mark_server_permission_snapshots_due(live_session.server.id)
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
                await context.report(95, "Project permission attachments replaced; user permission snapshots marked due")
                return {
                    "server_id": live_session.server.id,
                    "captured_at": inventory.captured_at.isoformat(),
                    "role_count": len(inventory.roles),
                    "group_count": len(inventory.groups),
                    **attachment_counts,
                    "affected_user_count": len({
                        self._user_key(item.user.preferred_username)
                        for item in self.sessions.list_active_sessions()
                        if item.server.id == live_session.server.id
                    }),
                    "reason": reason,
                }
            except Exception as exc:
                self.repo.mark_server_permission_inventory_dirty(live_session.server.id)
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
        admin_model_visibility = self._has_workbench_admin_model_visibility(session)
        plugin_managed = self._is_plugin_managed_summary(summary)
        if admin_model_visibility and summary is not None:
            model_exists = (
                self.repo.get_cached_model(server_id, project_id, branch_id, model_id) is not None
                if model_id
                else None
            )
            return CurrentPermissionStatus(
                project_id=project_id,
                branch_id=branch_id,
                model_id=model_id,
                project_accessible=True,
                branch_accessible=True,
                branch_editable=False,
                branch_admin_access=True,
                model_accessible=model_exists,
                model_editable=False if model_id else None,
                snapshot_updated_at=summary.updated_at,
            )
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
        if session.user.auth_source == "workbench-local":
            raise RuntimeError(
                "This Workbench username/password session has no delegated TWC credentials. Use cached/plugin-backed project data or sign in with TWC for live TWC API actions."
            )
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
            readonly_project_ids: list[str] = []
            for project_id in sorted({summary.project_id for summary in summaries}):
                project_summaries = [summary for summary in summaries if summary.project_id == project_id]
                has_current_attachments = all(
                    self._attached_rest_manifest_is_current(
                        summary,
                        self.repo.get_branch_permission_attachment(
                            session.server.id,
                            summary.project_id,
                            summary.branch_id,
                        ),
                        permission_inventory,
                    )
                    for summary in project_summaries
                )
                if has_current_attachments:
                    continue
                if (
                    not session.authorization_context.permissions_included
                    or any(
                        self._session_resource_permission_flags(
                            session,
                            summary.project_id,
                            summary.workspace_id,
                        )["editable"]
                        for summary in project_summaries
                    )
                ):
                    readonly_project_ids.append(project_id)
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
            logger.info(
                "twc-server-permission-inventory-refreshed",
                server_id=server_id,
                role_count=len(roles),
                group_count=len(groups),
                refresh_hours=self.settings.permission_inventory_refresh_hours,
            )
            return inventory

    async def _refresh_plugin_permission_attachments(
        self,
        session: SessionData,
        adapter,
        inventory: ServerPermissionInventory,
        *,
        report=None,
    ) -> dict[str, int]:
        """Resolve complete TWC role/group access once per imported project.

        The resulting user-specific records are copied to each locally imported
        branch and stored as revision-bound permission attachments. User login
        refreshes can therefore compare against local authoritative evidence
        without repeating the server-wide role/group expansion.
        """
        summaries = [
            summary
            for summary in self.repo.list_branch_cache_summaries(session.server.id)
            if self._is_plugin_managed_summary(summary)
        ]
        projects: dict[str, list[BranchCacheSummary]] = {}
        for summary in summaries:
            projects.setdefault(summary.project_id, []).append(summary)

        captured_at = utcnow()
        attached_branch_count = 0
        resolved_user_ids: set[str] = set()
        ordered_projects = sorted(projects.items(), key=lambda item: item[0].lower())
        for index, (project_id, project_summaries) in enumerate(ordered_projects, start=1):
            project_summaries.sort(key=lambda item: (item.branch_name.lower(), item.branch_id.lower()))
            representative = project_summaries[0]
            if report is not None:
                progress = 45 + int(40 * (index - 1) / max(1, len(ordered_projects)))
                await report(
                    progress,
                    f"Resolving roles and groups for imported project {index} of {len(ordered_projects)}",
                )
            project_records = await adapter.build_plugin_branch_access_manifest(
                project_id,
                representative.branch_id,
                latest_revision=representative.latest_revision,
                workspace_id=representative.workspace_id,
                admin_roles_inventory=inventory.roles,
                usergroups_inventory=inventory.groups,
            )
            resolved_user_ids.update(self._user_key(record.user_id) for record in project_records)

            for summary in project_summaries:
                branch_records: list[BranchAccessRecord] = []
                for record in project_records:
                    payload = dict(record.payload or {})
                    readonly_branch_ids = list(dict.fromkeys(payload.get("readonly_branch_ids", [])))
                    branch_read_only = summary.branch_id in readonly_branch_ids
                    accessible = bool(record.accessible)
                    role_editable = bool(payload.get("role_editable_access", record.editable))
                    branch_admin = bool(payload.get("branch_admin_access", False)) and not branch_read_only
                    access_admin = bool(payload.get("access_admin_access", False))
                    payload.update(
                        {
                            "readonly_branch_ids": readonly_branch_ids,
                            "branch_read_only": branch_read_only,
                            "role_editable_access": role_editable,
                            "branch_admin_access": branch_admin,
                            "access_admin_access": access_admin,
                        }
                    )
                    branch_records.append(
                        record.model_copy(
                            update={
                                "server_id": session.server.id,
                                "project_id": summary.project_id,
                                "branch_id": summary.branch_id,
                                "workspace_id": summary.workspace_id,
                                "branch_name": summary.branch_name or summary.branch_id,
                                "latest_revision": summary.latest_revision,
                                "accessible": accessible,
                                "editable": bool(accessible and role_editable and not branch_read_only),
                                "admin_access": bool(accessible and (branch_admin or access_admin)),
                                "payload": payload,
                                "updated_at": captured_at,
                            }
                        )
                    )
                previous_attachment = self.repo.get_branch_permission_attachment(
                    session.server.id,
                    summary.project_id,
                    summary.branch_id,
                )
                attachment = self._permission_attachment_from_rest_manifest(
                    session,
                    summary,
                    branch_records,
                    captured_at,
                    previous_attachment,
                )
                self.repo.upsert_branch_permission_attachment(attachment)
                attached_branch_count += 1

        return {
            "permission_project_count": len(projects),
            "permission_branch_count": attached_branch_count,
            "permission_user_count": len(resolved_user_ids),
        }

    def _permission_candidate_summaries(
        self,
        session: SessionData,
        summaries: list[BranchCacheSummary],
    ) -> list[BranchCacheSummary]:
        # REST-created model caches are legacy partial data. Only branches
        # published by the Cameo plugin participate in user visibility and
        # permission refresh.
        summaries = [summary for summary in summaries if self._is_plugin_managed_summary(summary)]
        # The TWC current-user payload is not a complete project filter: access
        # can arrive through scoped roles, server groups, and nested groups that
        # are absent from that response. Resolve every imported project against
        # its saved permission attachment, then store only this user's matches.
        return summaries

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
        manifest_accessible = bool(manifest_user_access and manifest_user_access.accessible)
        accessible = bool(
            direct_accessible
            or permission_claim_access["accessible"]
            or manifest_accessible
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
        manifest_editable = bool(manifest_user_access and manifest_user_access.editable)
        manifest_branch_admin = self._branch_admin_access(manifest_user_access)
        manifest_access_admin = self._access_admin_access(manifest_user_access)
        editable = bool(
            accessible
            and not branch_read_only
            and (
                direct_editable
                or permission_claim_access["editable"]
                or manifest_editable
            )
        )
        branch_admin = bool(
            accessible
            and not branch_read_only
            and (permission_claim_access["branch_admin_access"] or manifest_branch_admin)
        )
        access_admin = bool(
            accessible
            and (permission_claim_access["access_admin_access"] or manifest_access_admin)
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
            branch_admin=branch_admin,
            access_admin=access_admin,
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
                        "manifest_branch_admin_access": manifest_branch_admin,
                        "manifest_access_admin_access": manifest_access_admin,
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
                    branch_admin
                    or access_admin
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
                "branch_admin_access": branch_admin,
                "access_admin_access": access_admin,
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
        operation_names: set[str] = set()
        permission_names: set[str] = set()
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
            if claim.operation_name:
                operation_names.add(claim.operation_name.strip().lower())
            if claim.name:
                permission_names.add(claim.name.strip().lower())
            matched_permissions.append(claim.model_dump())

        def has_permission(*names: str) -> bool:
            return any(name in term for term in matched_terms for name in names)

        has_read = bool(
            "read.resource" in operation_names
            or "com.nomagic.esi.resource_read.resource" in permission_names
            or has_permission("read resources", "read resource", "read projects", "list all resources")
        )
        has_edit = bool(
            "edit.resource" in operation_names
            or "com.nomagic.esi.resource_edit.resource" in permission_names
            or has_permission("edit resources", "edit projects")
        )
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
        # Security boundary: publishing a plugin snapshot is not an enduring
        # authorization grant. Access must come from the latest stored TWC
        # permission snapshot or an explicit Workbench admin assignment so a
        # later revoke cannot be bypassed by being the original source user.
        return None

    def _branch_access_for_session(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
    ) -> BranchAccessRecord | None:
        summary = self.repo.get_branch_cache_summary(session.server.id, project_id, branch_id)
        if self._has_workbench_admin_model_visibility(session) and summary is not None:
            return BranchAccessRecord(
                user_id=self._user_key(session.user.preferred_username),
                server_id=session.server.id,
                project_id=project_id,
                branch_id=branch_id,
                workspace_id=summary.workspace_id,
                branch_name=summary.branch_name or branch_id,
                latest_revision=summary.latest_revision,
                accessible=True,
                editable=False,
                admin_access=True,
                roles=["Workbench Administrator"],
                source="workbench-admin-cache-visibility",
                payload={
                    "workbench_admin_cache_visibility": True,
                    "branch_admin_access": False,
                    "access_admin_access": False,
                    "live_twc_permission": False,
                },
                updated_at=summary.updated_at,
            )
        return self._plugin_branch_access_or_source_fallback(
            self._user_key(session.user.preferred_username),
            session.server.id,
            project_id,
            branch_id,
            summary,
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
        if self._has_workbench_admin_model_visibility(session) and summary is not None:
            return True
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
        *,
        include_all_workbench_admin: bool = False,
    ) -> list[CachedModelRecord]:
        summary = self.repo.get_branch_cache_summary(server_id, project_id, branch_id)
        if include_all_workbench_admin:
            # Full model inventory for admin permission-management screens.
            return self.repo.list_cached_models(server_id, project_id, branch_id)
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
        agent_settings = self.get_workbench_agent_admin_settings()
        normalized = base_url.strip().rstrip("/")
        if normalized.endswith("/api"):
            normalized = normalized[:-4]
        normalized = normalized.rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme not in ({"https", "http"} if agent_settings.openwebui_allow_insecure_http else {"https"}):
            raise ValueError("Open WebUI must use HTTPS unless insecure HTTP is enabled in Settings > Agentic Settings.")
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Open WebUI base URL must be a host origin without credentials, query, or fragment.")
        allowed_hosts = {
            str(host).strip().lower()
            for host in agent_settings.openwebui_allowed_hosts
            if str(host).strip()
        }
        if allowed_hosts and parsed.hostname.lower() not in allowed_hosts:
            raise ValueError("Open WebUI host is not listed in Settings > Agentic Settings allowed hosts.")
        return normalized

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

    def _openwebui_verify(self) -> bool | str:
        agent_settings = self.get_workbench_agent_admin_settings()
        if not agent_settings.openwebui_verify_tls:
            return False
        if agent_settings.openwebui_ca_bundle_path:
            return str(Path(agent_settings.openwebui_ca_bundle_path).expanduser().resolve())
        return True

    async def _upload_openwebui_markdown_file(
        self,
        secret: WorkbenchAgentSecret,
        file_name: str,
        file_content: bytes,
    ) -> str:
        upload_url = f"{secret.base_url}/api/v1/files/?process=true&process_in_background=true"
        upload_timeout = httpx.Timeout(connect=30.0, read=120.0, write=900.0, pool=60.0)
        try:
            async with httpx.AsyncClient(timeout=upload_timeout, verify=self._openwebui_verify(), follow_redirects=True) as client:
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

        async with httpx.AsyncClient(timeout=status_timeout, verify=self._openwebui_verify(), follow_redirects=True) as client:
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

    def _three_ds_query_context(self, query: str) -> str:
        corpus = self._validate_three_ds_corpus()
        agent_settings = self.get_workbench_agent_admin_settings()
        documents = corpus.retrieve(
            f"TWC Workbench 2024x Refresh3 {query}",
            maximum_documents=agent_settings.three_ds_kb_retrieval_max_documents,
            maximum_characters=agent_settings.three_ds_kb_retrieval_max_characters,
        )
        if not documents:
            return (
                "SOURCE_NOT_IN_3DS_CORPUS: no path-routed evidence matched the request. "
                "Do not answer from model memory."
            )
        sections = [
            "## Query-routed evidence from the single authoritative 3DS_KB",
            "",
            f"Corpus root: {corpus.root}",
            f"Completion certificate SHA-256: {corpus.validated().certificate_sha256}",
            "",
        ]
        for document in documents:
            sections.extend(
                [
                    f"### {document.relative_path}",
                    "",
                    document.content,
                    "",
                    (
                        "[Workbench retrieval excerpt ended at the configured context limit.]"
                        if document.truncated
                        else "[Complete document.]"
                    ),
                    "",
                ]
            )
        return "\n".join(sections)

    def _workbench_agent_system_prompt(
        self,
        session: SessionData,
        project_id: str,
        branch_id: str,
        *,
        query_context: str,
    ) -> str:
        manifest = self.cache_api_manifest(
            preferred_username=session.user.preferred_username,
            source="app-key",
            scopes=[CacheApiKeyScope.READ, CacheApiKeyScope.WRITE, CacheApiKeyScope.EDIT],
        )
        return (
            "You are the Workbench Agent inside TWC Workbench. "
            "A processed branch file, validated 3DS control rails, and query-routed evidence from the single authoritative 3DS_KB are supplied with every request. "
            "Use the branch model file as the primary source of truth for project-specific names, IDs, containment, native specifications, stereotypes, relationships, and diagrams. "
            "Use only the supplied 3DS_KB evidence for Cameo, MagicDraw, Teamwork Cloud, SysML, UML, plugin, or 3DS guidance. Never substitute model memory or another KB. "
            "Never invent an endpoint, Java API, property, stereotype value, or model fact that these sources do not establish. "
            "When helping with automation, default to Python requests scripts against the Workbench API. "
            "When explicitly asked to create a new Workbench API call, implement it in the proper Workbench layers: "
            "FastAPI route in backend/app/api/routes, service logic in backend/app/services/platform.py or the appropriate service module, "
            "permission checks before data access, API Explorer registration when user-facing, frontend helper/types when the UI calls it, "
            "docs/examples for copy-paste use, and backend/frontend validation before saying it is ready. "
            f"Current user: {session.user.preferred_username}. "
            f"Current project: {project_id}. Current branch: {branch_id}. "
            f"Available Workbench cache routes: {', '.join(manifest.available_routes)}. "
            "If the user asks for code, return complete scripts instead of snippets whenever practical.\n\n"
            f"{query_context}"
        )

    def _default_three_ds_kb_root(self) -> Path:
        bundled = BUNDLED_THREE_DS_KB_ROOT.expanduser().resolve()
        if self._looks_like_three_ds_kb_root(bundled):
            return bundled
        configured_value = getattr(self.settings, "three_ds_kb_path", DEFAULT_THREE_DS_KB_ROOT)
        configured = Path(configured_value).expanduser().resolve()
        if self._looks_like_three_ds_kb_root(configured):
            return configured
        return DEFAULT_THREE_DS_KB_ROOT

    def _effective_three_ds_kb_root(self, agent_settings: WorkbenchAgentAdminSettings | None = None) -> Path:
        settings = agent_settings or self.get_workbench_agent_admin_settings()
        value = settings.three_ds_kb_path.strip()
        if value:
            return Path(value).expanduser().resolve()
        return self._default_three_ds_kb_root()

    @staticmethod
    def _looks_like_three_ds_kb_root(root: Path) -> bool:
        return (
            root.is_dir()
            and (root / "AGENTS.md").is_file()
            and (root / "00_MACHINE_MANIFEST.md").is_file()
            and (root / "00_VALIDATION.md").is_file()
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
            "36_workbench_owned_elements.py",
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

    def _resolved_three_ds_kb_root(self) -> Path | None:
        root = self._effective_three_ds_kb_root()
        if self._looks_like_three_ds_kb_root(root):
            return root
        return None

    def _three_ds_corpus_service(self) -> ThreeDsCorpus | None:
        with self._three_ds_corpus_lock:
            root = self._resolved_three_ds_kb_root()
            if root is None:
                return None
            if self._three_ds_corpus is None or self._three_ds_corpus_root != root:
                self._three_ds_corpus = ThreeDsCorpus(root)
                self._three_ds_corpus_root = root
            return self._three_ds_corpus

    def _validate_three_ds_corpus(self, progress: Callable[[int, int, str], None] | None = None) -> ThreeDsCorpus:
        with self._three_ds_corpus_lock:
            corpus = self._three_ds_corpus_service()
            if corpus is None:
                raise RuntimeError(
                    "The authoritative 3DS KB is unavailable at "
                    f"{self._effective_three_ds_kb_root()}. Workbench does not fall back to another KB."
                )
            try:
                corpus.validated()
            except RuntimeError:
                certificate_path = self.settings.resolved_database_path.parent / "three_ds_corpus_certificate.tsv"
                try:
                    corpus.load_validated_certificate(certificate_path)
                except RuntimeError:
                    corpus.validate(certificate_path, progress=progress)
            return corpus

    def _three_ds_kb_status(self) -> dict[str, Any]:
        with self._three_ds_corpus_lock:
            corpus = self._three_ds_corpus_service()
            if corpus is None:
                return {
                    "three_ds_kb_available": False,
                    "three_ds_kb_page_count": 0,
                    "three_ds_kb_chunk_count": 0,
                }
            try:
                _, entries = corpus.inspect()
            except RuntimeError:
                return {
                    "three_ds_kb_available": False,
                    "three_ds_kb_page_count": 0,
                    "three_ds_kb_chunk_count": 0,
                }
            return {
                "three_ds_kb_available": True,
                "three_ds_kb_page_count": len(entries) + 3,
                "three_ds_kb_chunk_count": len(entries) + 2,
            }

    def _build_workbench_reference_documents(self) -> tuple[list[tuple[str, bytes]], dict[str, int], str]:
        corpus = self._validate_three_ds_corpus()
        control_documents = corpus.control_documents()
        stats = self._three_ds_kb_status()
        common_lines = [
            "# TWC Workbench Agent reference",
            "",
            "This is the persistent operating reference for every model used through Workbench Agent.",
            "",
            "## Required response behavior",
            "",
            "1. For questions about Workbench operation, use the Workbench API routes and complete Python examples in this file.",
            "2. For Cameo, MagicDraw, Teamwork Cloud, SysML, UML, plugin, or 3DS questions, use only the query-routed evidence supplied from the authoritative 3DS_KB.",
            "3. Treat the separately attached branch model file as authoritative for project-specific names, IDs, structure, properties, stereotypes, and relationships.",
            "4. Never invent an endpoint, Java API, metaclass property, stereotype value, or model fact. Say when the attached sources do not prove it.",
            "5. When returning automation, prefer a complete runnable Python script against the scoped Workbench API unless the user explicitly asks for Cameo Java plugin code.",
            "6. When the user commands creation of a new Workbench API call, create the endpoint in the Workbench codebase rather than only explaining it. Place the route in `backend/app/api/routes`, place reusable business logic in `backend/app/services/platform.py` or the matching service module, use existing session/CSRF/admin/cache permission helpers, add API Explorer metadata for user-facing calls, add `frontend/src/services/api.ts` helpers and `frontend/src/models/api.ts` types when the UI needs it, add copy-paste examples under `examples/`, update docs, run backend tests and frontend build, then report exact files and route.",
            "7. Never put real tokens, passwords, session cookies, or private TWC data into generated examples. Use environment variables and placeholders.",
            "8. State product/release, execution surface, language/runtime, dependencies, authentication/privileges, runtime-validation status, transactions, destructive effects, cleanup/rollback, and exact 3DS KB paths used.",
            "",
            "## Workbench knowledge surfaces",
            "",
            "- Model Browser: complete accessible Cameo containment tree in published order.",
            "- Specification workspace: native metamodel properties plus ordered applied-stereotype properties, defaults, derived values, multiplicity, type, and state metadata.",
            "- Developer API: scoped cache reads, search, graph, tree, child, and edit workflows.",
            "- Agent: validated 3DS control rails, query-routed 3DS evidence, and the current user's selected branch model file.",
            "",
            "## Workbench API endpoint creation map",
            "",
            "Use this placement map when the user asks to add a new Workbench API call:",
            "",
            "1. Define request/response Pydantic models in `backend/app/models/domain.py` when structured payloads are needed.",
            "2. Add the FastAPI route in the matching file under `backend/app/api/routes/`; workspace/user-session calls usually belong in `backend/app/api/routes/workspace.py`, cache-token automation calls usually belong in `backend/app/api/routes/cache.py`, and auth/session calls belong in `backend/app/api/routes/auth.py`.",
            "3. Keep real logic out of the route body. Add or reuse a method in `backend/app/services/platform.py` or a focused service module.",
            "4. Enforce access before reading or mutating data. Use `get_session` for normal reads, `require_csrf` for user writes, `require_admin`/`require_admin_csrf` for admin-only routes, and the existing effective branch-access helpers for project/model data.",
            "5. If the endpoint should appear in Workbench API Explorer, add a `WORKBENCH_*_OPERATION_KEY`, a `SwaggerOperationSpec`, and an executor branch in `execute_swagger_operation`.",
            "6. If frontend code needs the route, add a typed helper in `frontend/src/services/api.ts` and interfaces in `frontend/src/models/api.ts`.",
            "7. Add runnable examples under `examples/` and update `examples/README.md`; examples must be copy-paste runnable and use environment variables for secrets.",
            "8. Update `README.md`, `CACHE_API.md`, or a focused doc under `docs/` so humans can find the route.",
            "9. Validate with targeted backend tests, `pytest`, and `npm run build`; include PowerShell script parse checks when installer/offline scripts change.",
            "",
            "## Complete Workbench Python examples",
            "",
        ]
        for name, content in self._workbench_agent_example_payload().items():
            common_lines.extend([f"### {name}", "", "```python", content, "```", ""])

        documents: list[tuple[str, bytes]] = []
        operating_content = "\n".join(common_lines).encode("utf-8")
        documents.append(("twc-workbench-operating-reference.md", operating_content))
        control_lines = [
            "# Authoritative 3DS KB control rails",
            "",
            f"Corpus root: {corpus.root}",
            f"Completion certificate: {corpus.validated().certificate_sha256}",
            "",
        ]
        for document in control_documents:
            control_lines.extend(
                [
                    f"## {document.relative_path}",
                    "",
                    document.content,
                    "",
                ]
            )
        documents.append(("twc-3ds-kb-control-rails.md", "\n".join(control_lines).encode("utf-8")))

        digest = hashlib.sha256()
        for name, content in documents:
            digest.update(name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(content)
            digest.update(b"\0")
        return documents, stats, digest.hexdigest()

    async def _ensure_workbench_reference_knowledge(
        self,
        secret: WorkbenchAgentSecret,
        *,
        session: SessionData | None = None,
        report: Callable[[int, str], Awaitable[None]] | None = None,
    ) -> tuple[list[tuple[str, str]], dict[str, int], str]:
        documents, stats, fingerprint = await asyncio.to_thread(self._build_workbench_reference_documents)
        existing_ids = list(secret.reference_file_ids)
        existing_names = list(secret.reference_file_names)
        if not existing_ids and secret.reference_file_id:
            existing_ids = [secret.reference_file_id]
            existing_names = [secret.reference_file_name or documents[0][0]]
        if (
            secret.reference_fingerprint == fingerprint
            and len(existing_ids) == len(documents)
            and len(existing_names) == len(documents)
            and all(existing_ids)
        ):
            if report is not None:
                await report(70, "Persistent Workbench + 3DS reference files are already processed in Open WebUI.")
            return list(zip(existing_ids, existing_names, strict=False)), stats, fingerprint

        expected_names = [name for name, _ in documents]
        can_resume = bool(
            secret.reference_fingerprint == fingerprint
            and len(existing_ids) == len(existing_names)
            and len(existing_ids) < len(documents)
            and existing_names == expected_names[: len(existing_names)]
            and all(existing_ids)
        )
        uploaded: list[tuple[str, str]] = (
            list(zip(existing_ids, existing_names, strict=False)) if can_resume else []
        )
        total_documents = len(documents)
        for index, (file_name, content) in enumerate(documents[len(uploaded) :], start=len(uploaded) + 1):
            if report is not None:
                progress = 48 + int(22 * (index - 1) / max(1, total_documents))
                await report(progress, f"Uploading persistent reference file {index}/{total_documents}: {file_name}.")
            file_id = await self._upload_openwebui_markdown_file(secret, file_name, content)
            uploaded.append((file_id, file_name))
            if report is not None:
                progress = 48 + int(22 * index / max(1, total_documents))
                await report(progress, f"Open WebUI processed persistent reference file {index}/{total_documents}: {file_name}.")
            if session is not None:
                # Persist every completed segment so a gateway restart or a
                # failed later segment resumes without re-uploading the files
                # that Open WebUI has already processed.
                partial_secret = secret.model_copy(
                    update={
                        "reference_file_id": uploaded[0][0],
                        "reference_file_name": uploaded[0][1],
                        "reference_file_ids": [uploaded_id for uploaded_id, _ in uploaded],
                        "reference_file_names": [uploaded_name for _, uploaded_name in uploaded],
                        "reference_fingerprint": fingerprint,
                        "updated_at": utcnow(),
                    }
                )
                self._store_workbench_agent_secret(session, partial_secret)
        return uploaded, stats, fingerprint

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
        tree_child_counts: dict[str, int] = {}

        def index_tree_children(nodes: list[TreeNode]) -> None:
            for node in nodes:
                tree_child_counts[node.id] = len(node.children)
                index_tree_children(node.children)

        index_tree_children(tree_response.nodes)
        with sqlite3.connect(self.settings.resolved_database_path) as connection:
            connection.row_factory = sqlite3.Row
            element_rows = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT model_id, element_id, name, item_type, path, owner_id,
                           qualified_name, metaclass, length(payload) AS payload_bytes
                    FROM twc_cached_elements
                    WHERE server_id = ? AND project_id = ? AND branch_id = ?
                    ORDER BY COALESCE(NULLIF(qualified_name, ''), path, name, element_id)
                    """,
                    (session.server.id, project_id, branch_id),
                ).fetchall()
            ]
        model_count = len(snapshot.models) if snapshot is not None else 0
        lines = [
            f"# TWC Workbench knowledge: {project_name} / {branch_name}",
            "",
            "This bundle is generated from the current user's accessible stored branch snapshot. It is authoritative for project-specific facts. Product, API, and Workbench operating guidance lives in the separately attached persistent Workbench + 3DS reference file set.",
            "",
            "## Context",
            "",
            f"- Workbench user: `{session.user.preferred_username}`",
            f"- Server: {session.server.name} (`{session.server.id}`)",
            f"- Project: {project_name} (`{project_id}`)",
            f"- Branch: {branch_name} (`{branch_id}`)",
            f"- Revision: `{summary.latest_revision or 'unknown'}`",
            f"- Models: {model_count}",
            f"- Elements: {len(element_rows)}",
            f"- Containment tree nodes: {tree_response.total_nodes}",
            "",
            "## Detail retrieval rule",
            "",
            "This branch knowledge file intentionally contains compact indexed element facts instead of every raw cached payload. For exact native specifications, relationships, inner elements, or owned elements, use the Workbench API routes listed near the bottom of this file against the element ID shown here.",
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
        lines.extend(
            [
                "## Compact element index",
                "",
                "Format: `element_id | metaclass | qualified path | owner_id | child_count | cached_payload_bytes`",
                "",
                "```text",
            ]
        )
        for record in element_rows:
            element_id = str(record.get("element_id") or "").strip()
            name = str(record.get("name") or element_id).strip()
            metaclass = str(record.get("metaclass") or record.get("item_type") or "Element").strip()
            qualified_name = str(record.get("qualified_name") or record.get("path") or "").strip()
            owner_id = str(record.get("owner_id") or "").strip()
            payload_bytes = int(record.get("payload_bytes") or 0)
            display_name = name if name and name != element_id else qualified_name
            lines.append(
                " | ".join(
                    [
                        element_id,
                        metaclass,
                        display_name or qualified_name,
                        owner_id,
                        str(tree_child_counts.get(element_id, 0)),
                        str(payload_bytes),
                    ]
                )
            )
        lines.extend(
            [
                "```",
                "",
                "Use `/api/workspace/model-cache/item`, `/api/workspace/model-cache/native-specifications`, `/api/workspace/model-cache/element-graph`, or `/api/workspace/model-cache/owned-elements` with an element ID above for exact native details.",
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
            "element_count": len(element_rows),
            "tree_node_count": tree_response.total_nodes,
        }
        return file_name, "\n".join(lines).encode("utf-8"), stats

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

    def reveal_cache_ingest_token(self) -> CacheIngestTokenRevealResponse:
        token, updated_at = self._shared_cache_ingest_token()
        if not token:
            raise ValueError("No app-managed plugin ingest token is stored. Generate or save one first.")
        return CacheIngestTokenRevealResponse(
            configured=True,
            source="shared",
            token_hint=self._token_hint(token),
            updated_at=updated_at,
            message="The app-managed plugin ingest token was revealed for this administrator session.",
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
                "GET /api/cache/servers/{server_id}/projects/{project_id}/branches/{branch_id}/spec-diagnostic",
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
        can_manage_groups = can_manage or self._claims_grant_group_manager(roles, groups)

        if roles or groups or permissions:
            return AuthorizationContext(
                roles=roles,
                role_ids=role_ids,
                groups=groups,
                permissions=permissions,
                permissions_included=permissions_included,
                source="upstream-authorization-claims",
                can_manage_server_presets=can_manage,
                can_manage_groups=can_manage_groups,
            )

        return AuthorizationContext(
            roles=[],
            role_ids=role_ids,
            groups=[],
            permissions=permissions,
            permissions_included=permissions_included,
            source="authenticated-user-default",
            can_manage_server_presets=can_manage,
            can_manage_groups=can_manage_groups,
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

    def _claims_grant_group_manager(self, roles: list[str], groups: list[str]) -> bool:
        normalized_claims = {
            re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
            for value in [*roles, *groups]
            if value.strip()
        }
        return "group manager" in normalized_claims

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
        self.settings = settings
        self.repo = SqliteRepository(settings.resolved_database_path)
        if settings.twc_preset_servers:
            self.repo.sync_servers(settings.twc_preset_servers)
        self.sessions = SessionManager(settings)
        self.jobs = JobCoordinator(self.repo)
        self.publisher = build_publisher(settings)
        self.platform = PlatformService(
            settings=settings,
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
