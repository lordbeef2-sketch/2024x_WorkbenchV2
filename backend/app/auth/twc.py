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


def _auth_scope(settings: Settings, server) -> str | None:
    override = _auth_override(settings, server)
    return (override.scope if override and override.scope else None) or settings.twc_auth_scope


def _auth_return_url_parameter(settings: Settings, server) -> str:
    override = _auth_override(settings, server)
    return (
        (override.return_url_parameter if override and override.return_url_parameter else None)
        or settings.twc_oidc_return_url_parameter
    )


def _auth_token_method(settings: Settings, server) -> str:
    override = _auth_override(settings, server)
    return (
        (override.token_auth_method if override and override.token_auth_method else None)
        or settings.twc_oidc_token_auth_method
        or "client_secret_basic"
    ).strip().lower()


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
    configured_url = (settings.twc_oidc_authorize_url or "").strip()
    if configured_url:
        return configured_url

    login_path = (
        (override.login_path if override and override.login_path else None)
        or settings.twc_oidc_authorize_path
    )
    login_port = (override.login_port if override and override.login_port is not None else None)
    if login_port is None:
        login_port = settings.twc_oidc_port
    return build_twc_auth_server_url(settings, server, login_path or "/authentication/oidc/authorize", port=login_port)


def _build_twc_token_url(settings: Settings, server) -> str:
    override = _auth_override(settings, server)
    if override and override.token_url:
        return override.token_url
    if settings.twc_oidc_token_url:
        return settings.twc_oidc_token_url

    token_path = (
        (override.token_path if override and override.token_path else None)
        or settings.twc_oidc_token_path
    )
    authorize_url = (
        (override.authorize_url if override and override.authorize_url else None)
        or settings.twc_oidc_authorize_url
    )
    if authorize_url:
        return _url_with_path(authorize_url, token_path or "/authentication/api/oidc/token")

    login_port = (override.login_port if override and override.login_port is not None else None)
    if login_port is None:
        login_port = settings.twc_oidc_port
    return build_twc_auth_server_url(settings, server, token_path or "/authentication/api/oidc/token", port=login_port)


def _build_twc_discovery_url(settings: Settings, server) -> str:
    override = _auth_override(settings, server)
    if override and override.discovery_url:
        return override.discovery_url
    if settings.twc_oidc_discovery_url:
        return settings.twc_oidc_discovery_url
    return build_twc_auth_server_url(
        settings,
        server,
        settings.twc_oidc_discovery_path,
        port=settings.twc_oidc_port,
    )


async def resolve_twc_oidc_configuration(settings: Settings, server) -> dict[str, Any]:
    """Resolve the 2024x Refresh3 OIDC endpoints from AuthServer discovery.

    Explicit per-server URLs remain authoritative. If discovery is unavailable,
    the documented 2024x Refresh3 endpoint paths are used as a bounded fallback.
    """
    override = _auth_override(settings, server)
    explicit_authorize = (override.authorize_url if override and override.authorize_url else None) or settings.twc_oidc_authorize_url
    explicit_token = (override.token_url if override and override.token_url else None) or settings.twc_oidc_token_url
    configuration: dict[str, Any] = {
        "authorization_endpoint": explicit_authorize or _build_twc_authorize_base_url(settings, server),
        "token_endpoint": explicit_token or _build_twc_token_url(settings, server),
        "token_endpoint_auth_methods_supported": [_auth_token_method(settings, server)],
        "scopes_supported": ["openid"],
        "discovery_endpoint": _build_twc_discovery_url(settings, server),
        "source": "explicit" if explicit_authorize and explicit_token else "documented-2024x-r3-default",
    }
    if explicit_authorize and explicit_token:
        return configuration

    verify = server.ca_bundle_path if server.verify_tls and server.ca_bundle_path else server.verify_tls
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=verify, follow_redirects=True) as client:
            response = await client.get(configuration["discovery_endpoint"], headers={"Accept": "application/json"})
        if response.status_code >= 400:
            return configuration
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return configuration
    if not isinstance(payload, dict):
        return configuration
    if not explicit_authorize and isinstance(payload.get("authorization_endpoint"), str):
        configuration["authorization_endpoint"] = payload["authorization_endpoint"].strip()
    if not explicit_token and isinstance(payload.get("token_endpoint"), str):
        configuration["token_endpoint"] = payload["token_endpoint"].strip()
    methods = payload.get("token_endpoint_auth_methods_supported")
    if isinstance(methods, list):
        configuration["token_endpoint_auth_methods_supported"] = [str(item) for item in methods]
    scopes = payload.get("scopes_supported")
    if isinstance(scopes, list):
        configuration["scopes_supported"] = [str(item) for item in scopes]
    configuration["source"] = "oidc-discovery"
    return configuration


