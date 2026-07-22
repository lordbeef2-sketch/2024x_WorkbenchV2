from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.storage import SqliteRepository
from app.jobs.coordinator import JobCoordinator
from app.models.domain import JobRecord, JobStatus, JobType


def main() -> int:
    with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        database_path = Path(directory) / "multi-worker.sqlite3"
        first = SqliteRepository(database_path)
        second = SqliteRepository(database_path)
        now = datetime.now(UTC)
        fresh = JobRecord(
            job_type=JobType.PERMISSION_INVENTORY_REFRESH,
            status=JobStatus.RUNNING,
            title="Live worker job",
            owner="admin",
            server_id="server",
            payload={},
            updated_at=now,
        )
        stale = JobRecord(
            job_type=JobType.PERMISSION_INVENTORY_REFRESH,
            status=JobStatus.RUNNING,
            title="Abandoned worker job",
            owner="admin",
            server_id="server",
            payload={},
            updated_at=now - timedelta(hours=1),
        )
        first.upsert_job(fresh)
        first.upsert_job(stale)
        recovered = JobCoordinator(second).recover_interrupted_jobs(stale_before=now - timedelta(minutes=30))

        lease_a = first.acquire_permission_refresh_lease("permission-inventory:server", "worker-a", ttl_seconds=60)
        lease_b_blocked = not second.acquire_permission_refresh_lease(
            "permission-inventory:server", "worker-b", ttl_seconds=60
        )
        lease_a_renewed = first.renew_permission_refresh_lease(
            "permission-inventory:server", "worker-a", ttl_seconds=60
        )
        first.release_permission_refresh_lease("permission-inventory:server", "worker-a")
        lease_b_after_release = second.acquire_permission_refresh_lease(
            "permission-inventory:server", "worker-b", ttl_seconds=60
        )
        checks = {
            "stale_job_recovered": [job.id for job in recovered] == [stale.id],
            "fresh_job_preserved": second.get_job(fresh.id).status == JobStatus.RUNNING,
            "lease_acquired_by_first_worker": lease_a,
            "second_worker_blocked": lease_b_blocked,
            "lease_renewed": lease_a_renewed,
            "second_worker_acquired_after_release": lease_b_after_release,
        }
        print(json.dumps({"passed": all(checks.values()), "checks": checks}, indent=2, sort_keys=True))
        return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
