from datetime import UTC, datetime, timedelta
import asyncio
from inspect import iscoroutinefunction
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from app.core.storage import SqliteRepository
from app.api.routes.workspace import refresh_fallback_cache, sync_workbench_agent_knowledge
from app.jobs.coordinator import JobCoordinator
from app.models.domain import (
    BranchCacheSummary,
    CachedElementRecord,
    CachedModelRecord,
    FallbackCacheRefreshRequest,
    JobRecord,
    JobStatus,
    JobType,
    MaterializedCacheStatus,
    ModelPermissionSnapshot,
)
from app.services.platform import PlatformService


class FallbackCacheTests(unittest.TestCase):
    def test_nightly_fallback_scheduler_is_disabled(self) -> None:
        service = object.__new__(PlatformService)
        service.sessions = SimpleNamespace(
            list_active_sessions=lambda: self.fail("disabled fallback must not inspect active sessions")
        )

        asyncio.run(service.refresh_due_fallback_caches())

    def test_background_job_routes_run_on_application_event_loop(self) -> None:
        self.assertTrue(iscoroutinefunction(refresh_fallback_cache))
        self.assertTrue(iscoroutinefunction(sync_workbench_agent_knowledge))

    def test_job_submission_without_event_loop_fails_persisted_job(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            repo = SqliteRepository(Path(directory) / "workbench.db")
            coordinator = JobCoordinator(repo)
            job = coordinator.create_job(
                job_type=JobType.FALLBACK_CACHE_REFRESH,
                title="fallback",
                owner="admin",
                server_id="server",
                payload={},
            )

            async def handler(_context):
                return {}

            with self.assertRaisesRegex(RuntimeError, "no application event loop"):
                coordinator.submit(job, handler)

            stored = repo.get_job(job.id)
            self.assertEqual(stored.status, JobStatus.FAILED)
            self.assertIsNotNone(stored.finished_at)

    def test_stale_pending_refresh_is_failed_and_does_not_block_requeue(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            repo = SqliteRepository(Path(directory) / "workbench.db")
            pending = JobRecord(
                job_type=JobType.FALLBACK_CACHE_REFRESH,
                title="fallback",
                owner="admin",
                server_id="server",
                payload={},
                updated_at=datetime.now(UTC) - timedelta(minutes=2),
            )
            repo.upsert_job(pending)
            service = object.__new__(PlatformService)
            service.repo = repo

            active = service._active_fallback_cache_refresh_job("server")

            self.assertIsNone(active)
            stored = repo.get_job(pending.id)
            self.assertEqual(stored.status, JobStatus.FAILED)
            self.assertIn("never started", stored.message)
            self.assertIsNotNone(stored.finished_at)

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

    def test_manual_trigger_is_disabled(self) -> None:
        service = object.__new__(PlatformService)
        session = SimpleNamespace(
            authorization_context=SimpleNamespace(roles=["Resource Manager"], permissions=[]),
        )

        with self.assertRaisesRegex(RuntimeError, "model and element fallback is disabled"):
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
