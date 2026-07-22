from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from app.core.storage import SqliteRepository
from app.models.domain import (
    BranchCacheSummary,
    CachedElementRecord,
    CachedModelRecord,
    FallbackCacheRefreshRequest,
    MaterializedCacheStatus,
    ModelPermissionSnapshot,
)
from app.services.platform import PlatformService


class FallbackCacheTests(unittest.TestCase):
    def test_nightly_window_uses_configured_timezone_and_handles_midnight(self) -> None:
        service = object.__new__(PlatformService)
        service.settings = SimpleNamespace(
            fallback_cache_sync_time="00:00",
            fallback_cache_sync_timezone="America/New_York",
            fallback_cache_sync_window_minutes=60,
        )

        open_window, schedule_date, local_now = service._fallback_cache_window(
            datetime(2026, 7, 22, 4, 30, tzinfo=UTC)
        )
        closed_window, _, _ = service._fallback_cache_window(
            datetime(2026, 7, 22, 6, 0, tzinfo=UTC)
        )

        self.assertTrue(open_window)
        self.assertEqual(schedule_date, "2026-07-22")
        self.assertEqual(local_now.hour, 0)
        self.assertFalse(closed_window)

    def test_manual_trigger_requires_twc_server_administrator(self) -> None:
        service = object.__new__(PlatformService)
        session = SimpleNamespace(
            authorization_context=SimpleNamespace(roles=["Resource Manager"], permissions=[]),
        )

        with self.assertRaises(PermissionError):
            service.trigger_fallback_cache_refresh(session, FallbackCacheRefreshRequest())

    def test_plugin_snapshot_atomically_blocks_fallback_replacement(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            repo = SqliteRepository(Path(directory) / "workbench.db")
            plugin = BranchCacheSummary(
                server_id="server",
                project_id="project",
                branch_id="main",
                source_kind="cameo-plugin",
                status=MaterializedCacheStatus.READY,
                model_count=1,
            )
            repo.upsert_branch_cache_summary(plugin)
            fallback = plugin.model_copy(
                update={"source_kind": "twc-rest", "model_count": 2, "message": "fallback"}
            )
            model = CachedModelRecord(
                server_id="server",
                project_id="project",
                branch_id="main",
                model_id="model",
            )
            permission = ModelPermissionSnapshot(
                user_id="admin",
                server_id="server",
                project_id="project",
                branch_id="main",
                model_id="model",
                accessible=True,
            )
            element = CachedElementRecord(
                server_id="server",
                project_id="project",
                branch_id="main",
                model_id="model",
                element_id="element",
            )

            stored = repo.replace_fallback_branch_snapshot_if_not_plugin(
                fallback,
                [model],
                [permission],
                {"model": [element]},
                permission_user_id="admin",
            )

            self.assertFalse(stored)
            current = repo.get_branch_cache_summary("server", "project", "main")
            self.assertEqual(current.source_kind, "cameo-plugin")
            self.assertEqual(current.model_count, 1)
            self.assertEqual(repo.list_cached_models("server", "project", "main"), [])


if __name__ == "__main__":
    unittest.main()
