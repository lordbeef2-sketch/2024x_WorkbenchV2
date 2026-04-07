from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.api.deps import get_container, require_csrf
from app.models.domain import TokenLoginRequest
from app.services.platform import ApplicationContainer

router = APIRouter(prefix="/auth", tags=["auth"])

logger = structlog.get_logger(__name__)

REDIRECT_SIGNIN_MESSAGE = (
    "Sign in via TWC redirects to the selected Teamwork Cloud SAML v2 login entry point and completes when the callback receives authenticated Teamwork Cloud session cookies or a forwarded user-scoped TWC token from your deployment."
)


def set_session_cookie(response: Response, container: ApplicationContainer, session_id: str) -> None:
    response.set_cookie(
        key=container.settings.session_cookie_name,
        value=session_id,
        httponly=True,
        secure=container.settings.secure_cookies,
        samesite="lax",
        max_age=container.settings.session_ttl_minutes * 60,
        path="/",
    )


def set_pending_server_cookie(response: Response, container: ApplicationContainer, server_id: str) -> None:
    response.set_cookie(
        key=container.settings.pending_server_cookie_name,
        value=server_id,
        httponly=True,
        secure=container.settings.secure_cookies,
        samesite="lax",
        max_age=container.settings.session_ttl_minutes * 60,
        path="/",
    )


def clear_pending_server_cookie(response: Response, container: ApplicationContainer) -> None:
    response.delete_cookie(container.settings.pending_server_cookie_name, path="/")


def clear_auth_state_cookie(response: Response, container: ApplicationContainer) -> None:
    response.delete_cookie(container.settings.auth_state_cookie_name, path="/")


def set_auth_state_cookie(response: Response, container: ApplicationContainer, value: str) -> None:
    response.set_cookie(
        key=container.settings.auth_state_cookie_name,
        value=value,
        httponly=True,
        secure=container.settings.secure_cookies,
        samesite="lax",
        max_age=container.settings.twc_auth_state_ttl_minutes * 60,
        path="/",
    )


def build_session_redirect(container: ApplicationContainer, session_id: str) -> RedirectResponse:
    redirect = RedirectResponse(f"{container.settings.resolved_app_origin}/workspace", status_code=status.HTTP_302_FOUND)
    set_session_cookie(redirect, container, session_id)
    clear_pending_server_cookie(redirect, container)
    clear_auth_state_cookie(redirect, container)
    return redirect


def build_error_redirect(container: ApplicationContainer, detail: str) -> RedirectResponse:
    query = urlencode({"authError": detail})
    redirect = RedirectResponse(f"{container.settings.resolved_app_origin}/?{query}", status_code=status.HTTP_302_FOUND)
    clear_pending_server_cookie(redirect, container)
    clear_auth_state_cookie(redirect, container)
    return redirect


def upstream_signin_context(request: Request, container: ApplicationContainer) -> tuple[str | None, dict[str, str], str | None]:
    access_token = container.settings.extract_upstream_access_token(request.headers)
    session_cookies = container.settings.extract_upstream_auth_cookies(request.cookies)
    preferred_username = container.settings.extract_upstream_username(request.headers)
    return access_token, session_cookies, preferred_username


def _urlsafe_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))