def build_twc_authorize_base_url(container: ApplicationContainer, server) -> str:
    return _build_twc_authorize_base_url(container.settings, server)


def build_twc_token_url(container: ApplicationContainer, server) -> str:
    return _build_twc_token_url(container.settings, server)


def build_twc_oidc_authorization_url(container: ApplicationContainer, server, state: str) -> str:
    settings = container.settings
    client_id = _auth_client_id(settings, server)
    if not client_id:
        raise ValueError(
            "A TWC AuthServer client id must be configured for Teamwork Cloud SSO. "
            "Use the generated OpenID Connect client id in TWC_AUTH_CLIENT_ID or a per-server TWC_AUTH_SERVER_OVERRIDES entry."
        )
    callback_url = build_callback_url(settings)
    login_url = _build_twc_authorize_base_url(settings, server)
    query_values = {
        _auth_return_url_parameter(settings, server): callback_url,
        "client_id": client_id,
        "response_type": "code",
        "state": state,
    }
    if scope := _auth_scope(settings, server):
        query_values["scope"] = scope
    query = urlencode(query_values)
    separator = "&" if "?" in login_url else "?"
    return f"{login_url}{separator}{query}"


async def build_twc_oidc_signin_url(container: ApplicationContainer, server, state: str) -> tuple[str, dict[str, Any]]:
    configuration = await resolve_twc_oidc_configuration(container.settings, server)
    url = build_twc_oidc_authorization_url(container, server, state)
    configured_endpoint = str(configuration.get("authorization_endpoint") or "").strip()
    if configured_endpoint:
        parsed = urlparse(url)
        endpoint = urlparse(configured_endpoint)
        url = urlunparse((endpoint.scheme, endpoint.netloc, endpoint.path, endpoint.params, parsed.query, ""))
    return url, configuration


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
            "A generated TWC OpenID Connect client id and secret must be configured for SSO code exchange. "
            "Use TWC_AUTH_CLIENT_ID/TWC_AUTH_CLIENT_SECRET or per-server TWC_AUTH_SERVER_OVERRIDES."
        )

    configuration = await resolve_twc_oidc_configuration(settings, server)
    token_url = str(configuration.get("token_endpoint") or _build_twc_token_url(settings, server))
    token_method = _auth_token_method(settings, server)
    supported_methods = {
        str(item).strip().lower()
        for item in configuration.get("token_endpoint_auth_methods_supported", [])
        if str(item).strip()
    }
    if token_method == "client_secret_basic" and supported_methods and token_method not in supported_methods:
        raise PermissionError(
            f"TWC AuthServer discovery does not advertise configured token authentication method {token_method}."
        )
    verify = server.ca_bundle_path if server.verify_tls and server.ca_bundle_path else server.verify_tls
    async with httpx.AsyncClient(timeout=20.0, verify=verify, follow_redirects=True) as client:
        if token_method == "client_secret_basic":
            response = await client.post(token_url, auth=httpx.BasicAuth(client_id, client_secret), data=form_data)
        else:
            raise PermissionError(f"Unsupported TWC OIDC token authentication method: {token_method}")
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
    form_data = {
        "redirect_uri": build_callback_url(container.settings),
        "client_id": client_id,
        "grant_type": "authorization_code",
        "code": code,
    }
    if scope := _auth_scope(container.settings, server):
        form_data["scope"] = scope
    return await _request_authserver_tokens(
        container.settings,
        server,
        form_data,
    )


async def refresh_twc_auth_token(settings: Settings, server, refresh_token: str) -> TokenBundle:
    client_id = _auth_client_id(settings, server)
    if not client_id:
        raise PermissionError("A TWC AuthServer client id must be configured for Teamwork Cloud token refresh.")
    form_data = {
        "redirect_uri": build_callback_url(settings),
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    if scope := _auth_scope(settings, server):
        form_data["scope"] = scope
    return await _request_authserver_tokens(
        settings,
        server,
        form_data,
    )
