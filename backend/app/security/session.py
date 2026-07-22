from __future__ import annotations

import base64
import hashlib
import json
import threading
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from cryptography.fernet import Fernet
from redis import Redis

from app.models.domain import (
    AuthorizationContext,
    Bookmark,
    OSLCConsumerCredentials,
    OSLCTokenBundle,
    SavedSearch,
    ServerProfile,
    SessionData,
    SessionPreferences,
    SessionSnapshot,
    TokenBundle,
    UserContext,
)
from app.settings.config import Settings


class CredentialCipher:
    def __init__(self, secret: str) -> None:
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest)
        self._fernet = Fernet(key)

    def encrypt_raw(self, payload: bytes) -> str:
        return self._fernet.encrypt(payload).decode("utf-8")

    def decrypt_raw(self, encrypted_value: str) -> bytes:
        return self._fernet.decrypt(encrypted_value.encode("utf-8"))

    def encrypt(self, credentials: TokenBundle) -> str:
        payload = credentials.model_dump_json().encode("utf-8")
        return self.encrypt_raw(payload)

    def decrypt(self, encrypted_credentials: str) -> TokenBundle:
        raw = self.decrypt_raw(encrypted_credentials)
        return TokenBundle.model_validate_json(raw)


class SessionStore:
    def get(self, session_id: str) -> SessionData | None:
        raise NotImplementedError

    def set(self, session: SessionData) -> None:
        raise NotImplementedError

    def delete(self, session_id: str) -> None:
        raise NotImplementedError

    def list_active(self) -> list[SessionData]:
        raise NotImplementedError


class InMemorySessionStore(SessionStore):
    def __init__(self) -> None:
        self._sessions: dict[str, SessionData] = {}
        self._lock = threading.RLock()

    def get(self, session_id: str) -> SessionData | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session and session.expires_at > datetime.now(UTC):
                return session
            if session:
                self._sessions.pop(session_id, None)
            return None

    def set(self, session: SessionData) -> None:
        with self._lock:
            self._sessions[session.session_id] = session

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def list_active(self) -> list[SessionData]:
        now = datetime.now(UTC)
        with self._lock:
            expired = [session_id for session_id, session in self._sessions.items() if session.expires_at <= now]
            for session_id in expired:
                self._sessions.pop(session_id, None)
            return list(self._sessions.values())


class RedisSessionStore(SessionStore):
    def __init__(self, redis_url: str) -> None:
        self._redis = Redis.from_url(redis_url, decode_responses=True)

    def get(self, session_id: str) -> SessionData | None:
        payload = self._redis.get(f"twc:session:{session_id}")
        if not payload:
            return None
        return SessionData.model_validate_json(payload)

    def set(self, session: SessionData) -> None:
        ttl_seconds = max(int((session.expires_at - datetime.now(UTC)).total_seconds()), 1)
        self._redis.setex(f"twc:session:{session.session_id}", ttl_seconds, session.model_dump_json())

    def delete(self, session_id: str) -> None:
        self._redis.delete(f"twc:session:{session_id}")

    def list_active(self) -> list[SessionData]:
        now = datetime.now(UTC)
        sessions: list[SessionData] = []
        for key in self._redis.scan_iter(match="twc:session:*"):
            payload = self._redis.get(key)
            if not payload:
                continue
            try:
                session = SessionData.model_validate_json(payload)
            except Exception:
                continue
            if session.expires_at > now:
                sessions.append(session)
        return sessions


class SessionManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.cipher = CredentialCipher(settings.session_secret)
        self.store: SessionStore = (
            RedisSessionStore(settings.redis_url) if settings.redis_url else InMemorySessionStore()
        )

    def create_session(
        self,
        server: ServerProfile,
        user: UserContext,
        authorization_context: AuthorizationContext,
        credentials: TokenBundle,
        capabilities: Any,
    ) -> SessionData:
        now = datetime.now(UTC)
        session = SessionData(
            session_id=uuid4().hex,
            server=server,
            user=user,
            authorization_context=authorization_context,
            encrypted_credentials=self.cipher.encrypt(credentials),
            capabilities=capabilities,
            created_at=now,
            expires_at=now + timedelta(minutes=self.settings.session_ttl_minutes),
        )
        self.store.set(session)
        return session

    def get_session(self, session_id: str | None) -> SessionData | None:
        if not session_id:
            return None
        session = self.store.get(session_id)
        if not session:
            return None
        if session.expires_at <= datetime.now(UTC):
            self.store.delete(session_id)
            return None

        session.expires_at = datetime.now(UTC) + timedelta(minutes=self.settings.session_ttl_minutes)
        self.store.set(session)
        return session

    def destroy_session(self, session_id: str) -> None:
        self.store.delete(session_id)

    def list_active_sessions(self) -> list[SessionData]:
        return self.store.list_active()

    def mark_permission_snapshot_attempt(
        self,
        session: SessionData,
        attempted_at: datetime,
        *,
        successful: bool,
        error: str | None = None,
    ) -> SessionData:
        session.permission_snapshot_attempted_at = attempted_at
        if successful:
            session.permission_snapshot_refreshed_at = attempted_at
            session.permission_snapshot_failure_count = 0
            session.permission_snapshot_last_error = None
        else:
            session.permission_snapshot_failure_count += 1
            session.permission_snapshot_last_error = error
        self.store.set(session)
        return session

    def mark_server_permission_snapshots_due(self, server_id: str) -> None:
        due_at = datetime.min.replace(tzinfo=UTC)
        for session in self.store.list_active():
            if session.server.id != server_id:
                continue
            session.permission_snapshot_attempted_at = due_at
            self.store.set(session)

    def get_credentials(self, session: SessionData) -> TokenBundle:
        return self.cipher.decrypt(session.encrypted_credentials)

    def update_credentials(self, session: SessionData, credentials: TokenBundle) -> SessionData:
        session.encrypted_credentials = self.cipher.encrypt(credentials)
        self.store.set(session)
        return session

    def get_oslc_credentials(self, session: SessionData) -> OSLCTokenBundle | None:
        if not session.encrypted_oslc_credentials:
            return None
        raw = self.cipher.decrypt_raw(session.encrypted_oslc_credentials)
        return OSLCTokenBundle.model_validate_json(raw)

    def set_oslc_credentials(self, session: SessionData, credentials: OSLCTokenBundle) -> SessionData:
        session.encrypted_oslc_credentials = self.cipher.encrypt_raw(credentials.model_dump_json().encode("utf-8"))
        self.store.set(session)
        return session

    def clear_oslc_credentials(self, session: SessionData) -> SessionData:
        session.encrypted_oslc_credentials = None
        self.store.set(session)
        return session

    def get_oslc_consumer_credentials(self, session: SessionData) -> OSLCConsumerCredentials | None:
        if not session.encrypted_oslc_consumer_credentials:
            return None
        raw = self.cipher.decrypt_raw(session.encrypted_oslc_consumer_credentials)
        return OSLCConsumerCredentials.model_validate_json(raw)

    def set_oslc_consumer_credentials(self, session: SessionData, credentials: OSLCConsumerCredentials) -> SessionData:
        session.encrypted_oslc_consumer_credentials = self.cipher.encrypt_raw(credentials.model_dump_json().encode("utf-8"))
        self.store.set(session)
        return session

    def clear_oslc_consumer_credentials(self, session: SessionData) -> SessionData:
        session.encrypted_oslc_consumer_credentials = None
        self.store.set(session)
        return session

    def validate_csrf(self, session: SessionData, token: str | None) -> bool:
        return bool(token and token == session.csrf_token)

    def snapshot(self, session: SessionData | None) -> SessionSnapshot:
        if not session:
            return SessionSnapshot(authenticated=False)
        warning = None
        stale_minutes = self.settings.permission_snapshot_stale_warning_minutes
        last_valid = session.permission_snapshot_refreshed_at or session.created_at
        if (
            session.permission_snapshot_failure_count >= self.settings.permission_refresh_warning_failures
            or last_valid + timedelta(minutes=stale_minutes) <= datetime.now(UTC)
        ):
            warning = (
                f"Teamwork Cloud permission refresh has failed {session.permission_snapshot_failure_count} time(s). "
                "The last valid access snapshot remains active while Workbench retries."
            )
        return SessionSnapshot(
            authenticated=True,
            session_id=session.session_id,
            csrf_token=session.csrf_token,
            user=session.user,
            server=session.server,
            can_manage_server_presets=session.authorization_context.can_manage_server_presets,
            capabilities=session.capabilities,
            preferences=session.preferences,
            bookmarks=session.bookmarks,
            saved_searches=session.saved_searches,
            recent_items=session.recent_items,
            permission_snapshot_attempted_at=session.permission_snapshot_attempted_at,
            permission_snapshot_refreshed_at=session.permission_snapshot_refreshed_at,
            permission_snapshot_failure_count=session.permission_snapshot_failure_count,
            permission_snapshot_warning=warning,
        )

    def update_capabilities(self, session: SessionData, capabilities: Any) -> SessionData:
        session.capabilities = capabilities
        self.store.set(session)
        return session

    def update_authorization_context(
        self,
        session: SessionData,
        authorization_context: AuthorizationContext,
    ) -> SessionData:
        session.authorization_context = authorization_context
        self.store.set(session)
        return session

    def update_preferences(self, session: SessionData, preferences: SessionPreferences) -> SessionData:
        session.preferences = preferences
        self.store.set(session)
        return session

    def add_recent_item(self, session: SessionData, bookmark: Bookmark) -> SessionData:
        without_duplicate = [
            item
            for item in session.recent_items
            if (item.item_id, item.project_id, item.branch_id) != (bookmark.item_id, bookmark.project_id, bookmark.branch_id)
        ]
        session.recent_items = [bookmark, *without_duplicate][:10]
        self.store.set(session)
        return session

    def upsert_bookmark(self, session: SessionData, bookmark: Bookmark) -> SessionData:
        without_duplicate = [
            item
            for item in session.bookmarks
            if (item.item_id, item.project_id, item.branch_id) != (bookmark.item_id, bookmark.project_id, bookmark.branch_id)
        ]
        session.bookmarks = [bookmark, *without_duplicate]
        self.store.set(session)
        return session

    def delete_bookmark(self, session: SessionData, bookmark_id: str) -> SessionData:
        session.bookmarks = [item for item in session.bookmarks if item.id != bookmark_id]
        self.store.set(session)
        return session

    def upsert_saved_search(self, session: SessionData, search: SavedSearch) -> SessionData:
        session.saved_searches = [item for item in session.saved_searches if item.id != search.id] + [search]
        self.store.set(session)
        return session

    def delete_saved_search(self, session: SessionData, search_id: str) -> SessionData:
        session.saved_searches = [item for item in session.saved_searches if item.id != search_id]
        self.store.set(session)
        return session

    def export_state(self) -> dict[str, Any]:
        if isinstance(self.store, InMemorySessionStore):
            return json.loads(
                json.dumps(
                    {
                        "sessions": [json.loads(item.model_dump_json()) for item in self.store._sessions.values()],
                    }
                )
            )
        return {"sessions": "stored-in-redis"}
