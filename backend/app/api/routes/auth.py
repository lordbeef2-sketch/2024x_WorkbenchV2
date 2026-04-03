from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.api.deps import get_container, get_session, require_csrf
from app.models.domain import PATLoginRequest
from app.services.platform import ApplicationContainer

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/session")
def get_session_snapshot(request: Request, container: ApplicationContainer = Depends(get_container)):
    return container.platform.get_session_snapshot(request.cookies.get(container.settings.session_cookie_name))


@router.get("/options")
def get_auth_options(container: ApplicationContainer = Depends(get_container)):
    return {
        "pat_enabled": container.settings.enable_pat_login,
        "csrf_header_name": container.settings.csrf_header_name,
    }


@router.get("/signin/{server_id}")
async def signin(server_id: str, container: ApplicationContainer = Depends(get_container)):
    try:
        target_url = await container.platform.create_signin_url(server_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server profile not found") from exc
    return RedirectResponse(target_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/callback")
async def callback(
    code: str = Query(...),
    state: str = Query(...),
    serverId: str | None = Query(default=None),
    container: ApplicationContainer = Depends(get_container),
):
    resolved_server_id = serverId or container.oauth.get_pending_server_id(state)
    if not resolved_server_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unable to resolve the server profile for this callback")

    server = container.platform.get_server(resolved_server_id)
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server profile not found")

    try:
        oauth_result = await container.oauth.handle_callback(server, code, state)
        session = await container.platform.finalize_oauth(server.id, oauth_result)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    redirect = RedirectResponse(f"{container.settings.frontend_origin}/workspace", status_code=status.HTTP_302_FOUND)
    redirect.set_cookie(
        key=container.settings.session_cookie_name,
        value=session.session_id,
        httponly=True,
        secure=container.settings.secure_cookies,
        samesite="lax",
        max_age=container.settings.session_ttl_minutes * 60,
        path="/",
    )
    return redirect


@router.post("/pat")
async def pat_login(
    payload: PATLoginRequest,
    response: Response,
    container: ApplicationContainer = Depends(get_container),
):
    try:
        session = await container.platform.login_with_pat(payload)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server profile not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

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
