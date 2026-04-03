from __future__ import annotations

import csv
import json
from contextlib import suppress
from io import StringIO
from pathlib import Path
from typing import Any

import httpx
import structlog

from app.adapters.teamwork import TeamworkAdapter, create_adapter
from app.auth.oauth import OAuthCallbackResult, OAuthService
from app.core.pdf import render_pdf_document
from app.core.storage import SqliteRepository
from app.integrations.publisher import PublisherAdapter, build_publisher
from app.jobs.coordinator import JobCoordinator
from app.models.domain import (
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
    PATLoginRequest,
    PublishRequest,
    SavedSearch,
    SearchResponse,
    ServerHealth,
    ServerProfile,
    ServerProfileCreate,
    ServerProfileUpdate,
    SessionData,
    SessionPreferences,
    SimulationConfig,
    SimulationRunRequest,
    TokenBundle,
    TWCVersion,
    UserContext,
    utcnow,
)
from app.security.session import SessionManager
from app.settings.config import Settings

logger = structlog.get_logger(__name__)


class PlatformService:
    def __init__(
        self,
        *,
        settings: Settings,
        repo: SqliteRepository,
        sessions: SessionManager,
        oauth: OAuthService,
        jobs: JobCoordinator,
        publisher: PublisherAdapter,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.sessions = sessions
        self.oauth = oauth
        self.jobs = jobs
        self.publisher = publisher

    def list_servers(self) -> list[ServerProfile]:
        return self.repo.list_servers()

    def create_server(self, payload: ServerProfileCreate) -> ServerProfile:
        server = ServerProfile(**payload.model_dump())
        return self.repo.upsert_server(server)

    def update_server(self, server_id: str, payload: ServerProfileUpdate) -> ServerProfile:
        current = self._require_server(server_id)
        updated = current.model_copy(update={key: value for key, value in payload.model_dump(exclude_none=True).items()})
        updated.updated_at = utcnow()
        return self.repo.upsert_server(updated)

    def delete_server(self, server_id: str) -> bool:
        return self.repo.delete_server(server_id)

    def get_server(self, server_id: str) -> ServerProfile | None:
        return self.repo.get_server(server_id)

    async def health_check(self, server_id: str) -> ServerHealth:
        server = self._require_server(server_id)
        verify = server.ca_bundle_path if server.verify_tls and server.ca_bundle_path else server.verify_tls
        checks = {"base_url": False, "auth_url": False}
        version_hint = server.version.value if server.version != TWCVersion.AUTO else None
        message = ""
        response_time_ms = None
        try:
            async with httpx.AsyncClient(timeout=8.0, verify=verify, follow_redirects=True) as client:
                response = await client.get(server.base_url)
                checks["base_url"] = response.status_code < 500
                auth_response = await client.get(server.auth_url)
                checks["auth_url"] = auth_response.status_code < 500
                response_time_ms = int(response.elapsed.total_seconds() * 1000)
                text = f"{response.text}\n{auth_response.text}".lower()
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

    async def create_signin_url(self, server_id: str) -> str:
        server = self._require_server(server_id)
        return await self.oauth.create_authorization_url(server)

    async def finalize_oauth(self, server_id: str, callback: OAuthCallbackResult) -> SessionData:
        server = self._require_server(server_id)
        user = UserContext(
            preferred_username=callback.preferred_username,
            server_id=server.id,
            server_name=server.name,
        )
        adapter = self._adapter_for_credentials(server, callback.token_bundle)
        capabilities = await adapter.discover_capabilities()
        capabilities.capabilities["publish"] = self.publisher.capability()
        session = self.sessions.create_session(server, user, callback.token_bundle, capabilities)
        server.last_used_at = session.created_at
        self.repo.upsert_server(server)
        logger.info("oauth-login-complete", user=user.preferred_username, server_id=server.id)
        return session

    async def login_with_pat(self, payload: PATLoginRequest) -> SessionData:
        if not self.settings.enable_pat_login:
            raise PermissionError("Personal access token login is disabled")
        if self.settings.pat_admin_secret and payload.admin_secret != self.settings.pat_admin_secret:
            raise PermissionError("Invalid admin secret for personal access token login")

        server = self._require_server(payload.server_id)
        token_bundle = TokenBundle(access_token=payload.personal_access_token, token_type="Bearer")
        user = UserContext(
            preferred_username=payload.preferred_username,
            server_id=server.id,
            server_name=server.name,
        )
        adapter = self._adapter_for_credentials(server, token_bundle)
        capabilities = await adapter.discover_capabilities()
        capabilities.capabilities["publish"] = self.publisher.capability()
        session = self.sessions.create_session(server, user, token_bundle, capabilities)
        server.last_used_at = session.created_at
        self.repo.upsert_server(server)
        logger.info("pat-login-complete", user=user.preferred_username, server_id=server.id)
        return session

    def get_session_snapshot(self, session_id: str | None):
        return self.sessions.snapshot(self.sessions.get_session(session_id))

    def get_preferences(self, session: SessionData) -> SessionPreferences:
        return session.preferences

    async def refresh_capabilities(self, session: SessionData):
        adapter = self._adapter_for_session(session)
        capabilities = await adapter.discover_capabilities()
        capabilities.capabilities["publish"] = self.publisher.capability()
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
        jobs = self.jobs.list_jobs(session.user.preferred_username)[:8]
        return DashboardPayload(
            projects=projects,
            recent_items=session.recent_items,
            bookmarks=session.bookmarks,
            capability_badges=list(session.capabilities.capabilities.values()),
            active_jobs=jobs,
            publish_presets=self.publisher.presets(),
        )

    async def list_projects(self, session: SessionData):
        return await self._adapter_for_session(session).list_projects()

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
            Bookmark(title=item.name, item_id=item.id, item_type=item.item_type, path=item.path),
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
            Bookmark(title=item.name, item_id=item.id, item_type=item.item_type, path=item.path),
        )
        return item

    async def search(self, session: SessionData, query: str) -> SearchResponse:
        return await self._adapter_for_session(session).search(query)

    async def compare_items(self, session: SessionData, left_id: str, right_id: str) -> CompareResult:
        return await self._adapter_for_session(session).compare_items(left_id, right_id)

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
            item = await self.get_item(session, request.reference_id)
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

    def _adapter_for_session(self, session: SessionData) -> TeamworkAdapter:
        return self._adapter_for_credentials(session.server, self.sessions.get_tokens(session))

    def _adapter_for_credentials(self, server: ServerProfile, tokens) -> TeamworkAdapter:
        return create_adapter(server, tokens, self.settings.resolved_data_dir)

    def _require_server(self, server_id: str) -> ServerProfile:
        server = self.repo.get_server(server_id)
        if not server:
            raise KeyError(server_id)
        return server


class ApplicationContainer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.repo = SqliteRepository(settings.resolved_database_path)
        self.sessions = SessionManager(settings)
        self.oauth = OAuthService()
        self.jobs = JobCoordinator(self.repo)
        self.publisher = build_publisher(settings)
        self.platform = PlatformService(
            settings=settings,
            repo=self.repo,
            sessions=self.sessions,
            oauth=self.oauth,
            jobs=self.jobs,
            publisher=self.publisher,
        )

    async def close(self) -> None:
        return None
