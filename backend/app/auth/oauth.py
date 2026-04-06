from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.models.domain import ServerProfile, TokenBundle
from app.settings.config import Settings


@dataclass(slots=True)
class OIDCProviderMetadata:
    authorization_endpoint: str
    token_endpoint: str
    issuer: str | None = None


@dataclass(slots=True)
class PendingOAuthState:
    state: str
    server_id: str
    created_at: datetime


@dataclass(slots=True)
class OAuthCallbackResult:
    server_id: str
    token_bundle: TokenBundle
    preferred_username: str | None = None


class OAuthStateCipher:
    def __init__(self, secret: str) -> None:
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest)
        self._fernet = Fernet(key)

    def encrypt(self, state: PendingOAuthState) -> str:
        payload = json.dumps(
            {
                "state": state.state,
                "server_id": state.server_id,
                "created_at": state.created_at.isoformat(),
            }
        ).encode("utf-8")
        return self._fernet.encrypt(payload).decode("utf-8")

    def decrypt(self, payload: str) -> PendingOAuthState:
        raw = self._fernet.decrypt(payload.encode("utf-8"))
        data = json.loads(raw)
        return PendingOAuthState(
            state=str(data["state"]),
            server_id=str(data["server_id"]),
            created_at=datetime.fromisoformat(str(data["created_at"])),
        )


class OAuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.cipher = OAuthStateCipher(settings.session_secret)

    def is_configured(self) -> bool:
        return bool(self.settings.twc_auth_client_id and self.settings.twc_auth_client_secret and self.settings.resolved_app_origin)

    def configuration_error(self) -> str | None:
        missing: list[str] = []
        if not self.settings.twc_auth_client_id:
            missing.append("TWC_AUTH_CLIENT_ID")
        if not self.settings.twc_auth_client_secret:
            missing.append("TWC_AUTH_CLIENT_SECRET")
        if not self.settings.resolved_app_origin:
            missing.append("APP_ORIGIN or FRONTEND_ORIGIN")
        if not missing:
            return None
        return f"Redirect login is not configured. Missing settings: {', '.join(missing)}"

    def create_pending_state_cookie(self, server_id: str) -> tuple[str, PendingOAuthState]:
        pending = PendingOAuthState(
            state=secrets.token_urlsafe(24),
            server_id=server_id,
            created_at=datetime.now(UTC),
        )
        return self.cipher.encrypt(pending), pending

    def load_pending_state(self, cookie_value: str | None) -> PendingOAuthState | None:
        if not cookie_value:
            return None
        try:
            pending = self.cipher.decrypt(cookie_value)
        except (InvalidToken, KeyError, ValueError, TypeError, json.JSONDecodeError):
            return None
        if pending.created_at < datetime.now(UTC) - timedelta(minutes=self.settings.twc_auth_state_ttl_minutes):
            return None
        return pending

    async def create_authorization_url(self, server: ServerProfile, state: str) -> str:
        provider = await self._discover_provider(server)
        query = urlencode(
            {
                "scope": self.settings.twc_auth_scope,
                "redirect_uri": self.settings.resolved_twc_auth_callback_url,
                "client_id": self.settings.twc_auth_client_id,
                "response_type": "code",
                "state": state,
            }
        )
        return f"{provider.authorization_endpoint}?{query}"

    async def handle_callback(self, server: ServerProfile, code: str) -> OAuthCallbackResult:
        provider = await self._discover_provider(server)
        verify = server.ca_bundle_path if server.verify_tls and server.ca_bundle_path else server.verify_tls
        async with httpx.AsyncClient(timeout=30.0, verify=verify, follow_redirects=True) as client:
            response = await client.post(
                provider.token_endpoint,
                data={
                    "scope": self.settings.twc_auth_scope,
                    "redirect_uri": self.settings.resolved_twc_auth_callback_url,
                    "client_id": self.settings.twc_auth_client_id,
                    "grant_type": "authorization_code",
                    "code": code,
                },
                headers={
                    "Accept": "application/json",
                    "X-Auth-Secret": self.settings.twc_auth_client_secret or "",
                },
            )
            response.raise_for_status()
            payload = response.json()

        expires_at = None
        if expires_in := payload.get("expires_in"):
            expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in))

        api_token = payload.get("id_token") or payload.get("access_token")
        if not api_token:
            raise ValueError("Authentication server did not return a usable token for Teamwork Cloud API calls")

        bundle = TokenBundle(
            access_token=api_token,
            refresh_token=payload.get("refresh_token"),
            id_token=payload.get("id_token"),
            token_type="Token" if payload.get("id_token") else str(payload.get("token_type", "Bearer")),
            scope=payload.get("scope"),
            expires_at=expires_at,
        )
        return OAuthCallbackResult(
            server_id=server.id,
            token_bundle=bundle,
            preferred_username=self._preferred_username_from_bundle(bundle),
        )

    async def _discover_provider(self, server: ServerProfile) -> OIDCProviderMetadata:
        verify = server.ca_bundle_path if server.verify_tls and server.ca_bundle_path else server.verify_tls
        async with httpx.AsyncClient(timeout=15.0, verify=verify, follow_redirects=True) as client:
            for candidate in self._metadata_candidates(server.base_url):
                try:
                    response = await client.get(candidate, headers={"Accept": "application/json"})
                    if not response.is_success:
                        continue
                    payload = response.json()
                except (httpx.HTTPError, ValueError):
                    continue
                authorization_endpoint = payload.get("authorization_endpoint")
                token_endpoint = payload.get("token_endpoint")
                if authorization_endpoint and token_endpoint:
                    return OIDCProviderMetadata(
                        authorization_endpoint=str(authorization_endpoint),
                        token_endpoint=str(token_endpoint),
                        issuer=str(payload.get("issuer")) if payload.get("issuer") else None,
                    )

        auth_base = self._default_auth_base(server.base_url)
        return OIDCProviderMetadata(
            authorization_endpoint=f"{auth_base}/authorize",
            token_endpoint=f"{auth_base}/api/token",
            issuer=auth_base,
        )

    def _metadata_candidates(self, base_url: str) -> list[str]:
        auth_base = self._default_auth_base(base_url)
        parsed = urlparse(base_url)
        candidates = [f"{auth_base}/.well-known/openid-configuration"]
        if parsed.scheme and parsed.netloc:
            candidates.append(f"{parsed.scheme}://{parsed.netloc}/authentication/.well-known/openid-configuration")
        seen: set[str] = set()
        ordered: list[str] = []
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                ordered.append(candidate)
        return ordered

    def _default_auth_base(self, base_url: str) -> str:
        parsed = urlparse(base_url)
        scheme = parsed.scheme or "https"
        host = parsed.hostname or ""
        if not host:
            raise ValueError("Preset server base_url must include a hostname")
        auth_port = 8443 if parsed.port == 8111 else parsed.port
        netloc = f"{host}:{auth_port}" if auth_port else host
        return f"{scheme}://{netloc}/authentication"

    def _preferred_username_from_bundle(self, bundle: TokenBundle) -> str | None:
        for candidate in (bundle.id_token, bundle.access_token):
            claims = self._decode_unverified_jwt(candidate)
            for key in ("preferred_username", "upn", "email", "username"):
                value = claims.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    def _decode_unverified_jwt(self, token: str | None) -> dict[str, Any]:
        if not token:
            return {}
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        padding = "=" * (-len(payload) % 4)
        try:
            decoded = base64.urlsafe_b64decode(payload + padding)
            return json.loads(decoded)
        except Exception:
            return {}