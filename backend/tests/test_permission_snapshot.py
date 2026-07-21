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
    ServerProfile,
    SessionData,
    UserContext,
)
from app.services.platform import PlatformService


class PermissionSnapshotReplacementTests(unittest.TestCase):
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


class PermissionAttachmentComparisonTests(unittest.TestCase):
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

    async def test_due_refresh_failure_replaces_snapshot_with_empty_permissions(self) -> None:
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

            def mark_permission_snapshot_attempt(self, item, attempted_at, *, successful):
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

        self.assertEqual(service.repo.replacements, [("alice", "server", [], [])])
        self.assertEqual(service.sessions.marked, [(session.session_id, False)])
        self.assertIn("projects", service.repo.deleted_cache_keys)
        self.assertIn("project:", service.repo.deleted_cache_keys)

if __name__ == "__main__":
    unittest.main()
