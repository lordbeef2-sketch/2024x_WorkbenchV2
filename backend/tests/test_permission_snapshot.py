from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from app.core.storage import SqliteRepository
from app.jobs.coordinator import JobCoordinator
from app.models.domain import (
    AuthorizationContext,
    AuthorizationPermissionClaim,
    BranchAccessRecord,
    BranchCacheSummary,
    BranchDeltaIngestRequest,
    BranchPermissionAttachment,
    BranchSnapshotIngestRequest,
    BranchTombstoneRequest,
    CapabilitySummary,
    CacheProjectBranchEntry,
    CacheProjectEntry,
    CachedModelRecord,
    JobRecord,
    JobStatus,
    JobType,
    IngestElementRecord,
    IngestModelRecord,
    ModelPermissionSnapshot,
    PermissionManifest,
    PermissionManifestEntry,
    PermissionRefreshAuditRecord,
    ProjectTombstoneRequest,
    ServerProfile,
    ServerPermissionInventory,
    ServerPermissionInventoryAuditRecord,
    SessionData,
    UserContext,
)
from app.services.platform import PermissionSnapshotIndeterminateError, PlatformService


class PermissionSnapshotReplacementTests(unittest.TestCase):
    def test_project_listing_filters_actual_cache_entries_through_branch_summaries(self) -> None:
        service = object.__new__(PlatformService)
        service.list_cached_projects_for_user = lambda server_id, username: [
            CacheProjectEntry(
                project_id="project",
                project_name="Project",
                branches=[
                    CacheProjectBranchEntry(branch_id="main", branch_name="Main"),
                    CacheProjectBranchEntry(branch_id="legacy", branch_name="Legacy"),
                ],
            )
        ]
        summaries = {
            "main": BranchCacheSummary(
                server_id="server",
                project_id="project",
                branch_id="main",
                source_kind="cameo-plugin",
            ),
            "legacy": BranchCacheSummary(
                server_id="server",
                project_id="project",
                branch_id="legacy",
                source_kind="twc-rest",
            ),
        }
        service.repo = SimpleNamespace(
            get_branch_cache_summary=lambda server_id, project_id, branch_id: summaries[branch_id]
        )
        session = SimpleNamespace(
            server=SimpleNamespace(id="server"),
            user=SimpleNamespace(preferred_username="Alice"),
        )

        projects = service._project_summaries_from_cache_for_user(session)
        branches = service._branch_summaries_from_cache_for_user(session, "project")

        self.assertEqual([item.id for item in projects], ["project"])
        self.assertEqual([item.id for item in projects[0].branches], ["main"])
        self.assertEqual([item.id for item in branches], ["main"])

    def test_current_permission_status_uses_plugin_publisher_fallback_used_by_branch_listing(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            repo = SqliteRepository(Path(directory) / "workbench.db")
            repo.upsert_branch_cache_summary(
                BranchCacheSummary(
                    server_id="server",
                    project_id="project",
                    branch_id="trunk",
                    source_kind="cameo-plugin",
                    source_user="Alice",
                )
            )
            repo.upsert_cached_models([
                CachedModelRecord(
                    server_id="server",
                    project_id="project",
                    branch_id="trunk",
                    model_id="model",
                )
            ])
            service = object.__new__(PlatformService)
            service.repo = repo
            session = SimpleNamespace(
                server=SimpleNamespace(id="server"),
                user=SimpleNamespace(preferred_username="Alice"),
            )

            status = service.current_permission_status(session, "project", "trunk", "model")

            self.assertTrue(status.project_accessible)
            self.assertTrue(status.branch_accessible)
            self.assertTrue(status.branch_editable)
            self.assertTrue(status.model_accessible)
            self.assertTrue(status.model_editable)

    def test_current_permission_status_uses_rest_model_visibility_when_branch_row_is_absent(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            repo = SqliteRepository(Path(directory) / "workbench.db")
            repo.upsert_branch_cache_summary(
                BranchCacheSummary(
                    server_id="server",
                    project_id="project",
                    branch_id="trunk",
                    source_kind="twc-rest",
                )
            )
            repo.upsert_model_permissions([
                ModelPermissionSnapshot(
                    user_id="alice",
                    server_id="server",
                    project_id="project",
                    branch_id="trunk",
                    model_id="model",
                    accessible=True,
                    editable=False,
                )
            ])
            service = object.__new__(PlatformService)
            service.repo = repo
            session = SimpleNamespace(
                server=SimpleNamespace(id="server"),
                user=SimpleNamespace(preferred_username="Alice"),
            )

            status = service.current_permission_status(session, "project", "trunk", "model")

            self.assertTrue(status.project_accessible)
            self.assertTrue(status.branch_accessible)
            self.assertFalse(status.branch_editable)
            self.assertTrue(status.model_accessible)
            self.assertFalse(status.model_editable)

    def test_current_permission_status_tracks_branch_and_model_revocation(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            repo = SqliteRepository(Path(directory) / "workbench.db")
            repo.upsert_branch_access_records([
                BranchAccessRecord(
                    user_id="alice",
                    server_id="server",
                    project_id="project",
                    branch_id="main",
                    accessible=True,
                    editable=True,
                )
            ])
            repo.upsert_model_permissions([
                ModelPermissionSnapshot(
                    user_id="alice",
                    server_id="server",
                    project_id="project",
                    branch_id="main",
                    model_id="model",
                    accessible=True,
                    editable=True,
                )
            ])
            service = object.__new__(PlatformService)
            service.repo = repo
            session = SimpleNamespace(
                server=SimpleNamespace(id="server"),
                user=SimpleNamespace(preferred_username="Alice"),
            )

            allowed = service.current_permission_status(session, "project", "main", "model")
            self.assertTrue(allowed.branch_accessible)
            self.assertTrue(allowed.model_accessible)

            repo.replace_user_permission_snapshot("alice", "server", [], [])
            revoked = service.current_permission_status(session, "project", "main", "model")
            self.assertFalse(revoked.project_accessible)
            self.assertFalse(revoked.branch_accessible)
            self.assertFalse(revoked.model_accessible)

    def test_permission_refresh_lease_coordinates_repository_processes(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            database_path = Path(directory) / "workbench.db"
            first = SqliteRepository(database_path)
            second = SqliteRepository(database_path)

            self.assertTrue(first.acquire_permission_refresh_lease("permission-refresh:server:alice", "worker-a", ttl_seconds=60))
            self.assertFalse(second.acquire_permission_refresh_lease("permission-refresh:server:alice", "worker-b", ttl_seconds=60))
            self.assertTrue(first.renew_permission_refresh_lease("permission-refresh:server:alice", "worker-a", ttl_seconds=60))
            first.release_permission_refresh_lease("permission-refresh:server:alice", "worker-a")
            self.assertTrue(second.acquire_permission_refresh_lease("permission-refresh:server:alice", "worker-b", ttl_seconds=60))

    def test_permission_refresh_audit_is_append_only_and_queryable(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            repo = SqliteRepository(Path(directory) / "workbench.db")
            record = PermissionRefreshAuditRecord(
                user_id="alice",
                server_id="server",
                reason="scheduled-permission-refresh",
                authoritative=True,
                status="succeeded",
                previous_hash="before",
                current_hash="after",
                revoked_branches=["project/old"],
            )

            repo.append_permission_refresh_audit(record)

            stored = repo.list_permission_refresh_audit("server", "alice")
            self.assertEqual([item.id for item in stored], [record.id])
            self.assertEqual(stored[0].revoked_branches, ["project/old"])

    def test_replacement_removes_stale_grants_and_preserves_other_users(self) -> None:
        # SQLite read helpers rely on interpreter cleanup for connection close;
        # ignore Windows' transient file-lock cleanup error in this isolated DB.
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            repo = SqliteRepository(Path(directory) / "workbench.db")
            alice_initial = [
                BranchAccessRecord(
                    user_id="alice",
                    server_id="server",
                    project_id="project",
                    branch_id="main",
                    accessible=True,
                    editable=True,
                ),
                BranchAccessRecord(
                    user_id="alice",
                    server_id="server",
                    project_id="project",
                    branch_id="old-branch",
                    accessible=True,
                ),
            ]
            alice_models = [
                ModelPermissionSnapshot(
                    user_id="alice",
                    server_id="server",
                    project_id="project",
                    branch_id="main",
                    model_id="model-old",
                    accessible=True,
                    editable=True,
                )
            ]
            bob_record = BranchAccessRecord(
                user_id="bob",
                server_id="server",
                project_id="project",
                branch_id="main",
                accessible=True,
            )
            repo.upsert_branch_access_records([*alice_initial, bob_record])
            repo.upsert_model_permissions(alice_models)

            alice_replacement = BranchAccessRecord(
                user_id="alice",
                server_id="server",
                project_id="project",
                branch_id="main",
                accessible=False,
                editable=False,
                source="twc-user-permission-snapshot",
            )
            denied_model = ModelPermissionSnapshot(
                user_id="alice",
                server_id="server",
                project_id="project",
                branch_id="main",
                model_id="model-current",
                accessible=False,
                restricted=True,
                editable=False,
            )
            repo.replace_user_permission_snapshot(
                "alice",
                "server",
                [alice_replacement],
                [denied_model],
            )

            self.assertIsNone(repo.get_branch_access_record("alice", "server", "project", "old-branch"))
            current = repo.get_branch_access_record("alice", "server", "project", "main")
            self.assertIsNotNone(current)
            self.assertFalse(current.accessible)
            self.assertIsNone(repo.get_model_permission("alice", "server", "project", "main", "model-old"))
            self.assertIsNotNone(repo.get_model_permission("alice", "server", "project", "main", "model-current"))
            self.assertTrue(repo.get_branch_access_record("bob", "server", "project", "main").accessible)

            repo.replace_user_permission_snapshot("alice", "server", [], [])
            self.assertIsNone(repo.get_branch_access_record("alice", "server", "project", "main"))
            self.assertIsNone(repo.get_model_permission("alice", "server", "project", "main", "model-current"))
            self.assertTrue(repo.get_branch_access_record("bob", "server", "project", "main").accessible)

    def test_permission_attachment_is_saved_with_atomic_user_snapshot(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            repo = SqliteRepository(Path(directory) / "workbench.db")
            attachment = BranchPermissionAttachment(
                server_id="server",
                project_id="project",
                branch_id="main",
                latest_revision="42",
                snapshot_hash="abc",
                manifest=PermissionManifest(
                    source="cameo-package-permissions",
                    entries=[
                        PermissionManifestEntry(
                            scope_id="package-1",
                            scope_type="package",
                            principal_name="engineering",
                            principal_type="group",
                            action="READ_WRITE",
                            accessible=True,
                            editable=True,
                        )
                    ],
                ),
            )

            repo.replace_user_permission_snapshot("alice", "server", [], [], [attachment])

            stored = repo.get_branch_permission_attachment("server", "project", "main")
            self.assertIsNotNone(stored)
            self.assertEqual(stored.latest_revision, "42")
            self.assertEqual(stored.manifest.entries[0].principal_name, "engineering")

    def test_server_permission_inventory_is_persisted_and_marked_dirty(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            repo = SqliteRepository(Path(directory) / "workbench.db")
            inventory = ServerPermissionInventory(
                server_id="server",
                roles=[{"ID": "role-1", "name": "Resource Manager"}],
                groups=[{"ID": "group-1", "name": "Managers"}],
            )

            repo.upsert_server_permission_inventory(inventory)
            stored = repo.get_server_permission_inventory("server")
            self.assertIsNotNone(stored)
            self.assertEqual(stored.roles[0]["name"], "Resource Manager")
            repo.mark_server_permission_inventory_dirty("server")
            dirty = repo.get_server_permission_inventory("server")
            self.assertTrue(dirty.dirty)
            self.assertEqual(dirty.roles[0]["name"], "Resource Manager")

    def test_inventory_audit_is_append_only_and_job_retention_preserves_active_jobs(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            repo = SqliteRepository(Path(directory) / "workbench.db")
            audit = ServerPermissionInventoryAuditRecord(
                server_id="server",
                job_id="job-1",
                triggered_by="admin",
                reason="upload",
                status="succeeded",
                previous_hash="before",
                current_hash="after",
                current_role_count=5,
                current_group_count=7,
            )
            repo.append_server_permission_inventory_audit(audit)
            old = datetime.now(UTC) - timedelta(days=60)
            completed = JobRecord(
                job_type=JobType.PERMISSION_INVENTORY_REFRESH,
                status=JobStatus.SUCCEEDED,
                title="done",
                owner="admin",
                server_id="server",
                payload={},
                created_at=old,
                updated_at=old,
            )
            running = JobRecord(
                job_type=JobType.PERMISSION_INVENTORY_REFRESH,
                status=JobStatus.RUNNING,
                title="running",
                owner="admin",
                server_id="server",
                payload={},
                created_at=old,
                updated_at=old,
            )
            repo.upsert_job(completed)
            repo.upsert_job(running)

            deleted = repo.delete_completed_jobs_before(datetime.now(UTC) - timedelta(days=30))

            self.assertEqual(repo.list_server_permission_inventory_audit("server"), [audit])
            self.assertEqual(repo.server_permission_inventory_audit_counts("server")["succeeded"], 1)
            self.assertEqual(deleted, 1)
            self.assertIsNone(repo.get_job(completed.id))
            self.assertIsNotNone(repo.get_job(running.id))

    def test_restart_recovery_marks_abandoned_jobs_failed(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            repo = SqliteRepository(Path(directory) / "workbench.db")
            abandoned = JobRecord(
                job_type=JobType.PERMISSION_INVENTORY_REFRESH,
                status=JobStatus.RUNNING,
                title="inventory",
                owner="admin",
                server_id="server",
                payload={},
                updated_at=datetime.now(UTC) - timedelta(hours=1),
            )
            repo.upsert_job(abandoned)
            fresh = JobRecord(
                job_type=JobType.PERMISSION_INVENTORY_REFRESH,
                status=JobStatus.RUNNING,
                title="other worker",
                owner="admin",
                server_id="server",
                payload={},
            )
            repo.upsert_job(fresh)

            recovered = JobCoordinator(repo).recover_interrupted_jobs(
                stale_before=datetime.now(UTC) - timedelta(minutes=30)
            )

            self.assertEqual([job.id for job in recovered], [abandoned.id])
            stored = repo.get_job(abandoned.id)
            self.assertEqual(stored.status, JobStatus.FAILED)
            self.assertIn("restart", stored.message.lower())
            self.assertEqual(repo.get_job(fresh.id).status, JobStatus.RUNNING)


class PermissionAttachmentComparisonTests(unittest.TestCase):
    def test_current_attached_rest_acl_is_reused_without_group_rescan(self) -> None:
        service = object.__new__(PlatformService)
        captured_at = datetime.now(UTC)
        summary = BranchCacheSummary(
            server_id="server",
            project_id="project",
            branch_id="main",
            latest_revision="42",
        )
        attachment = BranchPermissionAttachment(
            server_id="server",
            project_id="project",
            branch_id="main",
            latest_revision="42",
            attached_at=captured_at,
            manifest=PermissionManifest(
                source="twc-rest-role-manifest",
                complete=True,
                entries=[
                    PermissionManifestEntry(
                        scope_id="main",
                        scope_type="project-branch",
                        principal_name="alice",
                        principal_type="user",
                        role_name="Resource Manager",
                        accessible=True,
                        editable=True,
                        via_groups=["Engineering"],
                        readonly_branch_ids=["release"],
                    )
                ],
            ),
        )
        inventory = ServerPermissionInventory(
            server_id="server",
            captured_at=captured_at - timedelta(minutes=1),
        )
        session = SimpleNamespace(
            server=SimpleNamespace(id="server"),
            user=SimpleNamespace(preferred_username="Alice"),
        )

        self.assertTrue(service._attached_rest_manifest_is_current(summary, attachment, inventory))
        access = service._branch_access_from_attached_manifest(session, summary, attachment)
        self.assertIsNotNone(access)
        self.assertEqual(access.roles, ["Resource Manager"])
        self.assertEqual(access.via_groups, ["Engineering"])
        self.assertEqual(access.payload["readonly_branch_ids"], ["release"])
        self.assertFalse(
            service._attached_rest_manifest_is_current(
                summary,
                attachment,
                inventory.model_copy(update={"dirty": True}),
            )
        )

    def test_stale_attached_grant_never_overrides_live_denial(self) -> None:
        service = object.__new__(PlatformService)
        session = SimpleNamespace(
            user=SimpleNamespace(preferred_username="Alice"),
            authorization_context=SimpleNamespace(roles=[], groups=["Engineering"]),
        )
        attachment = BranchPermissionAttachment(
            server_id="server",
            project_id="project",
            branch_id="main",
            manifest=PermissionManifest(
                complete=True,
                entries=[
                    PermissionManifestEntry(
                        scope_id="main",
                        scope_type="project-branch",
                        principal_name="Engineering",
                        principal_type="group",
                        accessible=True,
                        editable=True,
                    )
                ],
            ),
        )

        comparison = service._compare_attached_and_live_permissions(
            session,
            attachment,
            accessible=False,
            editable=False,
            branch_admin=False,
            access_admin=False,
        )

        self.assertEqual(comparison["result"], "live-more-restrictive")
        self.assertEqual(comparison["enforced_source"], "twc-rest-current-user")

    def test_rest_refresh_preserves_package_acl_and_adds_role_levels(self) -> None:
        service = object.__new__(PlatformService)
        session = SimpleNamespace(
            server=SimpleNamespace(id="server"),
            user=SimpleNamespace(preferred_username="Alice"),
        )
        summary = BranchCacheSummary(
            server_id="server",
            project_id="project",
            branch_id="main",
            latest_revision="42",
            snapshot_hash="abc",
        )
        prior = BranchPermissionAttachment(
            server_id="server",
            project_id="project",
            branch_id="main",
            manifest=PermissionManifest(
                source="cameo-package-permissions",
                entries=[
                    PermissionManifestEntry(
                        scope_id="package-1",
                        scope_type="package",
                        principal_name="Engineering",
                        principal_type="group",
                        action="READ_WRITE",
                        accessible=True,
                        editable=True,
                    )
                ],
            ),
        )
        live_record = BranchAccessRecord(
            user_id="alice",
            server_id="server",
            project_id="project",
            branch_id="main",
            accessible=True,
            editable=False,
            roles=["Reviewer"],
            via_groups=["Engineering"],
            payload={"branch_admin_access": True, "access_admin_access": False},
        )

        merged = service._permission_attachment_from_rest_manifest(
            session,
            summary,
            [live_record],
            datetime.now(UTC),
            prior,
        )

        self.assertTrue(merged.manifest.complete)
        self.assertEqual(merged.manifest.source, "cameo-package-permissions+twc-rest-role-manifest")
        self.assertEqual([entry.scope_type for entry in merged.manifest.entries], ["package", "project-branch"])
        self.assertEqual(merged.manifest.entries[1].role_name, "Reviewer")
        self.assertEqual(merged.manifest.entries[1].via_groups, ["Engineering"])
        self.assertTrue(merged.manifest.entries[1].branch_admin_access)


class ScheduledPermissionRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_fetches_readonly_branches_once_per_project(self) -> None:
        now = datetime.now(UTC)
        summaries = [
            BranchCacheSummary(
                server_id="server",
                project_id="project",
                branch_id=branch_id,
                branch_name=branch_id,
                source_kind="cameo-plugin",
            )
            for branch_id in ("main", "release")
        ]
        session = SimpleNamespace(
            server=SimpleNamespace(id="server"),
            user=SimpleNamespace(preferred_username="Alice"),
            authorization_context=AuthorizationContext(
                permissions=[
                    AuthorizationPermissionClaim(
                        name="Read Resources",
                        related_resources=["project"],
                    ),
                    AuthorizationPermissionClaim(
                        name="Edit Resources",
                        related_resources=["project"],
                    ),
                ],
                permissions_included=True,
            ),
        )
        resolved = [
            (
                BranchAccessRecord(
                    user_id="alice",
                    server_id="server",
                    project_id="project",
                    branch_id=summary.branch_id,
                ),
                [],
                None,
            )
            for summary in summaries
        ]
        adapter = SimpleNamespace(
            current_user_context=AsyncMock(return_value=None),
            _user_readonly_branches=AsyncMock(return_value=["release"]),
        )
        replacements = []
        service = object.__new__(PlatformService)
        service.settings = SimpleNamespace(permission_snapshot_max_parallel_probes=2)
        service._permission_snapshot_locks = {}
        service._adapter_for_session = lambda item: adapter
        service._server_permission_inventory = AsyncMock(return_value=None)
        service._attach_inventory_role_names = lambda item, inventory: item
        service._resolve_user_branch_permission_snapshot = AsyncMock(side_effect=resolved)
        service.repo = SimpleNamespace(
            list_branch_cache_summaries=lambda server_id: summaries,
            replace_user_permission_snapshot=lambda *args: replacements.append(args),
            delete_user_cache=lambda *args: None,
            delete_user_cache_prefix=lambda *args: None,
        )
        service.sessions = SimpleNamespace(
            mark_permission_snapshot_attempt=lambda *args, **kwargs: None,
        )

        refreshed_at = await service.refresh_user_permission_snapshot(session, reason="login")

        self.assertGreaterEqual(refreshed_at, now)
        adapter.current_user_context.assert_not_awaited()
        adapter._user_readonly_branches.assert_awaited_once_with("project", "alice")
        self.assertEqual(service._resolve_user_branch_permission_snapshot.await_count, 2)
        for call in service._resolve_user_branch_permission_snapshot.await_args_list:
            self.assertEqual(call.kwargs["readonly_branch_ids"], ["release"])
        self.assertEqual(len(replacements), 1)

    async def test_complete_current_user_permissions_skip_branch_and_manifest_probes(self) -> None:
        now = datetime.now(UTC)
        model = CachedModelRecord(
            server_id="server",
            project_id="project",
            branch_id="main",
            model_id="model",
        )
        service = object.__new__(PlatformService)
        service.repo = SimpleNamespace(
            list_cached_models=lambda *args: [model],
            get_branch_permission_attachment=lambda *args: None,
        )
        adapter = SimpleNamespace(
            build_plugin_branch_access_manifest=AsyncMock(),
            probe_plugin_branch_permissions=AsyncMock(),
            _user_readonly_branches=AsyncMock(),
        )
        session = SimpleNamespace(
            server=SimpleNamespace(id="server"),
            user=SimpleNamespace(preferred_username="Alice"),
            authorization_context=AuthorizationContext(
                permissions=[
                    AuthorizationPermissionClaim(
                        name="Read Resources",
                        related_resources=["project"],
                    ),
                    AuthorizationPermissionClaim(
                        name="Edit Resources",
                        related_resources=["project"],
                    ),
                ],
                permissions_included=True,
            ),
        )

        branch, permissions, attachment = await service._resolve_user_branch_permission_snapshot(
            session,
            BranchCacheSummary(
                server_id="server",
                project_id="project",
                branch_id="main",
            ),
            adapter=adapter,
            readonly_branch_ids=[],
            refreshed_at=now,
        )

        self.assertTrue(branch.accessible)
        self.assertTrue(branch.editable)
        self.assertTrue(permissions[0].accessible)
        self.assertTrue(permissions[0].editable)
        self.assertIsNone(attachment)
        adapter.build_plugin_branch_access_manifest.assert_not_awaited()
        adapter.probe_plugin_branch_permissions.assert_not_awaited()
        adapter._user_readonly_branches.assert_not_awaited()

    async def test_recent_snapshot_does_not_call_twc(self) -> None:
        now = datetime.now(UTC)
        session = SimpleNamespace(
            server=SimpleNamespace(id="server"),
            user=SimpleNamespace(preferred_username="Alice"),
            permission_snapshot_attempted_at=now - timedelta(minutes=29),
            permission_snapshot_refreshed_at=now - timedelta(minutes=29),
            created_at=now - timedelta(hours=1),
            expires_at=now + timedelta(hours=1),
        )
        service = object.__new__(PlatformService)
        service.settings = SimpleNamespace(permission_snapshot_refresh_minutes=30)
        service.sessions = SimpleNamespace(list_active_sessions=lambda: [session])
        service._refresh_session_credentials_if_needed = AsyncMock()

        await service.refresh_due_permission_snapshots()

        service._refresh_session_credentials_if_needed.assert_not_awaited()

    async def test_due_refresh_failure_preserves_last_valid_snapshot(self) -> None:
        now = datetime.now(UTC)
        server = ServerProfile(id="server", name="Server", base_url="https://twc.example")
        session = SessionData(
            server=server,
            user=UserContext(preferred_username="Alice", server_id="server", server_name="Server"),
            encrypted_credentials="encrypted",
            capabilities=CapabilitySummary(detected_version="2024x"),
            created_at=now - timedelta(minutes=31),
            expires_at=now + timedelta(hours=1),
            permission_snapshot_attempted_at=now - timedelta(minutes=31),
        )

        class FakeSessions:
            def __init__(self) -> None:
                self.marked: list[tuple[str, bool]] = []

            def list_active_sessions(self):
                return [session]

            def mark_permission_snapshot_attempt(self, item, attempted_at, *, successful, error=None):
                self.marked.append((item.session_id, successful))

        class FakeRepository:
            def __init__(self) -> None:
                self.replacements: list[tuple[str, str, list, list]] = []
                self.deleted_cache_keys: list[str] = []

            def replace_user_permission_snapshot(self, user_id, server_id, branches, permissions):
                self.replacements.append((user_id, server_id, list(branches), list(permissions)))

            def delete_user_cache(self, user_id, server_id, cache_key):
                self.deleted_cache_keys.append(cache_key)

            def delete_user_cache_prefix(self, user_id, server_id, cache_key_prefix):
                self.deleted_cache_keys.append(cache_key_prefix)

        service = object.__new__(PlatformService)
        service.settings = SimpleNamespace(permission_snapshot_refresh_minutes=30)
        service.sessions = FakeSessions()
        service.repo = FakeRepository()
        service._refresh_session_credentials_if_needed = AsyncMock(side_effect=RuntimeError("expired"))

        await service.refresh_due_permission_snapshots()

        self.assertEqual(service.repo.replacements, [])
        self.assertEqual(service.sessions.marked, [(session.session_id, False)])
        self.assertEqual(service.repo.deleted_cache_keys, [])

    async def test_branch_probe_failure_cannot_be_converted_into_a_revocation(self) -> None:
        now = datetime.now(UTC)
        service = object.__new__(PlatformService)
        service.repo = SimpleNamespace(
            list_cached_models=lambda server_id, project_id, branch_id: [],
            get_branch_permission_attachment=lambda server_id, project_id, branch_id: None,
        )
        adapter = SimpleNamespace(
            build_plugin_branch_access_manifest=AsyncMock(return_value=[]),
            probe_plugin_branch_permissions=AsyncMock(side_effect=RuntimeError("temporary gateway failure")),
        )
        session = SimpleNamespace(
            server=SimpleNamespace(id="server"),
            user=SimpleNamespace(preferred_username="Alice"),
        )
        summary = BranchCacheSummary(
            server_id="server",
            project_id="project",
            branch_id="main",
        )

        with self.assertRaises(PermissionSnapshotIndeterminateError):
            await service._resolve_user_branch_permission_snapshot(
                session,
                summary,
                adapter=adapter,
                refreshed_at=now,
            )


class ManualCapabilityRefreshTests(unittest.IsolatedAsyncioTestCase):
    def test_snapshot_capability_summary_builds_without_remote_probe(self) -> None:
        service = object.__new__(PlatformService)
        server = ServerProfile(
            id="server",
            name="Server",
            base_url="https://twc.example",
        )

        capabilities = service._snapshot_capabilities(server)

        self.assertEqual(capabilities.detected_version, "2024x")
        self.assertEqual(capabilities.reachable_endpoints, {"permissions": True})
        self.assertEqual(capabilities.capabilities["models"].source, "workbench-snapshot")

    async def test_refresh_capabilities_queues_permission_refresh_without_blocking(self) -> None:
        capabilities = CapabilitySummary(detected_version="2024x")
        session = SimpleNamespace(
            session_id="session",
            server=SimpleNamespace(id="server"),
            user=SimpleNamespace(preferred_username="Alice"),
        )
        adapter = SimpleNamespace(discover_capabilities=AsyncMock(return_value=capabilities))
        submitted = []
        fake_job = SimpleNamespace(id="permission-job")
        service = object.__new__(PlatformService)
        service._adapter_for_session = lambda item: adapter
        service._snapshot_capabilities = lambda server: capabilities
        service.sessions = SimpleNamespace(
            update_capabilities=lambda item, value: SimpleNamespace(
                session_id=item.session_id,
                server=item.server,
                user=item.user,
                capabilities=value,
            )
        )
        service.jobs = SimpleNamespace(
            list_jobs=lambda owner: [],
            create_job=lambda **kwargs: fake_job,
            submit=lambda job, handler: submitted.append((job, handler)) or job,
        )

        result = await service.refresh_capabilities(session)

        self.assertEqual(result.permission_refresh_job_id, "permission-job")
        self.assertEqual(len(submitted), 1)
        adapter.discover_capabilities.assert_not_awaited()


class IngestPermissionLifecycleTests(unittest.TestCase):
    def test_snapshot_fingerprint_changes_when_native_specification_changes(self) -> None:
        service = object.__new__(PlatformService)
        original = BranchSnapshotIngestRequest(
            serverId="server",
            projectId="project",
            branchId="main",
            sourceUser="publisher",
            models=[IngestModelRecord(modelId="model", rootElementIds=["element"])],
            elements=[
                IngestElementRecord(
                    elementId="element",
                    modelId="model",
                    specSections={"properties": {"documentation": "before"}},
                )
            ],
        )
        changed = original.model_copy(deep=True)
        changed.elements[0].spec_sections["properties"]["documentation"] = "after"

        self.assertNotEqual(
            service._snapshot_hash_from_ingest_payload(original),
            service._snapshot_hash_from_ingest_payload(changed),
        )

    def test_delta_without_baseline_and_target_fingerprints_is_rejected(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            repo = SqliteRepository(Path(directory) / "workbench.db")
            repo.upsert_server(ServerProfile(id="server", name="Server", base_url="https://twc.example"))
            repo.upsert_branch_cache_summary(
                BranchCacheSummary(
                    server_id="server",
                    project_id="project",
                    branch_id="main",
                    snapshot_hash="baseline",
                    source_kind="cameo-plugin",
                )
            )
            service = object.__new__(PlatformService)
            service.repo = repo

            with self.assertRaisesRegex(RuntimeError, "baseline fingerprint"):
                service.ingest_branch_delta(
                    BranchDeltaIngestRequest(
                        serverId="server",
                        projectId="project",
                        branchId="main",
                        sourceUser="publisher",
                    )
                )

            with self.assertRaisesRegex(RuntimeError, "target snapshot fingerprint"):
                service.ingest_branch_delta(
                    BranchDeltaIngestRequest(
                        serverId="server",
                        projectId="project",
                        branchId="main",
                        baseSnapshotHash="baseline",
                        sourceUser="publisher",
                    )
                )

            with self.assertRaisesRegex(RuntimeError, "changed on the server"):
                service.ingest_branch_delta(
                    BranchDeltaIngestRequest(
                        serverId="server",
                        projectId="project",
                        branchId="main",
                        baseSnapshotHash="wrong-baseline",
                        targetSnapshotHash="target",
                        sourceUser="publisher",
                    )
                )

    def test_snapshot_with_elements_builds_cached_records_without_undefined_names(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            data_dir = Path(directory)
            repo = SqliteRepository(data_dir / "workbench.db")
            repo.upsert_server(ServerProfile(id="server", name="Server", base_url="https://twc.example"))
            due_calls: list[str] = []
            service = object.__new__(PlatformService)
            service.repo = repo
            service.settings = SimpleNamespace(resolved_data_dir=data_dir)
            service.sessions = SimpleNamespace(
                mark_server_permission_snapshots_due=lambda server_id: due_calls.append(server_id)
            )
            service._permission_inventory_dirty_notifier = None

            summary = service.ingest_branch_snapshot(
                BranchSnapshotIngestRequest(
                    serverId="server",
                    projectId="project",
                    projectName="Project",
                    branchId="main",
                    branchName="Main",
                    revisionId="1",
                    sourceUser="publisher",
                    models=[
                        IngestModelRecord(
                            modelId="model",
                            name="Model",
                            rootElementIds=["element"],
                        )
                    ],
                    elements=[
                        IngestElementRecord(
                            elementId="element",
                            modelId="model",
                            name="Element",
                            qualifiedName="Model::Element",
                        )
                    ],
                )
            )

            cached = repo.get_cached_element("server", "project", "main", "element", model_id="model")
            self.assertEqual(summary.element_count, 1)
            self.assertIsNotNone(cached)
            self.assertEqual(cached.path, "Model::Element")
            self.assertEqual(due_calls, ["server"])

    def test_acl_delta_marks_users_due_and_tombstone_revokes_branch_atomically(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            data_dir = Path(directory)
            repo = SqliteRepository(data_dir / "workbench.db")
            repo.upsert_server(ServerProfile(id="server", name="Server", base_url="https://twc.example"))
            repo.upsert_server_permission_inventory(
                ServerPermissionInventory(server_id="server", roles=[{"ID": "role"}])
            )
            due_calls: list[str] = []
            wakeups: list[bool] = []
            service = object.__new__(PlatformService)
            service.repo = repo
            service.settings = SimpleNamespace(resolved_data_dir=data_dir)
            service.sessions = SimpleNamespace(
                mark_server_permission_snapshots_due=lambda server_id: due_calls.append(server_id)
            )
            service._permission_inventory_dirty_notifier = lambda: wakeups.append(True)
            initial_manifest = PermissionManifest(
                source="cameo-package-permissions",
                complete=True,
                entries=[
                    PermissionManifestEntry(
                        scope_id="project",
                        scope_type="project",
                        principal_name="engineering",
                        principal_type="group",
                        action="READ",
                        accessible=True,
                    )
                ],
            )
            initial_summary = service.ingest_branch_snapshot(
                BranchSnapshotIngestRequest(
                    serverId="server",
                    projectId="project",
                    projectName="Project",
                    branchId="main",
                    branchName="Main",
                    revisionId="1",
                    sourceUser="publisher",
                    permissionManifest=initial_manifest,
                )
            )
            due_calls.clear()
            wakeups.clear()

            service.ingest_branch_delta(
                BranchDeltaIngestRequest(
                    serverId="server",
                    projectId="project",
                    branchId="main",
                    toRevisionId="2",
                    baseSnapshotHash=initial_summary.snapshot_hash,
                    targetSnapshotHash=initial_summary.snapshot_hash,
                    sourceUser="publisher",
                    permissionManifest=initial_manifest,
                )
            )
            self.assertEqual(due_calls, [])

            changed_manifest = initial_manifest.model_copy(
                update={
                    "entries": [
                        initial_manifest.entries[0].model_copy(update={"editable": True, "action": "READ_WRITE"})
                    ]
                }
            )
            service.ingest_branch_delta(
                BranchDeltaIngestRequest(
                    serverId="server",
                    projectId="project",
                    branchId="main",
                    toRevisionId="3",
                    baseSnapshotHash=initial_summary.snapshot_hash,
                    targetSnapshotHash=initial_summary.snapshot_hash,
                    sourceUser="publisher",
                    permissionManifest=changed_manifest,
                )
            )
            self.assertEqual(due_calls, ["server"])

            record = service.tombstone_ingested_branch(
                BranchTombstoneRequest(
                    serverId="server",
                    projectId="project",
                    branchId="main",
                    expectedRevisionId="3",
                    sourceUser="publisher",
                    reason="Deleted from Teamwork Cloud",
                )
            )

            self.assertIsNone(repo.get_branch_cache_summary("server", "project", "main"))
            self.assertEqual(repo.list_branch_tombstones("server")[0].id, record.id)
            self.assertFalse(
                service._branch_access_manifest_file_path("server", "project", "main").exists()
            )
            self.assertTrue(repo.get_server_permission_inventory("server").dirty)
            self.assertEqual(wakeups, [True])

            for branch_id in ("one", "two"):
                service.ingest_branch_snapshot(
                    BranchSnapshotIngestRequest(
                        serverId="server",
                        projectId="project-2",
                        projectName="Project 2",
                        branchId=branch_id,
                        branchName=branch_id.title(),
                        revisionId="1",
                        sourceUser="publisher",
                        permissionManifest=initial_manifest,
                    )
                )
            project_record = service.tombstone_ingested_project(
                ProjectTombstoneRequest(
                    serverId="server",
                    projectId="project-2",
                    expectedBranchIds=["one", "two"],
                    sourceUser="publisher",
                    reason="Project deleted from Teamwork Cloud",
                )
            )
            self.assertEqual(project_record.branch_ids, ["one", "two"])
            self.assertFalse(
                [item for item in repo.list_branch_cache_summaries("server") if item.project_id == "project-2"]
            )
            self.assertEqual(repo.list_project_tombstones("server")[0].id, project_record.id)


class ServerPermissionInventoryCadenceTests(unittest.IsolatedAsyncioTestCase):
    def test_only_twc_server_administrator_role_enables_global_inventory_refresh(self) -> None:
        service = object.__new__(PlatformService)
        server_admin = SimpleNamespace(
            authorization_context=SimpleNamespace(roles=["Server Administrator"], permissions=[]),
        )
        app_admin_only = SimpleNamespace(
            authorization_context=SimpleNamespace(roles=["Application Administrator"], permissions=[]),
        )
        uuid_role_with_server_permission = SimpleNamespace(
            authorization_context=SimpleNamespace(
                roles=[],
                permissions=[SimpleNamespace(name="Configure Server", operation_name="", display_name="")],
            ),
        )

        self.assertTrue(service._is_twc_server_administrator(server_admin))
        self.assertFalse(service._is_twc_server_administrator(app_admin_only))
        self.assertTrue(service._is_twc_server_administrator(uuid_role_with_server_permission))

    async def test_fresh_inventory_is_reused_for_six_hours(self) -> None:
        inventory = ServerPermissionInventory(
            server_id="server",
            roles=[{"ID": "role-1"}],
            groups=[{"ID": "group-1"}],
            captured_at=datetime.now(UTC),
        )
        service = object.__new__(PlatformService)
        service.settings = SimpleNamespace(permission_inventory_refresh_hours=6)
        service._permission_inventory_locks = {}
        service.repo = SimpleNamespace(get_server_permission_inventory=lambda server_id: inventory)
        adapter = SimpleNamespace(
            _admin_roles=AsyncMock(),
            _admin_usergroups=AsyncMock(),
        )

        result = await service._server_permission_inventory(adapter, "server")

        self.assertIs(result, inventory)
        adapter._admin_roles.assert_not_awaited()
        adapter._admin_usergroups.assert_not_awaited()

    async def test_expired_inventory_is_atomically_replaced_from_twc(self) -> None:
        expired = ServerPermissionInventory(
            server_id="server",
            roles=[{"ID": "old-role"}],
            captured_at=datetime.now(UTC) - timedelta(hours=7),
        )
        stored: list[ServerPermissionInventory] = []
        service = object.__new__(PlatformService)
        service.settings = SimpleNamespace(permission_inventory_refresh_hours=6)
        service._permission_inventory_locks = {}
        service.repo = SimpleNamespace(
            get_server_permission_inventory=lambda server_id: stored[-1] if stored else expired,
            upsert_server_permission_inventory=lambda inventory: stored.append(inventory),
        )
        adapter = SimpleNamespace(
            _admin_roles=AsyncMock(return_value=[{"ID": "new-role"}]),
            _admin_usergroups=AsyncMock(return_value=[{"ID": "new-group"}]),
        )

        result = await service._server_permission_inventory(adapter, "server")

        self.assertEqual(result.roles, [{"ID": "new-role"}])
        self.assertEqual(result.groups, [{"ID": "new-group"}])
        self.assertEqual(stored, [result])

    async def test_dirty_inventory_is_replaced_even_inside_six_hour_window(self) -> None:
        dirty = ServerPermissionInventory(
            server_id="server",
            roles=[{"ID": "old-role"}],
            captured_at=datetime.now(UTC),
            dirty=True,
        )
        stored: list[ServerPermissionInventory] = []
        service = object.__new__(PlatformService)
        service.settings = SimpleNamespace(permission_inventory_refresh_hours=6)
        service._permission_inventory_locks = {}
        service.repo = SimpleNamespace(
            get_server_permission_inventory=lambda server_id: stored[-1] if stored else dirty,
            upsert_server_permission_inventory=lambda inventory: stored.append(inventory),
        )
        adapter = SimpleNamespace(
            _admin_roles=AsyncMock(return_value=[{"ID": "new-role"}]),
            _admin_usergroups=AsyncMock(return_value=[{"ID": "new-group"}]),
        )

        result = await service._server_permission_inventory(adapter, "server", allow_refresh=True)

        self.assertFalse(result.dirty)
        self.assertEqual(result.roles, [{"ID": "new-role"}])
        adapter._admin_roles.assert_awaited_once()
        adapter._admin_usergroups.assert_awaited_once()

    async def test_admin_inventory_failure_retains_dirty_complete_inventory(self) -> None:
        dirty = ServerPermissionInventory(
            server_id="server",
            roles=[{"ID": "server-admin", "name": "Server Administrator"}],
            groups=[{"ID": "engineering", "name": "Engineering"}],
            captured_at=datetime.now(UTC),
            dirty=True,
        )
        service = object.__new__(PlatformService)
        service.settings = SimpleNamespace(permission_inventory_refresh_hours=6)
        service._permission_inventory_locks = {}
        service.repo = SimpleNamespace(get_server_permission_inventory=lambda server_id: dirty)
        service._permission_error_text = lambda exc: str(exc)
        adapter = SimpleNamespace(
            _admin_roles=AsyncMock(side_effect=RuntimeError("temporary gateway failure")),
            _admin_usergroups=AsyncMock(return_value=[]),
        )

        result = await service._server_permission_inventory(adapter, "server", allow_refresh=True)

        self.assertIs(result, dirty)
        self.assertTrue(result.dirty)
        self.assertEqual(result.groups[0]["name"], "Engineering")

    async def test_manual_user_refresh_reuses_stale_inventory_without_global_api_calls(self) -> None:
        inventory = ServerPermissionInventory(
            server_id="server",
            roles=[{"ID": "role-1"}],
            captured_at=datetime.now(UTC) - timedelta(hours=7),
        )
        service = object.__new__(PlatformService)
        service.settings = SimpleNamespace(permission_inventory_refresh_hours=6)
        service._permission_inventory_locks = {}
        service.repo = SimpleNamespace(get_server_permission_inventory=lambda server_id: inventory)
        adapter = SimpleNamespace(
            _admin_roles=AsyncMock(),
            _admin_usergroups=AsyncMock(),
        )

        result = await service._server_permission_inventory(adapter, "server", allow_refresh=False)

        self.assertIs(result, inventory)
        adapter._admin_roles.assert_not_awaited()
        adapter._admin_usergroups.assert_not_awaited()

    def test_dirty_inventory_is_queued_as_a_background_job_for_server_admin(self) -> None:
        dirty = ServerPermissionInventory(server_id="server", dirty=True)
        submitted: list[tuple[JobRecord, object]] = []
        service = object.__new__(PlatformService)
        service.settings = SimpleNamespace(permission_inventory_refresh_hours=6)
        service.repo = SimpleNamespace(
            get_server_permission_inventory=lambda server_id: dirty,
            list_jobs=lambda: [],
        )
        service.jobs = SimpleNamespace(
            create_job=lambda **kwargs: JobRecord(**kwargs),
            submit=lambda job, handler: submitted.append((job, handler)) or job,
        )
        session = SimpleNamespace(
            session_id="session",
            server=SimpleNamespace(id="server"),
            user=SimpleNamespace(preferred_username="admin"),
            authorization_context=SimpleNamespace(roles=["Server Administrator"], permissions=[]),
        )

        result = service._submit_server_permission_inventory_refresh(
            session,
            reason="server-administrator-login",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.job_type, JobType.PERMISSION_INVENTORY_REFRESH)
        self.assertEqual(result.payload["reason"], "server-administrator-login")
        self.assertEqual(len(submitted), 1)

    async def test_background_cadence_uses_only_active_server_administrator_sessions(self) -> None:
        service = object.__new__(PlatformService)
        admin = SimpleNamespace(
            session_id="admin-session",
            server=SimpleNamespace(id="server"),
            user=SimpleNamespace(preferred_username="admin"),
            authorization_context=SimpleNamespace(roles=["Server Administrator"], permissions=[]),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        regular = SimpleNamespace(
            session_id="user-session",
            server=SimpleNamespace(id="other-server"),
            user=SimpleNamespace(preferred_username="user"),
            authorization_context=SimpleNamespace(roles=["Resource Manager"], permissions=[]),
            expires_at=datetime.now(UTC) + timedelta(hours=2),
        )
        service.sessions = SimpleNamespace(list_active_sessions=lambda: [regular, admin])
        submitted: list[tuple[object, str]] = []
        service._submit_server_permission_inventory_refresh = lambda session, *, reason: submitted.append((session, reason))

        await service.refresh_due_server_permission_inventories()

        self.assertEqual(submitted, [(admin, "active-administrator-dirty-inventory")])

    def test_inventory_status_reports_failed_dirty_refresh_without_discarding_counts(self) -> None:
        dirty = ServerPermissionInventory(
            server_id="server",
            roles=[{"ID": "role"}],
            groups=[{"ID": "group"}],
            dirty=True,
        )
        failed = JobRecord(
            job_type=JobType.PERMISSION_INVENTORY_REFRESH,
            status=JobStatus.FAILED,
            title="Refresh inventory",
            owner="admin",
            server_id="server",
            payload={},
            message="gateway unavailable",
        )
        service = object.__new__(PlatformService)
        service.settings = SimpleNamespace(permission_inventory_refresh_hours=6)
        service.repo = SimpleNamespace(
            get_server_permission_inventory=lambda server_id: dirty,
            list_jobs=lambda: [failed],
            list_server_permission_inventory_audit=lambda server_id, limit: [],
            server_permission_inventory_audit_counts=lambda server_id: {"succeeded": 0, "failed": 0, "coalesced": 0},
        )
        service.sessions = SimpleNamespace(list_active_sessions=lambda: [])
        session = SimpleNamespace(
            server=SimpleNamespace(id="server"),
            authorization_context=SimpleNamespace(roles=["Server Administrator"], permissions=[]),
        )

        status = service.permission_inventory_status(session)

        self.assertEqual(status.state, "failed")
        self.assertEqual(status.role_count, 1)
        self.assertEqual(status.group_count, 1)
        self.assertEqual(status.last_failure, "gateway unavailable")
        self.assertTrue(status.current_user_can_refresh)
        self.assertIn("no active", status.warning.lower())

    async def test_force_inventory_refresh_bypasses_fresh_cache(self) -> None:
        fresh = ServerPermissionInventory(server_id="server", roles=[{"ID": "old"}])
        stored: list[ServerPermissionInventory] = []
        service = object.__new__(PlatformService)
        service.settings = SimpleNamespace(permission_inventory_refresh_hours=6)
        service._permission_inventory_locks = {}
        service.repo = SimpleNamespace(
            get_server_permission_inventory=lambda server_id: stored[-1] if stored else fresh,
            upsert_server_permission_inventory=lambda inventory: stored.append(inventory),
        )
        service.sessions = SimpleNamespace(mark_server_permission_snapshots_due=lambda server_id: None)
        adapter = SimpleNamespace(
            _admin_roles=AsyncMock(return_value=[{"ID": "new"}]),
            _admin_usergroups=AsyncMock(return_value=[]),
        )

        result = await service._server_permission_inventory(adapter, "server", force_refresh=True)

        self.assertEqual(result.roles, [{"ID": "new"}])
        adapter._admin_roles.assert_awaited_once()

    async def test_repeated_inventory_failures_forward_only_sanitized_alert_metadata(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            repo = SqliteRepository(Path(directory) / "workbench.db")
            for index in range(3):
                repo.append_server_permission_inventory_audit(
                    ServerPermissionInventoryAuditRecord(
                        server_id="server",
                        job_id=f"job-{index}",
                        triggered_by="admin",
                        reason="scheduled",
                        status="failed",
                        error="gateway unavailable",
                    )
                )
            service = object.__new__(PlatformService)
            service.repo = repo
            service.settings = SimpleNamespace(
                permission_alert_webhook_url="https://alerts.example/workbench",
                permission_refresh_warning_failures=3,
            )
            captured: list[dict[str, object]] = []

            class FakeResponse:
                def raise_for_status(self) -> None:
                    return None

            class FakeClient:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, exc_type, exc, traceback):
                    return False

                async def post(self, url, *, json):
                    captured.append({"url": url, "json": json})
                    return FakeResponse()

            with patch("app.services.platform.httpx.AsyncClient", return_value=FakeClient()):
                await service._forward_permission_inventory_failure_alert(
                    server_id="server",
                    job_id="job-2",
                    triggered_by="admin",
                    reason="scheduled",
                    error="gateway unavailable",
                )

            self.assertEqual(len(captured), 1)
            payload = captured[0]["json"]
            self.assertEqual(payload["consecutive_failures"], 3)
            self.assertNotIn("roles", payload)
            self.assertNotIn("groups", payload)

if __name__ == "__main__":
    unittest.main()
