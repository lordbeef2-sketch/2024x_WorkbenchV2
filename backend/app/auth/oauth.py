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

from app.models.domain import ServerProfile, TokenBundle


@dataclass(slots=True)
class OIDCProviderMetadata:
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str | None = None


@dataclass(slots=True)
class PendingOAuthState:
    server_id: str
    verifier: str
    redirect_uri: str
    created_at: datetime
    provider: OIDCProviderMetadata


@dataclass(slots=True)
class OAuthCallbackResult:
    server_id: str
    token_bundle: TokenBundle
    preferred_username: str


class OAuthService:
    def __init__(self) -> None:
        self._pending_states: dict[str, PendingOAuthState] = {}

    def get_pending_server_id(self, state: str) -> str | None:
        pending = self._pending_states.get(state)
        return pending.server_id if pending else None

    async def create_authorization_url(self, server: ServerProfile) -> str:
        provider = await self._discover_provider(server)
        state = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("utf-8")).digest()).rstrip(b"=").decode("utf-8")

        self._pending_states[state] = PendingOAuthState(
            server_id=server.id,
            verifier=verifier,
            redirect_uri=server.callback_url,
            created_at=datetime.now(UTC),
            provider=provider,
        )

        query = urlencode(
            {
                "client_id": server.client_id,
                "response_type": "code",
                "redirect_uri": server.callback_url,
                "scope": "openid profile",
                "state": state,
                "code_challenge_method": "S256",
                "code_challenge": challenge,
            }
        )
        return f"{provider.authorization_endpoint}?{query}"

    async def handle_callback(self, server: ServerProfile, code: str, state: str) -> OAuthCallbackResult:
        pending = self._pending_states.pop(state, None)
        if not pending or pending.server_id != server.id:
            raise ValueError("Invalid or expired OAuth state")
        if pending.created_at < datetime.now(UTC) - timedelta(minutes=15):
            raise ValueError("Expired OAuth state")

        verify = server.ca_bundle_path if server.verify_tls and server.ca_bundle_path else server.verify_tls
        async with httpx.AsyncClient(timeout=30.0, verify=verify) as client:
            response = await client.post(
                pending.provider.token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": pending.redirect_uri,
                    "client_id": server.client_id,
                    "code_verifier": pending.verifier,
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()

            expires_at = None
            if expires_in := payload.get("expires_in"):
                expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in))

            bundle = TokenBundle(
                access_token=payload["access_token"],
                refresh_token=payload.get("refresh_token"),
                id_token=payload.get("id_token"),
                token_type=payload.get("token_type", "Bearer"),
                scope=payload.get("scope"),
                expires_at=expires_at,
            )

            preferred_username = await self._resolve_preferred_username(client, pending.provider, bundle)
            return OAuthCallbackResult(server_id=server.id, token_bundle=bundle, preferred_username=preferred_username)

    async def _resolve_preferred_username(
        self,
        client: httpx.AsyncClient,
        provider: OIDCProviderMetadata,
        bundle: TokenBundle,
    ) -> str:
        headers = {"Authorization": f"Bearer {bundle.access_token}", "Accept": "application/json"}
        if provider.userinfo_endpoint:
            try:
                response = await client.get(provider.userinfo_endpoint, headers=headers)
                if response.is_success:
                    payload = response.json()
                    if payload.get("preferred_username"):
                        return payload["preferred_username"]
            except httpx.HTTPError:
                pass

        for candidate in [bundle.id_token, bundle.access_token]:
            if not candidate:
                continue
            claims = self._decode_unverified_jwt(candidate)
            if claims.get("preferred_username"):
                return str(claims["preferred_username"])
            if claims.get("upn"):
                return str(claims["upn"])
            if claims.get("email"):
                return str(claims["email"])
        raise ValueError("Unable to extract preferred_username from OAuth response")

    def _decode_unverified_jwt(self, token: str) -> dict[str, Any]:
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

    async def _discover_provider(self, server: ServerProfile) -> OIDCProviderMetadata:
        verify = server.ca_bundle_path if server.verify_tls and server.ca_bundle_path else server.verify_tls
        auth_url = server.auth_url.rstrip("/")
        candidates = self._build_metadata_candidates(auth_url)

        async with httpx.AsyncClient(timeout=15.0, verify=verify, follow_redirects=True) as client:
            for candidate in candidates:
                try:
                    response = await client.get(candidate, headers={"Accept": "application/json"})
                    if response.is_success:
                        payload = response.json()
                        if payload.get("authorization_endpoint") and payload.get("token_endpoint"):
                            return OIDCProviderMetadata(
                                authorization_endpoint=payload["authorization_endpoint"],
                                token_endpoint=payload["token_endpoint"],
                                userinfo_endpoint=payload.get("userinfo_endpoint"),
                            )
                except httpx.HTTPError:
                    continue

        return OIDCProviderMetadata(
            authorization_endpoint=auth_url,
            token_endpoint=self._derive_token_endpoint(auth_url),
            userinfo_endpoint=self._derive_userinfo_endpoint(auth_url),
        )

    def _build_metadata_candidates(self, auth_url: str) -> list[str]:
        candidates = []
        if ".well-known/openid-configuration" in auth_url:
            candidates.append(auth_url)

        parsed = urlparse(auth_url)
        auth_base = auth_url
        if auth_url.endswith("/authorize"):
            auth_base = auth_url[: -len("/authorize")]
        if auth_url.endswith("/auth"):
            auth_base = auth_url[: -len("/auth")]
        if "/protocol/openid-connect/auth" in auth_url:
            auth_base = auth_url.split("/protocol/openid-connect/auth", maxsplit=1)[0]

        if auth_base:
            candidates.append(f"{auth_base}/.well-known/openid-configuration")
        candidates.append(f"{parsed.scheme}://{parsed.netloc}/.well-known/openid-configuration")

        seen: set[str] = set()
        ordered = []
        for item in candidates:
            if item and item not in seen:
                seen.add(item)
                ordered.append(item)
        return ordered

    def _derive_token_endpoint(self, auth_url: str) -> str:
        if auth_url.endswith("/authorize"):
            return f"{auth_url[: -len('/authorize')]}/token"
        if "/protocol/openid-connect/auth" in auth_url:
            return auth_url.replace("/auth", "/token")
        return f"{auth_url}/token"

    def _derive_userinfo_endpoint(self, auth_url: str) -> str | None:
        if auth_url.endswith("/authorize"):
            return f"{auth_url[: -len('/authorize')]}/userinfo"
        if "/protocol/openid-connect/auth" in auth_url:
            return auth_url.replace("/auth", "/userinfo")
        return None
