from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from common import (
    CONFIG_PATH,
    AuthConfig,
    ContextConfig,
    ExampleConfig,
    ExampleError,
    TokenBundle,
    TwcExampleClient,
    authorize_url,
    ensure_authenticated_token,
    exchange_auth_code,
    load_config,
    print_json,
    refresh_auth_token,
    require_context_fields,
    token_url,
)


def _resolve_config(config_or_path: ExampleConfig | str | Path | None = None) -> ExampleConfig:
    if isinstance(config_or_path, ExampleConfig):
        return config_or_path
    if config_or_path is None:
        return load_config(CONFIG_PATH)
    return load_config(Path(config_or_path))


def load_example_config(config_path: str | Path | None = None) -> ExampleConfig:
    return _resolve_config(config_path)


def build_authenticated_client(config_path: str | Path | None = None) -> TwcExampleClient:
    config = _resolve_config(config_path)
    bundle = ensure_authenticated_token(config)
    return TwcExampleClient(config, bundle)


def authorize_request_url(config_or_path: ExampleConfig | str | Path | None = None, state: str | None = None) -> str:
    config = _resolve_config(config_or_path)
    request_state = state or secrets.token_urlsafe(24)
    query = urlencode(
        {
            "scope": config.resolved_auth_scope,
            "redirect_uri": config.callback_url,
            "client_id": config.auth.client_id.strip(),
            "response_type": "code",
            "state": request_state,
        }
    )
    return f"{authorize_url(config)}?{query}"


def token_endpoint(config_or_path: ExampleConfig | str | Path | None = None) -> str:
    config = _resolve_config(config_or_path)
    return token_url(config)


def exchange_code(code: str, config_path: str | Path | None = None) -> TokenBundle:
    config = _resolve_config(config_path)
    return exchange_auth_code(config, code)


def refresh_token(refresh_token_value: str, config_path: str | Path | None = None) -> TokenBundle:
    config = _resolve_config(config_path)
    return refresh_auth_token(config, refresh_token_value)


def token_summary(bundle: TokenBundle) -> dict[str, Any]:
    return {
        "has_rest_token": bool(bundle.rest_token),
        "has_access_token": bool(bundle.access_token),
        "has_id_token": bool(bundle.id_token),
        "has_refresh_token": bool(bundle.refresh_token),
        "expires_at": bundle.expires_at.isoformat() if bundle.expires_at else None,
        "is_expired": bundle.is_expired,
    }


def auth_summary(client: TwcExampleClient) -> dict[str, Any]:
    return {
        "base_url": client.config.base_url,
        "callback_url": client.config.callback_url,
        "authorize_url": authorize_request_url(client.config),
        "token_url": token_endpoint(client.config),
        "token": token_summary(client.bundle),
    }