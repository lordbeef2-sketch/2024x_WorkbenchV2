from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Iterable

from app.models.domain import JobRecord, ServerProfile


class SqliteRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._lock = threading.RLock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS servers (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    server_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def list_servers(self) -> list[ServerProfile]:
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT payload FROM servers").fetchall()
        servers = [ServerProfile.model_validate_json(row["payload"]) for row in rows]
        return sorted(
            servers,
            key=lambda item: (
                not item.favorite,
                item.last_used_at is None,
                item.last_used_at.isoformat() if item.last_used_at else "",
                item.name.lower(),
            ),
        )

    def get_server(self, server_id: str) -> ServerProfile | None:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT payload FROM servers WHERE id = ?", (server_id,)).fetchone()
        if not row:
            return None
        return ServerProfile.model_validate_json(row["payload"])

    def upsert_server(self, server: ServerProfile) -> ServerProfile:
        payload = server.model_dump_json()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO servers (id, payload) VALUES (?, ?)",
                (server.id, payload),
            )
            connection.commit()
        return server

    def delete_server(self, server_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM servers WHERE id = ?", (server_id,))
            connection.commit()
        return cursor.rowcount > 0

    def list_jobs(self, owner: str | None = None) -> list[JobRecord]:
        query = "SELECT payload FROM jobs"
        params: tuple[str, ...] = ()
        if owner:
            query += " WHERE owner = ?"
            params = (owner,)

        with self._lock, self._connect() as connection:
            rows = connection.execute(query, params).fetchall()

        jobs = [JobRecord.model_validate_json(row["payload"]) for row in rows]
        return sorted(jobs, key=lambda item: item.created_at, reverse=True)

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT payload FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        return JobRecord.model_validate_json(row["payload"])

    def upsert_job(self, job: JobRecord) -> JobRecord:
        payload = job.model_dump_json()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO jobs (id, job_type, status, owner, server_id, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.job_type.value,
                    job.status.value,
                    job.owner,
                    job.server_id,
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                    payload,
                ),
            )
            connection.commit()
        return job

    def bulk_upsert_jobs(self, jobs: Iterable[JobRecord]) -> None:
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO jobs (id, job_type, status, owner, server_id, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        job.id,
                        job.job_type.value,
                        job.status.value,
                        job.owner,
                        job.server_id,
                        job.created_at.isoformat(),
                        job.updated_at.isoformat(),
                        job.model_dump_json(),
                    )
                    for job in jobs
                ],
            )
            connection.commit()

    def dump_state(self) -> dict[str, list[dict[str, object]]]:
        return {
            "servers": [json.loads(item.model_dump_json()) for item in self.list_servers()],
            "jobs": [json.loads(item.model_dump_json()) for item in self.list_jobs()],
        }
