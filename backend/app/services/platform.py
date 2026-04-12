from __future__ import annotations

import base64
import csv
import json
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import httpx
import structlog

from app.auth.twc import infer_token_expiry, refresh_twc_auth_token
from app.adapters.teamwork import TeamworkAdapter, create_adapter
from app.core.pdf import render_pdf_document
from app.core.storage import SqliteRepository
from app.integrations.publisher import PublisherAdapter, build_publisher
from app.jobs.coordinator import JobCoordinator
from app.models.domain import (
    AuthorizationContext,
    Bookmark,
    BranchUpdateRequest,
    CapabilityState,
    CommentEntry,
    CompareResult,
    DashboardPayload,
    ExportRequest,
    ItemDetails,
    JobRecord,
    JobType,
    OSLCAuthorizationStatus,
    OSLCConsumerCredentials,
    OSLCExecuteRequest,
    OSLCExecuteResponse,
    OSLCGenerateConsumerResponse,
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
    TWCVersion,
    UserServerState,
    UserContext,
    utcnow,
)
from app.security.session import SessionManager
from app.services.swagger_contract import SwaggerContract
from app.settings.config import Settings

logger = structlog.get_logger(__name__)


ADMIN_CLAIM_MARKERS = ("admin", "administrator")


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
        adapter = self._adapter_for_session(session)
        projects = await adapter.list_projects()
        logger.info("twc-project-list-dashboard", user=session.user.preferred_username, server_id=session.server.id, delivered_count=len(projects))
        return DashboardPayload(
            projects=projects,
            recent_items=session.recent_items,
            bookmarks=session.bookmarks,
            capability_badges=list(session.capabilities.capabilities.values()),
            active_jobs=[],
            publish_presets=[],
        )

    async def list_projects(self, session: SessionData):
        projects = await self._adapter_for_session(session).list_projects()
        logger.info("twc-project-list-ui", user=session.user.preferred_username, server_id=session.server.id, delivered_count=len(projects))
        return projects

    async def get_model_tree(self, session: SessionData, project_id: str | None, branch_id: str | None):
        return await self._adapter_for_session(session).get_model_tree(project_id, branch_id)

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
    ) -> ItemDetails:
        item = await self._adapter_for_session(session).get_item(item_id, project_id, branch_id)
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
        return await self._adapter_for_session(session).compare_items(
            left_id,
            right_id,
            left_project_id,
            left_branch_id,
            right_project_id,
            right_branch_id,
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
        resolved_consumer = self.oauth.effective_consumer_credentials(server, session_consumer)
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

    def _build_authorization_context(
        self,
        current_user_context,
        *,
        upstream_roles: list[str] | None,
        upstream_groups: list[str] | None,
    ) -> AuthorizationContext:
        roles = self._merge_claims(*(upstream_roles or []), *((current_user_context.roles) if current_user_context else []))
        groups = self._merge_claims(*(upstream_groups or []), *((current_user_context.groups) if current_user_context else []))

        if roles or groups:
            return AuthorizationContext(
                roles=roles,
                groups=groups,
                source="upstream-authorization-claims",
                can_manage_server_presets=self._claims_grant_admin(roles, groups),
            )

        return AuthorizationContext(
            roles=[],
            groups=[],
            source="authenticated-user-default",
            can_manage_server_presets=True,
        )

    def _claims_grant_admin(self, roles: list[str], groups: list[str]) -> bool:
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
