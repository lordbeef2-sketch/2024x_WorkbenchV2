from __future__ import annotations

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


def build_session_redirect(container: ApplicationContainer, session_id: str) -> RedirectResponse:
    redirect = RedirectResponse(f"{container.settings.frontend_origin}/workspace", status_code=status.HTTP_302_FOUND)
    set_session_cookie(redirect, container, session_id)
    clear_pending_server_cookie(redirect, container)
    return redirect


def build_twc_redirect(container: ApplicationContainer, server_id: str, server_base_url: str) -> RedirectResponse:
    redirect = RedirectResponse(server_base_url, status_code=status.HTTP_302_FOUND)
    set_pending_server_cookie(redirect, container, server_id)
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
        return snapshot

    access_token = container.settings.extract_upstream_access_token(request.headers)
    session_cookies = container.settings.extract_upstream_auth_cookies(request.cookies)
    if access_token or session_cookies:
        try:
            session = await container.platform.login_with_upstream_session(
                pending_server.id,
                access_token=access_token,
                session_cookies=session_cookies,
                preferred_username=container.settings.extract_upstream_username(request.headers),
                upstream_roles=container.settings.extract_upstream_roles(request.headers),
                upstream_groups=container.settings.extract_upstream_groups(request.headers),
            )
        except PermissionError:
            pass
        else:
            set_session_cookie(response, container, session.session_id)
            clear_pending_server_cookie(response, container)
            return container.platform.get_session_snapshot(session.session_id)

    return snapshot.model_copy(update={"pending_server": pending_server})


@router.get("/options")
def get_auth_options(container: ApplicationContainer = Depends(get_container)):
    return {
        "token_signin_enabled": True,
        "csrf_header_name": container.settings.csrf_header_name,
    }


@router.get("/signin/{server_id}")
async def signin(server_id: str, request: Request, container: ApplicationContainer = Depends(get_container)):
    server = container.platform.get_server(server_id, include_disabled=False)
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset server not found")

    access_token = container.settings.extract_upstream_access_token(request.headers)
    session_cookies = container.settings.extract_upstream_auth_cookies(request.cookies)
    if not access_token and not session_cookies:
        return build_twc_redirect(container, server.id, server.base_url)

    try:
        session = await container.platform.login_with_upstream_session(
            server.id,
            access_token=access_token,
            session_cookies=session_cookies,
            preferred_username=container.settings.extract_upstream_username(request.headers),
            upstream_roles=container.settings.extract_upstream_roles(request.headers),
            upstream_groups=container.settings.extract_upstream_groups(request.headers),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
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
    return {"ok": True}
