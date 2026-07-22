from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from app.core.storage import SqliteRepository
from app.models.domain import (
    BranchAccessRecord,
    BranchCacheSummary,
    BranchPermissionAttachment,
    CapabilitySummary,
    ModelPermissionSnapshot,
    PermissionManifest,
    PermissionManifestEntry,
    PermissionRefreshAuditRecord,
    ServerProfile,
    ServerPermissionInventory,
    SessionData,
    UserContext,
)
from app.services.platform import PermissionSnapshotIndeterminateError, PlatformService


class PermissionSnapshotReplacementTests(unittest.TestCase):
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

if __name__ == "__main__":
    unittest.main()
