from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode, urlparse, urlunparse

import httpx

from app.models.domain import TokenBundle
from app.settings.config import Settings

if TYPE_CHECKING:
    from app.services.platform import ApplicationContainer


def build_callback_url(settings: Settings) -> str:
    return settings.resolved_twc_auth_callback_url


def _auth_override(settings: Settings, server):
    return settings.twc_auth_override_for_server(server.id)


def _auth_client_id(settings: Settings, server) -> str | None:
    override = _auth_override(settings, server)
    return (override.client_id if override and override.client_id else None) or settings.resolved_twc_auth_client_id


def _auth_client_secret(settings: Settings, server) -> str | None:
    override = _auth_override(settings, server)
    return (override.client_secret if override and override.client_secret else None) or settings.resolved_twc_auth_client_secret


def _auth_scope(settings: Settings, server) -> str:
    override = _auth_override(settings, server)
    return (override.scope if override and override.scope else None) or settings.twc_auth_scope


def _auth_return_url_parameter(settings: Settings, server) -> str:
    override = _auth_override(settings, server)
    return ((override.return_url_parameter if override and override.return_url_parameter else None) or settings.twc_saml_return_url_parameter)


def _url_with_path(url: str, path_or_url: str) -> str:
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url
    if not path_or_url.startswith("/"):
        path_or_url = f"/{path_or_url}"
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, path_or_url, "", "", ""))


def build_twc_auth_server_url(settings: Settings, server, path_or_url: str, *, port: int | None = None) -> str:
    path_or_url = path_or_url.strip()
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url
    if not path_or_url.startswith("/"):
        path_or_url = f"/{path_or_url}"
    parsed = urlparse(server.base_url.rstrip("/"))
    netloc = parsed.hostname or parsed.netloc
    if port is not None and parsed.hostname:
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = f"{host}:{port}"
    return urlunparse((parsed.scheme or "https", netloc, path_or_url, "", "", ""))


def _build_twc_authorize_base_url(settings: Settings, server) -> str:
    override = _auth_override(settings, server)
    if override and override.authorize_url:
        return override.authorize_url
    configured_url = (settings.twc_saml_authorize_url or "").strip()
    if configured_url:
        return configured_url

    login_path = (override.login_path if override and override.login_path else None) or settings.twc_saml_login_path
    login_port = (override.login_port if override and override.login_port is not None else None)
    if login_port is None:
        login_port = settings.twc_saml_login_port
    return build_twc_auth_server_url(settings, server, login_path or "/authentication/authorize", port=login_port)


def _build_twc_token_url(settings: Settings, server) -> str:
    override = _auth_override(settings, server)
    if override and override.token_url:
        return override.token_url
    if settings.twc_saml_token_url:
        return settings.twc_saml_token_url

    token_path = (override.token_path if override and override.token_path else None) or settings.twc_saml_token_path
    authorize_url = (override.authorize_url if override and override.authorize_url else None) or settings.twc_saml_authorize_url
    if authorize_url:
        return _url_with_path(authorize_url, token_path or "/authentication/api/token")

    login_port = (override.login_port if override and override.login_port is not None else None)
    if login_port is None:
        login_port = settings.twc_saml_login_port
    return build_twc_auth_server_url(settings, server, token_path or "/authentication/api/token", port=login_port)


def build_twc_authorize_base_url(container: ApplicationContainer, server) -> str:
    return _build_twc_authorize_base_url(container.settings, server)


def build_twc_token_url(container: ApplicationContainer, server) -> str:
    return _build_twc_token_url(container.settings, server)


def build_twc_saml_signin_url(container: ApplicationContainer, server, state: str) -> str:
    settings = container.settings
    client_id = _auth_client_id(settings, server)
    if not client_id:
        raise ValueError(
            "A TWC AuthServer client id must be configured for Teamwork Cloud SSO. "
            "Use TWC_AUTH_CLIENT_ID or a per-server TWC_AUTH_SERVER_OVERRIDES entry from authentication.client.ids."
        )
    callback_url = build_callback_url(settings)
    login_url = _build_twc_authorize_base_url(settings, server)
    query = urlencode(
        {
            "scope": _auth_scope(settings, server),
            _auth_return_url_parameter(settings, server): callback_url,
            "client_id": client_id,
            "response_type": "code",
            "state": state,
        }
    )
    separator = "&" if "?" in login_url else "?"
    return f"{login_url}{separator}{query}"


