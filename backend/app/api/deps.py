# Created by: Raymond Reeves Engineering Tech 4 2026
from __future__ import annotations

from datetime import timedelta

from fastapi import Depends, HTTPException, Request, status

from app.models.domain import AuthorizationContext, CacheApiKeyScope, SessionData, UserContext, WorkbenchUserRole, utcnow
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
    if session:
        return session

    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workbench API keys are enabled for read routes. Write routes still require a browser session and CSRF token.")
    identity = container.platform.authenticate_cache_api_token(token)
    if not identity or not identity.preferred_username.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Valid Workbench API bearer token required")
    if CacheApiKeyScope.READ not in identity.scopes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This API key does not allow workspace reads.")

    preferred_username = identity.preferred_username.strip()
    user_id = preferred_username.lower()
    server_id = (
        request.query_params.get("serverId")
        or request.query_params.get("server_id")
        or request.headers.get("x-workbench-server-id")
        or request.headers.get("x-twc-server-id")
        or ""
    ).strip()
    user_state = container.repo.get_user_server_state(user_id)
    if not server_id and user_state:
        server_id = (user_state.selected_server_id or user_state.last_used_server_id or "").strip()
    server = container.platform.get_server(server_id, include_disabled=True) if server_id else None
    if server is None:
        servers = container.repo.list_servers(include_disabled=True)
        server = servers[0] if servers else None
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No Workbench server profile is configured.")

    user_record = container.repo.get_workbench_user(user_id)
    is_admin = bool(user_record and user_record.enabled and user_record.role == WorkbenchUserRole.ADMIN)
    is_group_manager = bool(
        user_record
        and user_record.enabled
        and user_record.role in {WorkbenchUserRole.ADMIN, WorkbenchUserRole.GROUP_MANAGER}
    )
    return SessionData(
        server=server,
        user=UserContext(
            preferred_username=preferred_username,
            server_id=server.id,
            server_name=server.name,
            auth_source="workbench-local",
        ),
        authorization_context=AuthorizationContext(
            roles=[user_record.role.value] if user_record and user_record.enabled else [],
            source="workbench-api-key",
            can_manage_server_presets=is_admin,
            can_manage_groups=is_group_manager,
        ),
        encrypted_credentials="",
        capabilities=container.platform._snapshot_capabilities(server),
        created_at=utcnow(),
        expires_at=utcnow() + timedelta(hours=1),
    )


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


def require_group_manager(
    session=Depends(get_session),
    container: ApplicationContainer = Depends(get_container),
):
    if not container.platform.can_manage_groups(session):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Group manager access required")
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


def require_group_manager_csrf(
    request: Request,
    session=Depends(require_group_manager),
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
    if token and container.platform.is_valid_cache_ingest_token(token):
        return token
    identity = container.platform.authenticate_cache_api_token(token or "")
    if not identity or CacheApiKeyScope.WRITE not in identity.scopes:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Valid cache ingest bearer token required")
    return identity


def require_cache_api_token(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Valid cache API bearer token required")
    identity = container.platform.authenticate_cache_api_token(token)
    if not identity or not identity.preferred_username.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Valid cache API bearer token required")
    if CacheApiKeyScope.READ not in identity.scopes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This API key does not allow cache reads.")
    return identity.preferred_username.strip()


def require_cache_api_identity(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Valid cache API bearer token required")
    identity = container.platform.authenticate_cache_api_token(token)
    if not identity or not identity.preferred_username.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Valid cache API bearer token required")
    return identity


def require_cache_api_scope(scope: CacheApiKeyScope):
    def dependency(identity=Depends(require_cache_api_identity)):
        if scope not in identity.scopes:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"This API key does not allow {scope.value} access.")
        return identity

    return dependency


async def require_workspace_read_access(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    token = _extract_bearer_token(request)
    if token:
        identity = container.platform.authenticate_cache_api_token(token)
        if not identity or not identity.preferred_username.strip():
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Valid Workbench API bearer token required")
        if CacheApiKeyScope.READ not in identity.scopes:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This API key does not allow workspace reads.")
        return {"source": "api-key", "identity": identity, "session": None}
    session = await container.platform.get_live_session(request.cookies.get(container.settings.session_cookie_name))
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return {"source": "session", "identity": None, "session": session}