def create_auth_state_cookie(container: ApplicationContainer, server_id: str) -> tuple[str, str]:
    state = secrets.token_urlsafe(24)
    payload = json.dumps(
        {
            "state": state,
            "server_id": server_id,
            "issued_at": datetime.now(UTC).isoformat(),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    signature = hmac.new(container.settings.session_secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return state, f"{_urlsafe_b64encode(payload)}.{_urlsafe_b64encode(signature)}"


def load_auth_state_cookie(container: ApplicationContainer, raw_value: str | None) -> dict[str, str] | None:
    if not raw_value or "." not in raw_value:
        return None

    encoded_payload, encoded_signature = raw_value.split(".", 1)
    try:
        payload = _urlsafe_b64decode(encoded_payload)
        signature = _urlsafe_b64decode(encoded_signature)
    except Exception:
        return None

    expected_signature = hmac.new(container.settings.session_secret.encode("utf-8"), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    issued_at_raw = data.get("issued_at")
    if not isinstance(issued_at_raw, str):
        return None
    try:
        issued_at = datetime.fromisoformat(issued_at_raw)
    except ValueError:
        return None

    if issued_at < datetime.now(UTC) - timedelta(minutes=container.settings.twc_auth_state_ttl_minutes):
        return None

    if not isinstance(data.get("state"), str) or not isinstance(data.get("server_id"), str):
        return None
    return {"state": data["state"], "server_id": data["server_id"]}


def build_callback_url(container: ApplicationContainer, state: str) -> str:
    query = urlencode({"state": state})
    return f"{container.settings.resolved_twc_auth_callback_url}?{query}"


def build_twc_saml_signin_url(container: ApplicationContainer, server, state: str) -> str:
    callback_url = build_callback_url(container, state)
    login_path = container.settings.twc_saml_login_path.strip() or "/osmc/authen/login"
    if not login_path.startswith("/"):
        login_path = f"/{login_path}"
    login_url = f"{server.base_url.rstrip('/')}{login_path}"
    query = urlencode(
        {
            container.settings.twc_saml_return_url_parameter: callback_url,
            "RelayState": state,
        }
    )
    separator = "&" if "?" in login_url else "?"
    return f"{login_url}{separator}{query}"


@router.get("/session")
async def get_session_snapshot(
    request: Request,
    response: Response,
    container: ApplicationContainer = Depends(get_container),
):
    snapshot = container.platform.get_session_snapshot(request.cookies.get(container.settings.session_cookie_name))
    if snapshot.authenticated:
        return snapshot

    pending_server_id = request.cookies.get(container.settings.pending_server_cookie_name)
    if not pending_server_id:
        return snapshot

    pending_server = container.platform.get_server(pending_server_id, include_disabled=False)
    if not pending_server:
        clear_pending_server_cookie(response, container)
        clear_auth_state_cookie(response, container)
        return snapshot

    return snapshot.model_copy(update={"pending_server": pending_server})


@router.get("/options")
def get_auth_options(container: ApplicationContainer = Depends(get_container)):
    return {
        "token_signin_enabled": True,
        "redirect_signin_enabled": True,
        "redirect_signin_message": REDIRECT_SIGNIN_MESSAGE,
        "csrf_header_name": container.settings.csrf_header_name,
    }


@router.get("/signin/{server_id}")
async def signin(server_id: str, container: ApplicationContainer = Depends(get_container)):
    server = container.platform.get_server(server_id, include_disabled=False)
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset server not found")

    state, cookie_value = create_auth_state_cookie(container, server.id)
    twc_signin_url = build_twc_saml_signin_url(container, server, state)
    redirect = RedirectResponse(twc_signin_url, status_code=status.HTTP_302_FOUND)
    set_pending_server_cookie(redirect, container, server.id)
    set_auth_state_cookie(redirect, container, cookie_value)
    logger.info(
        "auth-mode-selected",
        auth_mode="twc-saml-redirect-start",
        server_id=server.id,
        twc_login_path=container.settings.twc_saml_login_path,
        callback=container.settings.resolved_twc_auth_callback_url,
    )
    return redirect


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    container: ApplicationContainer = Depends(get_container),
):
    if error:
        logger.warning("auth-callback-failed", auth_mode="redirect-callback", detail=error_description or error)
        return build_error_redirect(container, error_description or error)

    pending_server_id = request.cookies.get(container.settings.pending_server_cookie_name)
    auth_state = load_auth_state_cookie(container, request.cookies.get(container.settings.auth_state_cookie_name))
    if not pending_server_id or not auth_state:
        logger.warning("auth-callback-failed", auth_mode="redirect-callback", detail="Authentication state is missing or expired")
        return build_error_redirect(container, "Authentication state is missing or expired. Start Sign in via TWC again.")

    if auth_state["server_id"] != pending_server_id:
        logger.warning("auth-callback-failed", auth_mode="redirect-callback", detail="Selected Teamwork Cloud server no longer matches callback state")
        return build_error_redirect(container, "Selected Teamwork Cloud server no longer matches callback state. Start Sign in via TWC again.")

    relay_state = request.query_params.get("RelayState")
    callback_state = state or relay_state
    if callback_state and callback_state != auth_state["state"]:
        logger.warning("auth-callback-failed", auth_mode="redirect-callback", detail="Authentication state mismatch")
        return build_error_redirect(container, "Authentication state mismatch. Start Sign in via TWC again.")

    server = container.platform.get_server(auth_state["server_id"], include_disabled=False)
    if not server:
        logger.warning("auth-callback-failed", auth_mode="redirect-callback", detail="Preset server not found")
        return build_error_redirect(container, "Preset server not found")

    access_token, session_cookies, preferred_username = upstream_signin_context(request, container)
    if not access_token and not session_cookies:
        logger.warning(
            "auth-callback-failed",
            auth_mode="redirect-callback",
            server_id=server.id,
            detail="No upstream Teamwork Cloud session or token was forwarded to the callback.",
        )
        return build_error_redirect(
            container,
            "TWC SAML sign-in completed, but the app callback did not receive any Teamwork Cloud session cookies or forwarded access token. Configure the proxy or callback return flow to forward the authenticated TWC context.",
        )

    try:
        session = await container.platform.login_with_upstream_session(
            server.id,
            access_token=access_token,
            session_cookies=session_cookies,
            preferred_username=preferred_username,
            upstream_roles=container.settings.extract_upstream_roles(request.headers),
            upstream_groups=container.settings.extract_upstream_groups(request.headers),
        )
    except PermissionError as exc:
        logger.warning("auth-callback-failed", auth_mode="redirect-callback", server_id=server.id, detail=str(exc))
        return build_error_redirect(container, str(exc))

    logger.info(
        "auth-mode-selected",
        auth_mode="redirect-callback-complete",
        server_id=server.id,
        user=session.user.preferred_username,
        has_access_token=bool(access_token),
        cookie_count=len(session_cookies),
    )
    return build_session_redirect(container, session.session_id)


@router.post("/token")
async def token_login(
    payload: TokenLoginRequest,
    request: Request,
    response: Response,
    container: ApplicationContainer = Depends(get_container),
):
    logger.info("auth-mode-selected", auth_mode="token", server_id=payload.server_id)
    try:
        session = await container.platform.login_with_token(
            payload,
            upstream_roles=container.settings.extract_upstream_roles(request.headers),
            upstream_groups=container.settings.extract_upstream_groups(request.headers),
        )
    except KeyError as exc:
        logger.warning("auth-token-login-failed", auth_mode="token", server_id=payload.server_id, detail="Preset server not found")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset server not found") from exc
    except PermissionError as exc:
        logger.warning("auth-token-login-failed", auth_mode="token", server_id=payload.server_id, detail=str(exc))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    set_session_cookie(response, container, session.session_id)
    clear_pending_server_cookie(response, container)
    return container.platform.get_session_snapshot(session.session_id)


@router.post("/logout")
def logout(
    response: Response,
    request: Request,
    session=Depends(require_csrf),
    container: ApplicationContainer = Depends(get_container),
):
    session_id = request.cookies.get(container.settings.session_cookie_name)
    if session_id:
        container.sessions.destroy_session(session_id)
    response.delete_cookie(container.settings.session_cookie_name, path="/")
    clear_pending_server_cookie(response, container)
    clear_auth_state_cookie(response, container)
    return {"ok": True}
