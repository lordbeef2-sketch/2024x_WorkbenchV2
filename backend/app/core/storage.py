from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Iterable

from app.models.domain import (
    BranchWebhookRegistration,
    BranchCacheSummary,
    CachedElementQueryResponse,
    CachedElementRecord,
    CachedModelRecord,
    JobRecord,
    ModelPermissionSnapshot,
    PresetServerDefinition,
    ServerProfile,
    UserServerState,
    utcnow,
)


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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_server_state (
                    user_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_data_cache (
                    user_id TEXT NOT NULL,
                    server_id TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, server_id, cache_key)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS app_secrets (
                    scope TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS twc_branch_cache (
                    server_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    branch_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (server_id, project_id, branch_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS twc_cached_models (
                    server_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    branch_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (server_id, project_id, branch_id, model_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS twc_cached_model_permissions (
                    user_id TEXT NOT NULL,
                    server_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    branch_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    accessible INTEGER NOT NULL,
                    restricted INTEGER NOT NULL,
                    editable INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (user_id, server_id, project_id, branch_id, model_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS twc_cached_elements (
                    server_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    branch_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    element_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    path TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (server_id, project_id, branch_id, model_id, element_id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_twc_cached_elements_branch
                ON twc_cached_elements (server_id, project_id, branch_id, model_id, name)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_twc_cached_elements_search
                ON twc_cached_elements (server_id, project_id, branch_id, name, path)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS twc_webhook_registrations (
                    registration_id TEXT PRIMARY KEY,
                    server_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    branch_id TEXT NOT NULL,
                    webhook_id TEXT,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE (server_id, project_id, branch_id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_twc_webhook_registrations_server
                ON twc_webhook_registrations (server_id, project_id, branch_id)
                """
            )
            connection.commit()

    def list_servers(self, *, include_disabled: bool = False) -> list[ServerProfile]:
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT payload FROM servers").fetchall()
        servers = [ServerProfile.model_validate_json(row["payload"]) for row in rows]
        if not include_disabled:
            servers = [server for server in servers if server.enabled]
        return sorted(
            servers,
            key=lambda item: (
                item.display_order,
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

    def bulk_upsert_servers(self, servers: Iterable[ServerProfile]) -> list[ServerProfile]:
        items = list(servers)
        with self._lock, self._connect() as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO servers (id, payload) VALUES (?, ?)",
                [(server.id, server.model_dump_json()) for server in items],
            )
            connection.commit()
        return self.list_servers(include_disabled=True)

    def sync_servers(self, definitions: Iterable[PresetServerDefinition]) -> list[ServerProfile]:
        items = list(definitions)
        valid_server_ids = {item.id for item in items}
        existing_servers = {server.id: server for server in self.list_servers(include_disabled=True)}
        synced_servers: list[ServerProfile] = []

        for definition in items:
            current = existing_servers.get(definition.id)
            synced_servers.append(
                ServerProfile(
                    id=definition.id,
                    name=definition.name,
                    base_url=definition.base_url,
                    version=definition.version,
                    verify_tls=definition.verify_tls,
                    ca_bundle_path=definition.ca_bundle_path,
                    enabled=definition.enabled,
                    display_order=definition.display_order,
                    created_at=current.created_at if current else utcnow(),
                    updated_at=current.updated_at if current else utcnow(),
                )
            )

        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM servers")
            if synced_servers:
                connection.executemany(
                    "INSERT OR REPLACE INTO servers (id, payload) VALUES (?, ?)",
                    [(server.id, server.model_dump_json()) for server in synced_servers],
                )
            self._prune_invalid_user_server_state(connection, valid_server_ids)
            self._prune_invalid_user_cache(connection, valid_server_ids)
            self._prune_invalid_app_secrets(connection, valid_server_ids)
            connection.commit()

        return self.list_servers(include_disabled=True)

    def next_server_display_order(self) -> int:
        servers = self.list_servers(include_disabled=True)
        if not servers:
            return 0
        return max(server.display_order for server in servers) + 1

    def delete_server(self, server_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM servers WHERE id = ?", (server_id,))
            if cursor.rowcount > 0:
                self._remove_server_from_user_state(connection, server_id)
                connection.execute("DELETE FROM user_data_cache WHERE server_id = ?", (server_id,))
                connection.execute("DELETE FROM app_secrets WHERE scope = ?", (self._oslc_shared_scope(server_id),))
                self._delete_materialized_cache_for_server(connection, server_id)
            connection.commit()
        return cursor.rowcount > 0

    def get_user_server_state(self, user_id: str) -> UserServerState | None:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT payload FROM user_server_state WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            return None
        return UserServerState.model_validate_json(row["payload"])

    def upsert_user_server_state(self, state: UserServerState) -> UserServerState:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO user_server_state (user_id, payload) VALUES (?, ?)",
                (state.user_id, state.model_dump_json()),
            )
            connection.commit()
        return state

    def _remove_server_from_user_state(self, connection: sqlite3.Connection, server_id: str) -> None:
        rows = connection.execute("SELECT user_id, payload FROM user_server_state").fetchall()
        updates: list[tuple[str, str]] = []
        for row in rows:
            state = UserServerState.model_validate_json(row["payload"])
            changed = False
            if state.selected_server_id == server_id:
                state.selected_server_id = None
                changed = True
            if state.last_used_server_id == server_id:
                state.last_used_server_id = None
                changed = True
            favorite_ids = [value for value in state.favorite_server_ids if value != server_id]
            if favorite_ids != state.favorite_server_ids:
                state.favorite_server_ids = favorite_ids
                changed = True
            if changed:
                state.updated_at = utcnow()
                updates.append((state.user_id, state.model_dump_json()))

        if updates:
            connection.executemany(
                "INSERT OR REPLACE INTO user_server_state (user_id, payload) VALUES (?, ?)",
                updates,
            )

    def get_user_cache(self, user_id: str, server_id: str, cache_key: str):
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM user_data_cache WHERE user_id = ? AND server_id = ? AND cache_key = ?",
                (user_id, server_id, cache_key),
            ).fetchone()
        if not row:
            return None
        return json.loads(row["payload"])

    def upsert_user_cache(self, user_id: str, server_id: str, cache_key: str, payload: object) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO user_data_cache (user_id, server_id, cache_key, payload, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, server_id, cache_key, json.dumps(payload), utcnow().isoformat()),
            )
            connection.commit()

    def delete_user_cache(self, user_id: str, server_id: str, cache_key: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM user_data_cache WHERE user_id = ? AND server_id = ? AND cache_key = ?",
                (user_id, server_id, cache_key),
            )
            connection.commit()

    def delete_user_cache_prefix(self, user_id: str, server_id: str, cache_key_prefix: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM user_data_cache WHERE user_id = ? AND server_id = ? AND cache_key LIKE ?",
                (user_id, server_id, f"{cache_key_prefix}%"),
            )
            connection.commit()

    def get_app_secret(self, scope: str) -> tuple[str, str] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT payload, updated_at FROM app_secrets WHERE scope = ?", (scope,)).fetchone()
        if not row:
            return None
        return str(row["payload"]), str(row["updated_at"])

    def upsert_app_secret(self, scope: str, payload: str) -> str:
        updated_at = utcnow().isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO app_secrets (scope, payload, updated_at) VALUES (?, ?, ?)",
                (scope, payload, updated_at),
            )
            connection.commit()
        return updated_at

    def delete_app_secret(self, scope: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM app_secrets WHERE scope = ?", (scope,))
            connection.commit()

    def get_branch_webhook_registration(
        self,
        server_id: str,
        project_id: str,
        branch_id: str,
    ) -> BranchWebhookRegistration | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM twc_webhook_registrations
                WHERE server_id = ? AND project_id = ? AND branch_id = ?
                """,
                (server_id, project_id, branch_id),
            ).fetchone()
        if not row:
            return None
        return BranchWebhookRegistration.model_validate_json(row["payload"])

    def get_branch_webhook_registration_by_id(self, registration_id: str) -> BranchWebhookRegistration | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM twc_webhook_registrations WHERE registration_id = ?",
                (registration_id,),
            ).fetchone()
        if not row:
            return None
        return BranchWebhookRegistration.model_validate_json(row["payload"])

    def upsert_branch_webhook_registration(self, registration: BranchWebhookRegistration) -> BranchWebhookRegistration:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO twc_webhook_registrations (
                    registration_id, server_id, project_id, branch_id, webhook_id, status, updated_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    registration.registration_id,
                    registration.server_id,
                    registration.project_id,
                    registration.branch_id,
                    registration.webhook_id,
                    registration.status.value,
                    registration.updated_at.isoformat(),
                    registration.model_dump_json(),
                ),
            )
            connection.commit()
        return registration

    def delete_branch_webhook_registration(self, server_id: str, project_id: str, branch_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM twc_webhook_registrations WHERE server_id = ? AND project_id = ? AND branch_id = ?",
                (server_id, project_id, branch_id),
            )
            connection.commit()

    def get_branch_cache_summary(self, server_id: str, project_id: str, branch_id: str) -> BranchCacheSummary | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM twc_branch_cache
                WHERE server_id = ? AND project_id = ? AND branch_id = ?
                """,
                (server_id, project_id, branch_id),
            ).fetchone()
        if not row:
            return None
        return BranchCacheSummary.model_validate_json(row["payload"])

    def upsert_branch_cache_summary(self, summary: BranchCacheSummary) -> BranchCacheSummary:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO twc_branch_cache (server_id, project_id, branch_id, status, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    summary.server_id,
                    summary.project_id,
                    summary.branch_id,
                    summary.status.value,
                    summary.updated_at.isoformat(),
                    summary.model_dump_json(),
                ),
            )
            connection.commit()
        return summary

    def delete_branch_cache(self, server_id: str, project_id: str, branch_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM twc_branch_cache WHERE server_id = ? AND project_id = ? AND branch_id = ?",
                (server_id, project_id, branch_id),
            )
            connection.execute(
                "DELETE FROM twc_webhook_registrations WHERE server_id = ? AND project_id = ? AND branch_id = ?",
                (server_id, project_id, branch_id),
            )
            connection.execute(
                "DELETE FROM twc_cached_models WHERE server_id = ? AND project_id = ? AND branch_id = ?",
                (server_id, project_id, branch_id),
            )
            connection.execute(
                "DELETE FROM twc_cached_model_permissions WHERE server_id = ? AND project_id = ? AND branch_id = ?",
                (server_id, project_id, branch_id),
            )
            connection.execute(
                "DELETE FROM twc_cached_elements WHERE server_id = ? AND project_id = ? AND branch_id = ?",
                (server_id, project_id, branch_id),
            )
            connection.commit()

    def list_cached_models(self, server_id: str, project_id: str, branch_id: str) -> list[CachedModelRecord]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM twc_cached_models
                WHERE server_id = ? AND project_id = ? AND branch_id = ?
                ORDER BY LOWER(name), model_id
                """,
                (server_id, project_id, branch_id),
            ).fetchall()
        return [CachedModelRecord.model_validate_json(row["payload"]) for row in rows]

    def get_cached_model(self, server_id: str, project_id: str, branch_id: str, model_id: str) -> CachedModelRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM twc_cached_models
                WHERE server_id = ? AND project_id = ? AND branch_id = ? AND model_id = ?
                """,
                (server_id, project_id, branch_id, model_id),
            ).fetchone()
        if not row:
            return None
        return CachedModelRecord.model_validate_json(row["payload"])

    def upsert_cached_models(self, records: Iterable[CachedModelRecord]) -> None:
        items = list(records)
        if not items:
            return
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO twc_cached_models (server_id, project_id, branch_id, model_id, name, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.server_id,
                        item.project_id,
                        item.branch_id,
                        item.model_id,
                        item.name,
                        item.synced_at.isoformat(),
                        item.model_dump_json(),
                    )
                    for item in items
                ],
            )
            connection.commit()

    def get_model_permission(
        self,
        user_id: str,
        server_id: str,
        project_id: str,
        branch_id: str,
        model_id: str,
    ) -> ModelPermissionSnapshot | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM twc_cached_model_permissions
                WHERE user_id = ? AND server_id = ? AND project_id = ? AND branch_id = ? AND model_id = ?
                """,
                (user_id, server_id, project_id, branch_id, model_id),
            ).fetchone()
        if not row:
            return None
        return ModelPermissionSnapshot.model_validate_json(row["payload"])

    def list_model_permissions(
        self,
        user_id: str,
        server_id: str,
        project_id: str,
        branch_id: str,
    ) -> list[ModelPermissionSnapshot]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM twc_cached_model_permissions
                WHERE user_id = ? AND server_id = ? AND project_id = ? AND branch_id = ?
                ORDER BY model_id
                """,
                (user_id, server_id, project_id, branch_id),
            ).fetchall()
        return [ModelPermissionSnapshot.model_validate_json(row["payload"]) for row in rows]

    def upsert_model_permissions(self, records: Iterable[ModelPermissionSnapshot]) -> None:
        items = list(records)
        if not items:
            return
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO twc_cached_model_permissions (
                    user_id, server_id, project_id, branch_id, model_id,
                    accessible, restricted, editable, updated_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.user_id,
                        item.server_id,
                        item.project_id,
                        item.branch_id,
                        item.model_id,
                        int(item.accessible),
                        int(item.restricted),
                        int(item.editable),
                        item.updated_at.isoformat(),
                        item.model_dump_json(),
                    )
                    for item in items
                ],
            )
            connection.commit()

    def replace_model_permissions_for_user_branch(
        self,
        user_id: str,
        server_id: str,
        project_id: str,
        branch_id: str,
        records: Iterable[ModelPermissionSnapshot],
    ) -> None:
        items = list(records)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                DELETE FROM twc_cached_model_permissions
                WHERE user_id = ? AND server_id = ? AND project_id = ? AND branch_id = ?
                """,
                (user_id, server_id, project_id, branch_id),
            )
            if items:
                connection.executemany(
                    """
                    INSERT OR REPLACE INTO twc_cached_model_permissions (
                        user_id, server_id, project_id, branch_id, model_id,
                        accessible, restricted, editable, updated_at, payload
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            item.user_id,
                            item.server_id,
                            item.project_id,
                            item.branch_id,
                            item.model_id,
                            int(item.accessible),
                            int(item.restricted),
                            int(item.editable),
                            item.updated_at.isoformat(),
                            item.model_dump_json(),
                        )
                        for item in items
                    ],
                )
            connection.commit()

    def replace_cached_elements(
        self,
        server_id: str,
        project_id: str,
        branch_id: str,
        model_id: str,
        records: Iterable[CachedElementRecord],
    ) -> int:
        items = list(records)
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM twc_cached_elements WHERE server_id = ? AND project_id = ? AND branch_id = ? AND model_id = ?",
                (server_id, project_id, branch_id, model_id),
            )
            if items:
                connection.executemany(
                    """
                    INSERT OR REPLACE INTO twc_cached_elements (
                        server_id, project_id, branch_id, model_id, element_id,
                        name, item_type, path, updated_at, payload
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            item.server_id,
                            item.project_id,
                            item.branch_id,
                            item.model_id,
                            item.element_id,
                            item.name,
                            item.item_type,
                            item.path,
                            item.synced_at.isoformat(),
                            item.model_dump_json(),
                        )
                        for item in items
                    ],
            )
            connection.commit()
        return len(items)

    def upsert_cached_elements(self, records: Iterable[CachedElementRecord]) -> int:
        items = list(records)
        if not items:
            return 0
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO twc_cached_elements (
                    server_id, project_id, branch_id, model_id, element_id,
                    name, item_type, path, updated_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.server_id,
                        item.project_id,
                        item.branch_id,
                        item.model_id,
                        item.element_id,
                        item.name,
                        item.item_type,
                        item.path,
                        item.synced_at.isoformat(),
                        item.model_dump_json(),
                    )
                    for item in items
                ],
            )
            connection.commit()
        return len(items)

    def delete_cached_elements_by_ids(
        self,
        server_id: str,
        project_id: str,
        branch_id: str,
        element_ids: Iterable[str],
    ) -> None:
        ids = [element_id for element_id in dict.fromkeys(element_ids) if element_id]
        if not ids:
            return
        placeholders = ", ".join("?" for _ in ids)
        with self._lock, self._connect() as connection:
            connection.execute(
                f"""
                DELETE FROM twc_cached_elements
                WHERE server_id = ? AND project_id = ? AND branch_id = ? AND element_id IN ({placeholders})
                """,
                (server_id, project_id, branch_id, *ids),
            )
            connection.commit()

    def delete_cached_models_by_ids(
        self,
        server_id: str,
        project_id: str,
        branch_id: str,
        model_ids: Iterable[str],
    ) -> None:
        ids = [model_id for model_id in dict.fromkeys(model_ids) if model_id]
        if not ids:
            return
        placeholders = ", ".join("?" for _ in ids)
        with self._lock, self._connect() as connection:
            connection.execute(
                f"""
                DELETE FROM twc_cached_models
                WHERE server_id = ? AND project_id = ? AND branch_id = ? AND model_id IN ({placeholders})
                """,
                (server_id, project_id, branch_id, *ids),
            )
            connection.execute(
                f"""
                DELETE FROM twc_cached_model_permissions
                WHERE server_id = ? AND project_id = ? AND branch_id = ? AND model_id IN ({placeholders})
                """,
                (server_id, project_id, branch_id, *ids),
            )
            connection.execute(
                f"""
                DELETE FROM twc_cached_elements
                WHERE server_id = ? AND project_id = ? AND branch_id = ? AND model_id IN ({placeholders})
                """,
                (server_id, project_id, branch_id, *ids),
            )
            connection.commit()

    def count_cached_elements_for_model(self, server_id: str, project_id: str, branch_id: str, model_id: str) -> int:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total FROM twc_cached_elements
                WHERE server_id = ? AND project_id = ? AND branch_id = ? AND model_id = ?
                """,
                (server_id, project_id, branch_id, model_id),
            ).fetchone()
        return int(row["total"]) if row else 0

    def count_cached_elements_for_branch(self, server_id: str, project_id: str, branch_id: str) -> int:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total FROM twc_cached_elements
                WHERE server_id = ? AND project_id = ? AND branch_id = ?
                """,
                (server_id, project_id, branch_id),
            ).fetchone()
        return int(row["total"]) if row else 0

    def list_branch_cache_summaries(self, server_id: str | None = None) -> list[BranchCacheSummary]:
        query = "SELECT payload FROM twc_branch_cache"
        params: tuple[object, ...] = ()
        if server_id is not None:
            query += " WHERE server_id = ?"
            params = (server_id,)
        query += " ORDER BY project_id, branch_id"
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [BranchCacheSummary.model_validate_json(row["payload"]) for row in rows]

    def delete_branch_models_except(
        self,
        server_id: str,
        project_id: str,
        branch_id: str,
        model_ids: Iterable[str],
    ) -> None:
        kept_ids = [model_id for model_id in dict.fromkeys(model_ids) if model_id]
        with self._lock, self._connect() as connection:
            if not kept_ids:
                connection.execute(
                    "DELETE FROM twc_cached_models WHERE server_id = ? AND project_id = ? AND branch_id = ?",
                    (server_id, project_id, branch_id),
                )
                connection.execute(
                    "DELETE FROM twc_cached_model_permissions WHERE server_id = ? AND project_id = ? AND branch_id = ?",
                    (server_id, project_id, branch_id),
                )
                connection.execute(
                    "DELETE FROM twc_cached_elements WHERE server_id = ? AND project_id = ? AND branch_id = ?",
                    (server_id, project_id, branch_id),
                )
                connection.commit()
                return

            placeholders = ", ".join("?" for _ in kept_ids)
            params = (server_id, project_id, branch_id, *kept_ids)
            connection.execute(
                f"DELETE FROM twc_cached_models WHERE server_id = ? AND project_id = ? AND branch_id = ? AND model_id NOT IN ({placeholders})",
                params,
            )
            connection.execute(
                f"DELETE FROM twc_cached_model_permissions WHERE server_id = ? AND project_id = ? AND branch_id = ? AND model_id NOT IN ({placeholders})",
                params,
            )
            connection.execute(
                f"DELETE FROM twc_cached_elements WHERE server_id = ? AND project_id = ? AND branch_id = ? AND model_id NOT IN ({placeholders})",
                params,
            )
            connection.commit()

    def list_cached_elements(
        self,
        server_id: str,
        project_id: str,
        branch_id: str,
        *,
        model_id: str | None = None,
        search: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> CachedElementQueryResponse:
        clauses = ["server_id = ?", "project_id = ?", "branch_id = ?"]
        params: list[object] = [server_id, project_id, branch_id]
        if model_id:
            clauses.append("model_id = ?")
            params.append(model_id)
        if search:
            query = f"%{search.lower()}%"
            clauses.append("(LOWER(name) LIKE ? OR LOWER(path) LIKE ? OR LOWER(item_type) LIKE ? OR LOWER(element_id) LIKE ?)")
            params.extend([query, query, query, query])

        where = " AND ".join(clauses)
        with self._lock, self._connect() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) AS total FROM twc_cached_elements WHERE {where}",
                    tuple(params),
                ).fetchone()["total"]
            )
            rows = connection.execute(
                f"""
                SELECT payload FROM twc_cached_elements
                WHERE {where}
                ORDER BY LOWER(name), element_id
                LIMIT ? OFFSET ?
                """,
                (*params, limit, offset),
            ).fetchall()
        return CachedElementQueryResponse(
            total=total,
            items=[CachedElementRecord.model_validate_json(row["payload"]) for row in rows],
        )

    def get_cached_element(
        self,
        server_id: str,
        project_id: str,
        branch_id: str,
        element_id: str,
        *,
        model_id: str | None = None,
    ) -> CachedElementRecord | None:
        clauses = ["server_id = ?", "project_id = ?", "branch_id = ?", "element_id = ?"]
        params: list[object] = [server_id, project_id, branch_id, element_id]
        if model_id:
            clauses.append("model_id = ?")
            params.append(model_id)
        where = " AND ".join(clauses)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                f"SELECT payload FROM twc_cached_elements WHERE {where} ORDER BY model_id LIMIT 1",
                tuple(params),
            ).fetchone()
        if not row:
            return None
        return CachedElementRecord.model_validate_json(row["payload"])

    def _prune_invalid_user_server_state(self, connection: sqlite3.Connection, valid_server_ids: set[str]) -> None:
        rows = connection.execute("SELECT user_id, payload FROM user_server_state").fetchall()
        updates: list[tuple[str, str]] = []
        for row in rows:
            state = UserServerState.model_validate_json(row["payload"])
            changed = False
            if state.selected_server_id and state.selected_server_id not in valid_server_ids:
                state.selected_server_id = None
                changed = True
            if state.last_used_server_id and state.last_used_server_id not in valid_server_ids:
                state.last_used_server_id = None
                changed = True
            favorite_ids = [value for value in state.favorite_server_ids if value in valid_server_ids]
            if favorite_ids != state.favorite_server_ids:
                state.favorite_server_ids = favorite_ids
                changed = True
            if changed:
                state.updated_at = utcnow()
                updates.append((state.user_id, state.model_dump_json()))

        if updates:
            connection.executemany(
                "INSERT OR REPLACE INTO user_server_state (user_id, payload) VALUES (?, ?)",
                updates,
            )

    def _prune_invalid_user_cache(self, connection: sqlite3.Connection, valid_server_ids: set[str]) -> None:
        if not valid_server_ids:
            connection.execute("DELETE FROM user_data_cache")
            self._delete_materialized_cache_for_all_servers(connection)
            return
        placeholders = ", ".join("?" for _ in valid_server_ids)
        connection.execute(
            f"DELETE FROM user_data_cache WHERE server_id NOT IN ({placeholders})",
            tuple(valid_server_ids),
        )
        self._prune_invalid_materialized_cache(connection, valid_server_ids)

    def _prune_invalid_app_secrets(self, connection: sqlite3.Connection, valid_server_ids: set[str]) -> None:
        valid_scopes = {self._oslc_shared_scope(server_id) for server_id in valid_server_ids}
        rows = connection.execute("SELECT scope FROM app_secrets").fetchall()
        invalid_scopes = [str(row["scope"]) for row in rows if str(row["scope"]) not in valid_scopes]
        if invalid_scopes:
            connection.executemany("DELETE FROM app_secrets WHERE scope = ?", [(scope,) for scope in invalid_scopes])

    def _prune_invalid_materialized_cache(self, connection: sqlite3.Connection, valid_server_ids: set[str]) -> None:
        if not valid_server_ids:
            self._delete_materialized_cache_for_all_servers(connection)
            return
        placeholders = ", ".join("?" for _ in valid_server_ids)
        for table in (
            "twc_branch_cache",
            "twc_cached_models",
            "twc_cached_model_permissions",
            "twc_cached_elements",
            "twc_webhook_registrations",
        ):
            connection.execute(
                f"DELETE FROM {table} WHERE server_id NOT IN ({placeholders})",
                tuple(valid_server_ids),
            )

    def _delete_materialized_cache_for_server(self, connection: sqlite3.Connection, server_id: str) -> None:
        for table in (
            "twc_branch_cache",
            "twc_cached_models",
            "twc_cached_model_permissions",
            "twc_cached_elements",
            "twc_webhook_registrations",
        ):
            connection.execute(f"DELETE FROM {table} WHERE server_id = ?", (server_id,))

    def _delete_materialized_cache_for_all_servers(self, connection: sqlite3.Connection) -> None:
        for table in (
            "twc_branch_cache",
            "twc_cached_models",
            "twc_cached_model_permissions",
            "twc_cached_elements",
            "twc_webhook_registrations",
        ):
            connection.execute(f"DELETE FROM {table}")

    def _oslc_shared_scope(self, server_id: str) -> str:
        return f"oslc-shared:{server_id}"

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
        with self._connect() as connection:
            user_server_state = [json.loads(item["payload"]) for item in connection.execute("SELECT payload FROM user_server_state").fetchall()]
            user_data_cache = [
                {
                    "user_id": item["user_id"],
                    "server_id": item["server_id"],
                    "cache_key": item["cache_key"],
                    "updated_at": item["updated_at"],
                }
                for item in connection.execute("SELECT user_id, server_id, cache_key, updated_at FROM user_data_cache").fetchall()
            ]
        return {
            "servers": [json.loads(item.model_dump_json()) for item in self.list_servers(include_disabled=True)],
            "user_server_state": user_server_state,
            "user_data_cache": user_data_cache,
            "jobs": [json.loads(item.model_dump_json()) for item in self.list_jobs()],
        }
