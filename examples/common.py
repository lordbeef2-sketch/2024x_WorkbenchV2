from __future__ import annotations

import json
import secrets
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx


CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


class ExampleError(RuntimeError):
    """Raised when an example cannot continue."""


@dataclass(slots=True)
class AuthConfig:
    client_id: str = ""
    client_secret: str = ""
    scope: str = "openid"
    discovery_url: str = ""
    authorize_url: str = ""
    token_url: str = ""
    auth_scheme: str = "https"
    auth_port: int = 8443
    discovery_path: str = "/authentication/.well-known/oidc-configuration"
    authorize_path: str = "/authentication/oidc/authorize"
    token_path: str = "/authentication/api/oidc/token"
    token_auth_method: str = "client_secret_basic"
    callback_host: str = "127.0.0.1"
    callback_port: int = 8765
    callback_path: str = "/callback"
    open_browser: bool = True
    auth_timeout_seconds: int = 300
    token_cache_file: str = ".twc_sso_token_cache.json"


@dataclass(slots=True)
class ContextConfig:
    workspace_id: str = ""
    resource_id: str = ""
    branch_id: str = ""
    model_id: str = ""
    element_id: str = ""
    element_ids: list[str] = field(default_factory=list)
    source_revision: str = ""
    target_revision: str = ""
    artifact_id: str = ""
    update_payload: dict[str, Any] = field(default_factory=dict)
    contract_example: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExampleConfig:
    base_url: str
    verify_tls: bool | str = True
    request_timeout_seconds: int = 30
    auth: AuthConfig = field(default_factory=AuthConfig)
    context: ContextConfig = field(default_factory=ContextConfig)

    @property
    def callback_url(self) -> str:
        path = self.auth.callback_path if self.auth.callback_path.startswith("/") else f"/{self.auth.callback_path}"
        return f"http://{self.auth.callback_host}:{self.auth.callback_port}{path}"

    @property
    def cache_path(self) -> Path:
        return CONFIG_PATH.parent / (self.auth.token_cache_file or ".twc_sso_token_cache.json")

    @property
    def resolved_auth_scope(self) -> str | None:
        return self.auth.scope.strip() or None


@dataclass(slots=True)
class TokenBundle:
    rest_token: str
    refresh_token: str | None = None
    id_token: str | None = None
    access_token: str | None = None
    expires_at: datetime | None = None

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at <= datetime.now(UTC) + timedelta(minutes=2)


def normalize_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if normalized.endswith("/osmc"):
        return normalized[: -len("/osmc")]
    return normalized


def parse_verify_tls(value: Any) -> bool | str:
    if isinstance(value, bool):
        return value
    text = str(value).strip()
    if not text:
        return True
    lowered = text.lower()
    if lowered in {"true", "1", "yes", "on"}:
        return True
    if lowered in {"false", "0", "no", "off"}:
        return False
    return text


def is_http_base_url(base_url: str) -> bool:
    return normalize_base_url(base_url).lower().startswith("http://")


