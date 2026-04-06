from __future__ import annotations

from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.api.deps import get_container, require_csrf
from app.models.domain import TokenLoginRequest
from app.services.platform import ApplicationContainer

router = APIRouter(prefix="/auth", tags=["auth"])


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


def set_auth_state_cookie(response: Response, container: ApplicationContainer, payload: str) -> None:
    response.set_cookie(
        key=container.settings.auth_state_cookie_name,
        value=payload,
        httponly=True,
        secure=container.settings.secure_cookies,
        samesite="lax",
        max_age=container.settings.twc_auth_state_ttl_minutes * 60,
        path="/",
    )


def clear_auth_state_cookie(response: Response, container: ApplicationContainer) -> None:
    response.delete_cookie(container.settings.auth_state_cookie_name, path="/")


def build_session_redirect(container: ApplicationContainer, session_id: str) -> RedirectResponse:
    redirect = RedirectResponse(f"{container.settings.resolved_app_origin}/workspace", status_code=status.HTTP_302_FOUND)
    set_session_cookie(redirect, container, session_id)
    clear_pending_server_cookie(redirect, container)
    clear_auth_state_cookie(redirect, container)
    return redirect


def build_twc_redirect(container: ApplicationContainer, server_id: str, authorization_url: str, auth_state_payload: str) -> RedirectResponse:
    redirect = RedirectResponse(authorization_url, status_code=status.HTTP_302_FOUND)
    set_pending_server_cookie(redirect, container, server_id)
    set_auth_state_cookie(redirect, container, auth_state_payload)
    return redirect


def build_error_redirect(container: ApplicationContainer, detail: str) -> RedirectResponse:
    query = urlencode({"authError": detail})
    redirect = RedirectResponse(f"{container.settings.resolved_app_origin}/?{query}", status_code=status.HTTP_302_FOUND)
    clear_auth_state_cookie(redirect, container)
    return redirect


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
        "redirect_signin_enabled": container.oauth.is_configured(),
        "redirect_signin_message": container.oauth.configuration_error(),
        "csrf_header_name": container.settings.csrf_header_name,
    }


@router.get("/signin/{server_id}")
async def signin(server_id: str, container: ApplicationContainer = Depends(get_container)):
    server = container.platform.get_server(server_id, include_disabled=False)
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset server not found")

    configuration_error = container.oauth.configuration_error()
    if configuration_error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=configuration_error)

    auth_state_payload, pending_state = container.oauth.create_pending_state_cookie(server.id)
    authorization_url = await container.oauth.create_authorization_url(server, pending_state.state)
    return build_twc_redirect(container, server.id, authorization_url, auth_state_payload)


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
        return build_error_redirect(container, error_description or error)
    if not code or not state:
        return build_error_redirect(container, "Authentication callback is missing the required code or state parameter")

    auth_state_cookie = request.cookies.get(container.settings.auth_state_cookie_name)
    pending = container.oauth.load_pending_state(auth_state_cookie)
    if not pending or pending.state != state:
        return build_error_redirect(container, "Authentication state is missing, expired, or invalid")

    server = container.platform.get_server(pending.server_id, include_disabled=False)
    if not server:
        return build_error_redirect(container, "The selected preset server is no longer available")

    try:
        callback_result = await container.oauth.handle_callback(server, code)
        session = await container.platform.login_with_token_bundle(
            server.id,
            callback_result.token_bundle,
            preferred_username=callback_result.preferred_username,
        )
    except (PermissionError, ValueError, httpx.HTTPError) as exc:
        return build_error_redirect(container, str(exc))

    return build_session_redirect(container, session.session_id)


@router.post("/token")
async def token_login(
    payload: TokenLoginRequest,
    request: Request,
    response: Response,
    container: ApplicationContainer = Depends(get_container),
):
    try:
        session = await container.platform.login_with_token(
            payload,
            upstream_roles=container.settings.extract_upstream_roles(request.headers),
            upstream_groups=container.settings.extract_upstream_groups(request.headers),
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset server not found") from exc
    except PermissionError as exc:
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
