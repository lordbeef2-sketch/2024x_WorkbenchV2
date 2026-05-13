from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from app.security.session import SessionManager
from app.services.platform import ApplicationContainer


def get_container(request: Request) -> ApplicationContainer:
    return request.app.state.container


def _extract_bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


async def get_session(request: Request, container: ApplicationContainer = Depends(get_container)):
    session = await container.platform.get_live_session(request.cookies.get(container.settings.session_cookie_name))
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return session


def require_csrf(
    request: Request,
    session=Depends(get_session),
    container: ApplicationContainer = Depends(get_container),
):
    token = request.headers.get(container.settings.csrf_header_name)
    if not container.sessions.validate_csrf(session, token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
    return session


def require_admin(
    session=Depends(get_session),
    container: ApplicationContainer = Depends(get_container),
):
    if not container.platform.can_manage_server_presets(session):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    return session


def require_admin_csrf(
    request: Request,
    session=Depends(require_admin),
    container: ApplicationContainer = Depends(get_container),
):
    token = request.headers.get(container.settings.csrf_header_name)
    if not container.sessions.validate_csrf(session, token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
    return session


def require_cache_ingest_token(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    token = _extract_bearer_token(request)
    if not token or token not in set(container.settings.cache_ingest_tokens):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Valid cache ingest bearer token required")
    return token


def require_cache_api_token(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Valid cache API bearer token required")
    username = container.settings.cache_api_tokens.get(token)
    if not username or not username.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Valid cache API bearer token required")
    return username.strip()