def infer_token_expiry(token: str | None) -> datetime | None:
    if not token or token.count(".") < 2:
        return None
    try:
        _, payload, _ = token.split(".", 2)
        padded = payload + ("=" * (-len(payload) % 4))
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        claims = json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return None
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return None
    return datetime.fromtimestamp(exp, tz=UTC)


def _bundle_from_authserver_payload(payload: dict[str, Any], *, scope: str | None = None) -> TokenBundle:
    id_token = payload.get("id_token") if isinstance(payload.get("id_token"), str) else None
    access_token = payload.get("access_token") if isinstance(payload.get("access_token"), str) else None
    refresh_token = payload.get("refresh_token") if isinstance(payload.get("refresh_token"), str) else None
    rest_token = id_token or access_token
    if not rest_token or not rest_token.strip():
        raise PermissionError("TWC AuthServer token exchange did not return an id_token or access_token.")

    expires_at = None
    expires_in = payload.get("expires_in")
    if isinstance(expires_in, (int, float)):
        expires_at = datetime.now(UTC) + timedelta(seconds=float(expires_in))
    if expires_at is None:
        expires_at = infer_token_expiry(id_token) or infer_token_expiry(access_token)

    return TokenBundle(
        access_token=rest_token.strip(),
        refresh_token=refresh_token,
        id_token=id_token,
        token_type="Token",
        scope=scope,
        expires_at=expires_at,
    )


async def _request_authserver_tokens(
    settings: Settings,
    server,
    form_data: dict[str, str],
) -> TokenBundle:
    client_id = _auth_client_id(settings, server)
    client_secret = _auth_client_secret(settings, server)
    if not client_id or not client_secret:
        raise PermissionError(
            "A TWC AuthServer client id and authentication.client.secret must be configured for SSO code exchange. "
            "Use TWC_AUTH_CLIENT_ID/TWC_AUTH_CLIENT_SECRET or per-server TWC_AUTH_SERVER_OVERRIDES."
        )

    token_url = _build_twc_token_url(settings, server)
    verify = server.ca_bundle_path if server.verify_tls and server.ca_bundle_path else server.verify_tls
    async with httpx.AsyncClient(timeout=20.0, verify=verify, follow_redirects=True) as client:
        response = await client.post(
            token_url,
            headers={"X-Auth-Secret": client_secret},
            data=form_data,
        )
    if response.status_code >= 400:
        raise PermissionError(f"TWC AuthServer token exchange failed with HTTP {response.status_code}: {response.text[:500]}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise PermissionError("TWC AuthServer token exchange did not return JSON.") from exc
    return _bundle_from_authserver_payload(payload, scope=form_data.get("scope"))


async def exchange_twc_auth_code(container: ApplicationContainer, server, code: str) -> TokenBundle:
    client_id = _auth_client_id(container.settings, server)
    if not client_id:
        raise PermissionError("A TWC AuthServer client id must be configured for Teamwork Cloud SSO.")
    return await _request_authserver_tokens(
        container.settings,
        server,
        {
            "scope": _auth_scope(container.settings, server),
            "redirect_uri": build_callback_url(container.settings),
            "client_id": client_id,
            "grant_type": "authorization_code",
            "code": code,
        },
    )


async def refresh_twc_auth_token(settings: Settings, server, refresh_token: str) -> TokenBundle:
    client_id = _auth_client_id(settings, server)
    if not client_id:
        raise PermissionError("A TWC AuthServer client id must be configured for Teamwork Cloud token refresh.")
    return await _request_authserver_tokens(
        settings,
        server,
        {
            "scope": _auth_scope(settings, server),
            "redirect_uri": build_callback_url(settings),
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