def read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ExampleError(f"Config file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExampleError(f"Config file is not valid JSON: {path}") from exc


def load_config(path: Path = CONFIG_PATH) -> ExampleConfig:
    raw = read_json_file(path)
    auth = AuthConfig(**(raw.get("auth") or {}))
    context = ContextConfig(**(raw.get("context") or {}))
    config = ExampleConfig(
        base_url=str(raw.get("base_url") or "").strip(),
        verify_tls=raw.get("verify_tls", True),
        request_timeout_seconds=int(raw.get("request_timeout_seconds", 30)),
        auth=auth,
        context=context,
    )
    if not config.base_url:
        raise ExampleError(f"base_url must be set in {path}")
    if not config.auth.client_id.strip():
        raise ExampleError(f"auth.client_id must be set in {path}")
    if not config.auth.client_secret.strip():
        raise ExampleError(f"auth.client_secret must be set in {path}")
    return config


def build_auth_server_url(config: ExampleConfig, path_or_url: str) -> str:
    raw = path_or_url.strip()
    if raw.startswith(("http://", "https://")):
        return raw
    if not raw.startswith("/"):
        raw = f"/{raw}"
    parsed = urlparse(normalize_base_url(config.base_url))
    scheme = config.auth.auth_scheme.strip() or (parsed.scheme or "https")
    host = parsed.hostname or parsed.netloc
    if not host:
        raise ExampleError("Unable to derive the AuthServer host from base_url.")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{config.auth.auth_port}"
    return urlunparse((scheme, netloc, raw, "", "", ""))


def authorize_url(config: ExampleConfig) -> str:
    if config.auth.authorize_url.strip():
        return config.auth.authorize_url.strip()
    discovered = oidc_configuration(config).get("authorization_endpoint")
    if isinstance(discovered, str) and discovered.strip():
        return discovered.strip()
    return build_auth_server_url(config, config.auth.authorize_path or "/authentication/oidc/authorize")


def token_url(config: ExampleConfig) -> str:
    if config.auth.token_url.strip():
        return config.auth.token_url.strip()
    discovered = oidc_configuration(config).get("token_endpoint")
    if isinstance(discovered, str) and discovered.strip():
        return discovered.strip()
    return build_auth_server_url(config, config.auth.token_path or "/authentication/api/oidc/token")


def oidc_configuration(config: ExampleConfig) -> dict[str, Any]:
    discovery_url = config.auth.discovery_url.strip() or build_auth_server_url(
        config,
        config.auth.discovery_path or "/authentication/.well-known/oidc-configuration",
    )
    try:
        with httpx.Client(verify=build_requests_verify(config), follow_redirects=True) as session:
            response = session.get(
                discovery_url,
                headers={"Accept": "application/json"},
                timeout=max(config.request_timeout_seconds, 30),
            )
        if response.status_code >= 400:
            return {}
        payload = response.json()
        return payload if isinstance(payload, dict) else {}
    except (httpx.HTTPError, ValueError):
        return {}


def token_bundle_from_payload(payload: dict[str, Any], *, scope: str | None) -> TokenBundle:
    id_token = payload.get("id_token") if isinstance(payload.get("id_token"), str) else None
    access_token = payload.get("access_token") if isinstance(payload.get("access_token"), str) else None
    refresh_token = payload.get("refresh_token") if isinstance(payload.get("refresh_token"), str) else None
    rest_token = (id_token or access_token or "").strip()
    if not rest_token:
        raise ExampleError("AuthServer token exchange did not return id_token or access_token.")

    expires_at: datetime | None = None
    expires_in = payload.get("expires_in")
    if isinstance(expires_in, (int, float)):
        expires_at = datetime.now(UTC) + timedelta(seconds=float(expires_in))

    return TokenBundle(
        rest_token=rest_token,
        refresh_token=refresh_token.strip() if isinstance(refresh_token, str) and refresh_token.strip() else None,
        id_token=id_token.strip() if isinstance(id_token, str) and id_token.strip() else None,
        access_token=access_token.strip() if isinstance(access_token, str) and access_token.strip() else None,
        expires_at=expires_at,
    )


def save_token_bundle(config: ExampleConfig, bundle: TokenBundle) -> None:
    payload = {
        "rest_token": bundle.rest_token,
        "refresh_token": bundle.refresh_token,
        "id_token": bundle.id_token,
        "access_token": bundle.access_token,
        "expires_at": bundle.expires_at.isoformat() if bundle.expires_at else None,
        "saved_at": datetime.now(UTC).isoformat(),
    }
    config.cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_token_bundle(config: ExampleConfig) -> TokenBundle | None:
    if not config.cache_path.exists():
        return None
    try:
        payload = json.loads(config.cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    expires_at = payload.get("expires_at")
    parsed_expires_at = None
    if isinstance(expires_at, str) and expires_at.strip():
        try:
            parsed_expires_at = datetime.fromisoformat(expires_at)
        except ValueError:
            parsed_expires_at = None

    rest_token = payload.get("rest_token")
    if not isinstance(rest_token, str) or not rest_token.strip():
        return None

    return TokenBundle(
        rest_token=rest_token.strip(),
        refresh_token=payload.get("refresh_token") if isinstance(payload.get("refresh_token"), str) else None,
        id_token=payload.get("id_token") if isinstance(payload.get("id_token"), str) else None,
        access_token=payload.get("access_token") if isinstance(payload.get("access_token"), str) else None,
        expires_at=parsed_expires_at,
    )


def build_requests_verify(config: ExampleConfig) -> bool | str:
    if is_http_base_url(config.base_url):
        return False
    return parse_verify_tls(config.verify_tls)


def requests_session(config: ExampleConfig) -> httpx.Client:
    return httpx.Client(
        headers={
            "Accept": "application/ld+json, application/json;q=0.9, */*;q=0.8",
        },
        verify=build_requests_verify(config),
        follow_redirects=True,
    )


def exchange_auth_code(config: ExampleConfig, code: str) -> TokenBundle:
    form_data = {
        "redirect_uri": config.callback_url,
        "client_id": config.auth.client_id.strip(),
        "grant_type": "authorization_code",
        "code": code,
    }
    if config.resolved_auth_scope:
        form_data["scope"] = config.resolved_auth_scope
    with requests_session(config) as session:
        if config.auth.token_auth_method.strip().lower() != "client_secret_basic":
            raise ExampleError("The 2024x Refresh3 examples support the documented client_secret_basic token method.")
        response = session.post(
            token_url(config),
            auth=httpx.BasicAuth(config.auth.client_id.strip(), config.auth.client_secret.strip()),
            data=form_data,
            timeout=max(config.request_timeout_seconds, 30),
        )
    if response.status_code >= 400:
        raise ExampleError(f"AuthServer token exchange failed with HTTP {response.status_code}: {response.text[:500]}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ExampleError("AuthServer token exchange did not return JSON.") from exc
    return token_bundle_from_payload(payload, scope=config.resolved_auth_scope)


def refresh_auth_token(config: ExampleConfig, refresh_token: str) -> TokenBundle:
    form_data = {
        "redirect_uri": config.callback_url,
        "client_id": config.auth.client_id.strip(),
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    if config.resolved_auth_scope:
        form_data["scope"] = config.resolved_auth_scope
    with requests_session(config) as session:
        if config.auth.token_auth_method.strip().lower() != "client_secret_basic":
            raise ExampleError("The 2024x Refresh3 examples support the documented client_secret_basic token method.")
        response = session.post(
            token_url(config),
            auth=httpx.BasicAuth(config.auth.client_id.strip(), config.auth.client_secret.strip()),
            data=form_data,
            timeout=max(config.request_timeout_seconds, 30),
        )
    if response.status_code >= 400:
        raise ExampleError(f"AuthServer token refresh failed with HTTP {response.status_code}: {response.text[:500]}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ExampleError("AuthServer token refresh did not return JSON.") from exc
    return token_bundle_from_payload(payload, scope=config.resolved_auth_scope)


class _CallbackHandler(BaseHTTPRequestHandler):
    callback_path = "/callback"
    queue_ref: list[dict[str, str] | None] = []
    event_ref: threading.Event | None = None

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != self.callback_path:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        params = {key: values[0] for key, values in parse_qs(parsed.query).items() if values}
        self.queue_ref.append(params)
        if self.event_ref is not None:
            self.event_ref.set()

        body = (
            "<html><body><h1>TWC Sign-In Complete</h1>"
            "<p>You can close this browser tab and return to the script.</p>"
            "</body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def capture_auth_callback(config: ExampleConfig, state: str) -> dict[str, str]:
    results: list[dict[str, str] | None] = []
    event = threading.Event()
    _CallbackHandler.callback_path = config.auth.callback_path if config.auth.callback_path.startswith("/") else f"/{config.auth.callback_path}"
    _CallbackHandler.queue_ref = results
    _CallbackHandler.event_ref = event

    server: ThreadingHTTPServer | None = None
    thread: threading.Thread | None = None
    listener_started = False

    try:
        server = ThreadingHTTPServer((config.auth.callback_host, config.auth.callback_port), _CallbackHandler)
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        listener_started = True
    except OSError:
        listener_started = False

    query_values = {
        "redirect_uri": config.callback_url,
        "client_id": config.auth.client_id.strip(),
        "response_type": "code",
        "state": state,
    }
    if config.resolved_auth_scope:
        query_values["scope"] = config.resolved_auth_scope
    signin_url = f"{authorize_url(config)}?{urlencode(query_values)}"

    print("")
    print("Open this URL to sign in with TWC SSO:")
    print(signin_url)
    print("")

    if config.auth.open_browser:
        webbrowser.open(signin_url)

    callback_params: dict[str, str] | None = None

    if listener_started:
        print(f"Waiting for callback on {config.callback_url} ...")
        if event.wait(timeout=config.auth.auth_timeout_seconds):
            callback_params = results[-1] if results else None
        else:
            print("No callback arrived before timeout.")

    if callback_params is None:
        pasted_url = input("Paste the full callback URL from the browser: ").strip()
        if not pasted_url:
            raise ExampleError("No callback URL was provided.")
        parsed = urlparse(pasted_url)
        callback_params = {key: values[0] for key, values in parse_qs(parsed.query).items() if values}

    if server is not None:
        try:
            server.server_close()
        except OSError:
            pass
    if thread is not None and thread.is_alive():
        thread.join(timeout=1.0)

    if not callback_params:
        raise ExampleError("No callback parameters were captured from the TWC sign-in flow.")

    if not callback_params.get("state"):
        raise ExampleError("TWC OIDC callback did not include state.")
    if callback_params["state"] != state:
        raise ExampleError("TWC callback state mismatch.")
    if callback_params.get("error"):
        detail = callback_params.get("error_description") or callback_params["error"]
        raise ExampleError(f"TWC sign-in returned an error: {detail}")

    code = callback_params.get("code")
    if not code:
        raise ExampleError("TWC callback did not include an authorization code.")
    return callback_params


def ensure_authenticated_token(config: ExampleConfig) -> TokenBundle:
    cached = load_token_bundle(config)
    if cached and not cached.is_expired:
        return cached
    if cached and cached.refresh_token:
        refreshed = refresh_auth_token(config, cached.refresh_token)
        save_token_bundle(config, refreshed)
        return refreshed

    state = secrets.token_urlsafe(24)
    callback = capture_auth_callback(config, state)
    bundle = exchange_auth_code(config, callback["code"])
    save_token_bundle(config, bundle)
    return bundle


class _StrictFormatDict(dict[str, Any]):
    def __missing__(self, key: str) -> Any:
        raise ExampleError(f"Missing config value for placeholder: {key}")


class TwcExampleClient:
    def __init__(self, config: ExampleConfig, bundle: TokenBundle) -> None:
        self.config = config
        self.bundle = bundle
        self.session = requests_session(config)
        self.session.headers["Authorization"] = f"Token {bundle.rest_token}"

    def build_url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        normalized_path = path if path.startswith("/") else f"/{path}"
        return f"{normalize_base_url(self.config.base_url)}{normalized_path}"

    def request_json(
        self,
        method: str,
        candidates: list[str],
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        text_body: str | None = None,
        timeout: int | None = None,
    ) -> Any:
        timeout_value = timeout or self.config.request_timeout_seconds
        last_status: int | None = None
        last_error: Exception | None = None

        for candidate in candidates:
            headers: dict[str, str] = {}
            body: Any = None
            if json_body is not None:
                body = json_body
            if text_body is not None:
                headers["Content-Type"] = "text/plain"
                body = text_body

            try:
                response = self.session.request(
                    method=method,
                    url=self.build_url(candidate),
                    params=params,
                    json=json_body if text_body is None else None,
                    content=text_body,
                    headers=headers,
                    timeout=timeout_value,
                )
            except httpx.HTTPError as exc:
                last_error = exc
                continue

            last_status = response.status_code
            if response.status_code in {404, 405}:
                continue
            if response.status_code == 401:
                raise ExampleError(f"{method} {candidate} returned 401 Unauthorized.")
            if response.status_code == 403:
                raise ExampleError(f"{method} {candidate} returned 403 Forbidden.")
            if response.status_code == 409:
                raise ExampleError(f"{method} {candidate} returned 409 Conflict: {response.text.strip() or 'request conflicted with server state.'}")
            if response.status_code >= 500:
                raise ExampleError(f"{method} {candidate} returned {response.status_code}: {response.text.strip() or 'server error'}")
            if response.status_code >= 400:
                raise ExampleError(f"{method} {candidate} returned {response.status_code}: {response.text.strip() or 'request failed'}")

            if not response.content:
                return {}
            try:
                return response.json()
            except ValueError as exc:
                raise ExampleError(f"{method} {candidate} returned non-JSON content.") from exc

        if last_status is not None:
            raise ExampleError(f"No usable candidate succeeded. Last status: {last_status}")
        if last_error is not None:
            raise ExampleError(f"No candidate request succeeded: {last_error}")
        raise ExampleError("No candidate request succeeded.")

    def context_map(self) -> dict[str, Any]:
        raw = asdict(self.config.context)
        return {
            **raw,
            "workspace_id": self.config.context.workspace_id,
            "resource_id": self.config.context.resource_id,
            "branch_id": self.config.context.branch_id,
            "model_id": self.config.context.model_id,
            "element_id": self.config.context.element_id,
            "artifact_id": self.config.context.artifact_id,
            "source_revision": self.config.context.source_revision,
            "target_revision": self.config.context.target_revision,
        }

    def render_candidates(self, templates: list[str]) -> list[str]:
        values = _StrictFormatDict(self.context_map())
        return [template.format_map(values) for template in templates]


def build_client() -> TwcExampleClient:
    config = load_config()
    bundle = ensure_authenticated_token(config)
    return TwcExampleClient(config, bundle)


def require_context_fields(config: ExampleConfig, *field_names: str) -> None:
    for field_name in field_names:
        value = getattr(config.context, field_name)
        if isinstance(value, str) and not value.strip():
            raise ExampleError(f"context.{field_name} must be set in {CONFIG_PATH}")
        if isinstance(value, list) and not value:
            raise ExampleError(f"context.{field_name} must contain at least one value in {CONFIG_PATH}")


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def reference_id(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("@id", "id", "href", "models:root", "resource", "kerml:resource", "value"):
            nested = value.get(key)
            if nested is not None:
                found = reference_id(nested)
                if found:
                    return found
        return None
    if isinstance(value, list):
        for item in value:
            found = reference_id(item)
            if found:
                return found
        return None
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.startswith("#"):
        candidate = candidate[1:]
    parsed = urlparse(candidate)
    if parsed.fragment and parsed.fragment != "it":
        return parsed.fragment
    path = parsed.path or candidate
    segments = [segment for segment in path.split("/") if segment not in {"", ".", ".."}]
    return segments[-1] if segments else candidate


def payload_entity(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        preferred_keys = ("kerml:esiData", "kerml:name", "dcterms:title", "name", "title", "ID", "@id")
        for item in reversed(payload):
            if isinstance(item, dict) and any(key in item for key in preferred_keys):
                return item
    return None


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def container_member_ids(payload: Any) -> list[str]:
    identifiers: list[str] = []
    contains: list[Any] = []

    if isinstance(payload, dict):
        raw = payload.get("ldp:contains") or payload.get("items") or payload.get("data")
        if isinstance(raw, list):
            contains = raw
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and isinstance(item.get("ldp:contains"), list):
                contains.extend(item["ldp:contains"])

    for item in contains:
        candidate = reference_id(item)
        if candidate and candidate != "it" and candidate not in identifiers:
            identifiers.append(candidate)
    return identifiers


def element_containment_ids(payload: Any) -> list[str]:
    identifiers: list[str] = []

    if isinstance(payload, dict):
        payloads = [payload]
    elif isinstance(payload, list):
        payloads = [item for item in payload if isinstance(item, dict)]
    else:
        payloads = []

    for item in payloads:
        for key in ("ldp:contains", "kerml:ownedElement", "kerml:packagedElement"):
            raw_values = item.get(key)
            if not isinstance(raw_values, list):
                continue
            for value in raw_values:
                candidate = reference_id(value)
                if candidate and candidate != "it" and candidate not in identifiers:
                    identifiers.append(candidate)

    if identifiers:
        return identifiers

    return container_member_ids(payload)


def display_name(payload: Any, fallback_id: str) -> str:
    entity = payload_entity(payload)
    if not isinstance(entity, dict):
        return fallback_id

    esi_data = entity.get("kerml:esiData")
    if isinstance(esi_data, dict):
        for key in ("name", "qualifiedName", "ID"):
            value = esi_data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    for key in ("kerml:name", "dcterms:title", "name", "title", "ID", "@id"):
        value = entity.get(key)
        if isinstance(value, str) and value.strip():
            resolved = value.strip()
            return resolved if resolved != "#it" else fallback_id

    return fallback_id
