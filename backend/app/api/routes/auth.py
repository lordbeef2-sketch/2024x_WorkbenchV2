from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.api.deps import get_container, require_csrf
from app.models.domain import TokenLoginRequest
from app.services.platform import ApplicationContainer

router = APIRouter(prefix="/auth", tags=["auth"])


def build_session_redirect(container: ApplicationContainer, session_id: str) -> RedirectResponse:
    redirect = RedirectResponse(f"{container.settings.frontend_origin}/workspace", status_code=status.HTTP_302_FOUND)
    redirect.set_cookie(
        key=container.settings.session_cookie_name,
        value=session_id,
        httponly=True,
        secure=container.settings.secure_cookies,
        samesite="lax",
        max_age=container.settings.session_ttl_minutes * 60,
        path="/",
    )
    return redirect


@router.get("/session")
def get_session_snapshot(request: Request, container: ApplicationContainer = Depends(get_container)):
    return container.platform.get_session_snapshot(request.cookies.get(container.settings.session_cookie_name))


@router.get("/options")
def get_auth_options(container: ApplicationContainer = Depends(get_container)):
    return {
        "token_signin_enabled": True,
        "csrf_header_name": container.settings.csrf_header_name,
    }


@router.get("/signin/{server_id}")
async def signin(server_id: str, request: Request, container: ApplicationContainer = Depends(get_container)):
    server = container.platform.get_server(server_id)
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server profile not found")

    try:
        session = await container.platform.login_with_upstream_session(
            server.id,
            access_token=container.settings.extract_upstream_access_token(request.headers),
            session_cookies=container.settings.extract_upstream_auth_cookies(request.cookies),
            preferred_username=container.settings.extract_upstream_username(request.headers),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return build_session_redirect(container, session.session_id)


@router.post("/token")
async def token_login(
    payload: TokenLoginRequest,
    response: Response,
    container: ApplicationContainer = Depends(get_container),
):
    try:
        session = await container.platform.login_with_token(payload)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server profile not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    response.set_cookie(
        key=container.settings.session_cookie_name,
        value=session.session_id,
        httponly=True,
        secure=container.settings.secure_cookies,
        samesite="lax",
        max_age=container.settings.session_ttl_minutes * 60,
        path="/",
    )
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
