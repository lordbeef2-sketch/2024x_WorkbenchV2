from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from app.security.session import SessionManager
from app.services.platform import ApplicationContainer


def get_container(request: Request) -> ApplicationContainer:
    return request.app.state.container


def get_session(request: Request, container: ApplicationContainer = Depends(get_container)):
    session = container.sessions.get_session(request.cookies.get(container.settings.session_cookie_name))
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
